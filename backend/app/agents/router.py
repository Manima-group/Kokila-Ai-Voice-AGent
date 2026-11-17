import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.models import Agent, AgentVersion, KnowledgeDocument, KnowledgeSource
from app.agents.templates import (
    LANGUAGES,
    TEMPLATES,
    TOOLS,
    build_system_prompt,
    looks_like_injection,
    post_call_fields,
)
from app.audit.service import audit_ctx
from app.auth.deps import TenantContext, get_owned, require
from app.billing.service import require_active
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, PaymentRequired
from app.core.phone import normalize_e164
from app.db.session import get_db
from app.schemas.common import ORM
from app.voice.base import AgentSpec, ProviderAgentRef, ProviderError, UnsupportedCapability
from app.voice.registry import get_provider

router = APIRouter(prefix="/agents", tags=["agents"])


class BusinessHours(BaseModel):
    start: str = Field(default="09:00", pattern=r"^\d{2}:\d{2}$")
    end: str = Field(default="18:00", pattern=r"^\d{2}:\d{2}$")
    timezone: str = "Asia/Kolkata"
    days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5])


class Escalation(BaseModel):
    transfer_number: str | None = None
    notify_emails: list[str] = Field(default_factory=list)

    @field_validator("transfer_number")
    @classmethod
    def _e164(cls, v: str | None) -> str | None:
        return normalize_e164(v) if v else None


class AgentConfig(BaseModel):
    languages: list[str] = Field(default_factory=lambda: ["en"], min_length=1)
    voice_id: str = Field(default="11labs-Adrian", min_length=1, max_length=120)
    greeting: str = Field(min_length=3, max_length=500)
    instructions: str = Field(min_length=10, max_length=8000)
    business_rules: list[str] = Field(default_factory=list, max_length=50)
    business_hours: BusinessHours = Field(default_factory=BusinessHours)
    allowed_tools: list[str] = Field(default_factory=list)
    escalation: Escalation = Field(default_factory=Escalation)
    outcome_fields: list[str] = Field(default_factory=list, max_length=20)
    max_call_seconds: int = Field(default=600, ge=60, le=1800)

    @field_validator("languages")
    @classmethod
    def _langs(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in LANGUAGES]
        if bad:
            raise ValueError(f"Unsupported language codes: {bad}. Allowed: {list(LANGUAGES)}")
        return list(dict.fromkeys(v))

    @field_validator("allowed_tools")
    @classmethod
    def _tools(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in TOOLS]
        if bad:
            raise ValueError(f"Unknown tools: {bad}")
        return list(dict.fromkeys(v))


class AgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    template: str
    config: AgentConfig | None = None


class AgentOut(ORM):
    id: uuid.UUID
    name: str
    description: str | None
    template: str
    status: str
    provider: str
    provider_agent_id: str | None
    published_version_id: uuid.UUID | None
    latest_version: int
    sync_status: str
    sync_error: str | None
    created_at: datetime


class VersionOut(ORM):
    id: uuid.UUID
    version: int
    config: dict
    published_at: datetime | None
    created_at: datetime


class KnowledgeSourceIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    agent_id: uuid.UUID | None = None


class KnowledgeDocIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=50000)


@router.get("/templates")
def templates(_: TenantContext = Depends(require("agents:read"))) -> dict:
    return {
        "templates": {k: {"label": v["label"], "tools": v["tools"], "outcome_fields": v["outcome_fields"]} for k, v in TEMPLATES.items()},
        "languages": LANGUAGES,
        "tools": {k: v["description"] for k, v in TOOLS.items()},
    }


@router.get("", response_model=list[AgentOut])
def list_agents(ctx: TenantContext = Depends(require("agents:read")), db: Session = Depends(get_db)):
    return db.scalars(select(Agent).where(Agent.tenant_id == ctx.tenant_id).order_by(Agent.created_at.desc())).all()


@router.post("", response_model=AgentOut, status_code=201)
def create_agent(body: AgentCreate, ctx: TenantContext = Depends(require("agents:write")), db: Session = Depends(get_db)):
    if body.template not in TEMPLATES:
        raise AppError(f"Unknown template '{body.template}'", code="invalid_template", status_code=422)
    ent = require_active(db, ctx.tenant_id)
    count = db.scalar(select(func.count()).select_from(Agent).where(Agent.tenant_id == ctx.tenant_id, Agent.status != "archived"))
    if (count or 0) >= ent.plan.max_agents:  # type: ignore[attr-defined]
        raise PaymentRequired("Agent limit reached for your plan", code="agent_limit")
    if db.scalar(select(Agent.id).where(Agent.tenant_id == ctx.tenant_id, Agent.name == body.name)):
        raise Conflict("An agent with this name already exists")
    tpl = TEMPLATES[body.template]
    config = body.config or AgentConfig(
        greeting=tpl["greeting"].format(company=ctx.tenant.name),
        instructions=tpl["instructions"],
        allowed_tools=tpl["tools"],
        outcome_fields=tpl["outcome_fields"],
    )
    agent = Agent(
        tenant_id=ctx.tenant_id,
        name=body.name,
        description=body.description,
        template=body.template,
        provider=get_settings().voice_provider,
        latest_version=1,
    )
    db.add(agent)
    db.flush()
    db.add(AgentVersion(tenant_id=ctx.tenant_id, agent_id=agent.id, version=1, config=config.model_dump(), created_by=ctx.user.id))
    audit_ctx(db, ctx, "agent.created", "agent", agent.id)
    db.commit()
    return agent


@router.get("/{agent_id}")
def get_agent(agent_id: uuid.UUID, ctx: TenantContext = Depends(require("agents:read")), db: Session = Depends(get_db)) -> dict:
    agent = get_owned(db, Agent, agent_id, ctx)
    latest = db.scalar(select(AgentVersion).where(AgentVersion.agent_id == agent.id).order_by(AgentVersion.version.desc()))
    provider_langs: list[str] = []
    try:
        provider_langs = sorted(get_provider(agent.provider).supported_languages)
    except Exception:  # noqa: BLE001 - provider not configured
        provider_langs = []
    return {
        **AgentOut.model_validate(agent).model_dump(mode="json"),
        "latest": VersionOut.model_validate(latest).model_dump(mode="json") if latest else None,
        "language_support": {
            code: {
                "adapter_supported": code in provider_langs,
                "live_verified": False,  # set only after recorded real-audio tests (see docs/TEST_PLAN.md)
            }
            for code in (latest.config.get("languages", []) if latest else [])
        },
    }


@router.get("/{agent_id}/versions", response_model=list[VersionOut])
def versions(agent_id: uuid.UUID, ctx: TenantContext = Depends(require("agents:read")), db: Session = Depends(get_db)):
    get_owned(db, Agent, agent_id, ctx)
    return db.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version.desc())).all()


@router.post("/{agent_id}/versions", response_model=VersionOut, status_code=201)
def new_version(agent_id: uuid.UUID, config: AgentConfig, ctx: TenantContext = Depends(require("agents:write")), db: Session = Depends(get_db)):
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == ctx.tenant_id).with_for_update())
    if not agent:
        get_owned(db, Agent, agent_id, ctx)
    assert agent is not None
    agent.latest_version += 1
    v = AgentVersion(tenant_id=ctx.tenant_id, agent_id=agent.id, version=agent.latest_version, config=config.model_dump(), created_by=ctx.user.id)
    db.add(v)
    audit_ctx(db, ctx, "agent.version_created", "agent", agent.id, version=v.version)
    db.commit()
    return v


def _tools_payload(config: dict, provider: str) -> list[dict]:
    base = get_settings().public_base_url.rstrip("/")
    tools: list[dict] = [{"type": "end_call", "name": "end_call", "description": "End the call politely."}]
    for name in config.get("allowed_tools", []):
        t = TOOLS[name]
        tools.append(
            {
                "type": "custom",
                "name": name,
                "description": t["description"],
                "parameters": t["parameters"],
                "url": f"{base}/api/v1/webhooks/{provider}/tools/{name}",
                "speak_during_execution": False,
                "speak_after_execution": True,
            }
        )
    transfer = (config.get("escalation") or {}).get("transfer_number")
    if transfer:
        tools.append(
            {
                "type": "transfer_call",
                "name": "transfer_to_human",
                "description": "Transfer to a human operator.",
                "transfer_destination": {"type": "predefined", "number": transfer},
            }
        )
    return tools


@router.post("/{agent_id}/versions/{version}/publish", response_model=AgentOut)
def publish(agent_id: uuid.UUID, version: int, ctx: TenantContext = Depends(require("agents:publish")), db: Session = Depends(get_db)):
    agent = get_owned(db, Agent, agent_id, ctx)
    v = db.scalar(select(AgentVersion).where(AgentVersion.agent_id == agent.id, AgentVersion.version == version))
    if not v:
        raise AppError("Version not found", code="not_found", status_code=404)
    cfg = AgentConfig.model_validate(v.config).model_dump()
    knowledge = [
        (d.title, d.content)
        for d in db.scalars(
            select(KnowledgeDocument)
            .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
            .where(
                KnowledgeSource.agent_id == agent.id,
                KnowledgeDocument.tenant_id == ctx.tenant_id,
                KnowledgeDocument.status == "active",
                KnowledgeDocument.flagged_injection.is_(False),
            )
        )
    ]
    spec = AgentSpec(
        name=f"{ctx.tenant.slug}:{agent.name}",
        system_prompt=build_system_prompt(ctx.tenant.name, cfg, knowledge),
        greeting=cfg["greeting"],
        language=cfg["languages"][0],
        voice_id=cfg["voice_id"],
        tools=_tools_payload(cfg, agent.provider),
        webhook_url=f"{get_settings().public_base_url.rstrip('/')}/api/v1/webhooks/{agent.provider}",
        post_call_fields=post_call_fields(cfg),
        max_call_seconds=cfg["max_call_seconds"],
    )
    provider = get_provider(agent.provider)
    try:
        if agent.provider_agent_id:
            provider.update_agent(ProviderAgentRef(agent.provider_agent_id, agent.provider_llm_id), spec)
        else:
            ref = provider.create_agent(spec)
            agent.provider_agent_id, agent.provider_llm_id = ref.agent_id, ref.llm_id
    except (ProviderError, UnsupportedCapability) as exc:
        agent.sync_status, agent.sync_error = "failed", str(exc)
        audit_ctx(db, ctx, "agent.publish_failed", "agent", agent.id, error=str(exc))
        db.commit()
        raise AppError(f"Provider sync failed: {exc}", code="provider_error", status_code=502)
    v.published_at = datetime.now(UTC)
    agent.published_version_id, agent.status, agent.sync_status, agent.sync_error = v.id, "published", "synced", None
    audit_ctx(db, ctx, "agent.published", "agent", agent.id, version=version)
    db.commit()
    return agent


@router.post("/{agent_id}/archive", response_model=AgentOut)
def archive(agent_id: uuid.UUID, ctx: TenantContext = Depends(require("agents:write")), db: Session = Depends(get_db)):
    agent = get_owned(db, Agent, agent_id, ctx)
    agent.status = "archived"
    audit_ctx(db, ctx, "agent.archived", "agent", agent.id)
    db.commit()
    return agent


# ---- Knowledge base ---------------------------------------------------------------------------------------------
class KSOut(ORM):
    id: uuid.UUID
    name: str
    agent_id: uuid.UUID | None
    kind: str
    created_at: datetime


class KDocOut(ORM):
    id: uuid.UUID
    title: str
    status: str
    flagged_injection: bool
    created_at: datetime


@router.get("/knowledge/sources", response_model=list[KSOut])
def list_sources(ctx: TenantContext = Depends(require("agents:read")), db: Session = Depends(get_db)):
    return db.scalars(select(KnowledgeSource).where(KnowledgeSource.tenant_id == ctx.tenant_id)).all()


@router.post("/knowledge/sources", response_model=KSOut, status_code=201)
def create_source(body: KnowledgeSourceIn, ctx: TenantContext = Depends(require("agents:write")), db: Session = Depends(get_db)):
    if body.agent_id:
        get_owned(db, Agent, body.agent_id, ctx)
    ks = KnowledgeSource(tenant_id=ctx.tenant_id, name=body.name, agent_id=body.agent_id, kind="text")
    db.add(ks)
    db.commit()
    return ks


@router.get("/knowledge/sources/{source_id}/documents", response_model=list[KDocOut])
def list_docs(source_id: uuid.UUID, ctx: TenantContext = Depends(require("agents:read")), db: Session = Depends(get_db)):
    get_owned(db, KnowledgeSource, source_id, ctx)
    return db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.source_id == source_id)).all()


@router.post("/knowledge/sources/{source_id}/documents", response_model=KDocOut, status_code=201)
def add_doc(source_id: uuid.UUID, body: KnowledgeDocIn, ctx: TenantContext = Depends(require("agents:write")), db: Session = Depends(get_db)):
    get_owned(db, KnowledgeSource, source_id, ctx)
    doc = KnowledgeDocument(
        tenant_id=ctx.tenant_id,
        source_id=source_id,
        title=body.title,
        content=body.content,
        checksum=hashlib.sha256(body.content.encode()).hexdigest(),
        flagged_injection=looks_like_injection(body.content),
    )
    db.add(doc)
    audit_ctx(db, ctx, "knowledge.document_added", "knowledge_document", None, flagged=doc.flagged_injection)
    db.commit()
    return doc


@router.delete("/knowledge/documents/{doc_id}", status_code=204)
def delete_doc(doc_id: uuid.UUID, ctx: TenantContext = Depends(require("agents:write")), db: Session = Depends(get_db)) -> None:
    doc = get_owned(db, KnowledgeDocument, doc_id, ctx)
    db.delete(doc)
    db.commit()
