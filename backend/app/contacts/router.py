import csv
import io
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.service import audit_ctx
from app.auth.deps import TenantContext, get_owned, require
from app.contacts.models import Contact, ContactConsent, Lead, LeadActivity, SuppressionEntry
from app.contacts.service import get_or_create_contact, suppress
from app.core.errors import AppError, Conflict
from app.core.phone import normalize_e164
from app.db.session import get_db
from app.schemas.common import ORM, paginate
from app.telephony.models import Call

router = APIRouter(tags=["contacts"])
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 20000


class ContactIn(BaseModel):
    phone: str
    name: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = None
    language: str | None = Field(default=None, pattern="^(en|hi|te|kn)$")
    tags: list[str] = Field(default_factory=list, max_length=30)


class ContactPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = None
    language: str | None = Field(default=None, pattern="^(en|hi|te|kn)$")
    tags: list[str] | None = None


class ContactOut(ORM):
    id: uuid.UUID
    phone_e164: str
    name: str | None
    email: str | None
    language: str | None
    tags: list
    source: str
    created_at: datetime


class ConsentIn(BaseModel):
    purpose: str = Field(min_length=2, max_length=60)
    source: str = Field(min_length=2, max_length=60)
    evidence: str = Field(min_length=3, max_length=2000)
    granted_at: datetime | None = None
    expires_at: datetime | None = None
    recording_consent: bool = False


class ConsentOut(ORM):
    id: uuid.UUID
    purpose: str
    channel: str
    status: str
    source: str
    evidence: str | None
    granted_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    recording_consent: bool


class SuppressionIn(BaseModel):
    phone: str
    reason: str = Field(default="manual", pattern="^(opt_out|dnd|complaint|manual)$")


class SuppressionOut(ORM):
    id: uuid.UUID
    phone_e164: str
    reason: str
    source: str
    created_at: datetime


@router.get("/contacts")
def list_contacts(
    ctx: TenantContext = Depends(require("contacts:read")),
    db: Session = Depends(get_db),
    q: str | None = None,
    tag: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    stmt = select(Contact).where(Contact.tenant_id == ctx.tenant_id)
    if q:
        like = f"%{q.strip()[:100]}%"
        stmt = stmt.where(or_(Contact.name.ilike(like), Contact.phone_e164.ilike(like), Contact.email.ilike(like)))
    if tag:
        stmt = stmt.where(Contact.tags.contains([tag]))
    return paginate(db, stmt.order_by(Contact.created_at.desc()), limit, offset, ContactOut)


@router.post("/contacts", response_model=ContactOut, status_code=201)
def create_contact(body: ContactIn, ctx: TenantContext = Depends(require("contacts:write")), db: Session = Depends(get_db)):
    phone = normalize_e164(body.phone)
    if db.scalar(select(Contact.id).where(Contact.tenant_id == ctx.tenant_id, Contact.phone_e164 == phone)):
        raise Conflict("A contact with this phone already exists", code="duplicate_contact")
    c = Contact(
        tenant_id=ctx.tenant_id, phone_e164=phone, name=body.name, email=body.email, language=body.language, tags=body.tags, attributes={}, source="manual"
    )
    db.add(c)
    audit_ctx(db, ctx, "contact.created", "contact", None)
    db.commit()
    return c


@router.get("/contacts/{contact_id}")
def get_contact(contact_id: uuid.UUID, ctx: TenantContext = Depends(require("contacts:read")), db: Session = Depends(get_db)) -> dict:
    c = get_owned(db, Contact, contact_id, ctx)
    leads = db.scalars(select(Lead).where(Lead.contact_id == c.id)).all()
    calls = db.scalars(select(Call).where(Call.contact_id == c.id, Call.tenant_id == ctx.tenant_id).order_by(Call.created_at.desc()).limit(50)).all()
    acts = (
        db.scalars(select(LeadActivity).where(LeadActivity.lead_id.in_([lead.id for lead in leads])).order_by(LeadActivity.created_at.desc()).limit(100)).all()
        if leads
        else []
    )
    consents = db.scalars(select(ContactConsent).where(ContactConsent.contact_id == c.id)).all()
    sup = db.scalar(select(SuppressionEntry).where(SuppressionEntry.tenant_id == ctx.tenant_id, SuppressionEntry.phone_e164 == c.phone_e164))
    timeline = [
        {"type": "call", "at": x.created_at.isoformat(), "id": str(x.id), "status": x.status, "outcome": x.outcome, "direction": x.direction} for x in calls
    ]
    timeline += [{"type": a.kind, "at": a.created_at.isoformat(), "body": a.body, "due_at": a.due_at.isoformat() if a.due_at else None} for a in acts]
    timeline.sort(key=lambda e: e["at"] or "", reverse=True)
    return {
        **ContactOut.model_validate(c).model_dump(mode="json"),
        "leads": [
            {"id": str(lead.id), "status": lead.status, "score": lead.score, "assigned_to": str(lead.assigned_to) if lead.assigned_to else None}
            for lead in leads
        ],
        "consents": [ConsentOut.model_validate(x).model_dump(mode="json") for x in consents],
        "suppressed": sup is not None,
        "suppression_reason": sup.reason if sup else None,
        "timeline": timeline,
    }


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
def update_contact(contact_id: uuid.UUID, body: ContactPatch, ctx: TenantContext = Depends(require("contacts:write")), db: Session = Depends(get_db)):
    c = get_owned(db, Contact, contact_id, ctx)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    return c


@router.post("/contacts/import")
async def import_contacts(file: UploadFile = File(...), ctx: TenantContext = Depends(require("contacts:import")), db: Session = Depends(get_db)) -> dict:
    raw = await file.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise AppError("File too large (max 5 MB)", code="file_too_large", status_code=413)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise AppError("File must be UTF-8 CSV", code="invalid_csv")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "phone" not in [f.strip().lower() for f in reader.fieldnames]:
        raise AppError("CSV must have a 'phone' column", code="invalid_csv")
    created = existing = consents = 0
    invalid: list[dict] = []
    seen: set[str] = set()
    dupes = 0
    now = datetime.now(UTC)
    for i, row in enumerate(reader, start=2):
        if i - 1 > MAX_IMPORT_ROWS:
            raise AppError(f"Too many rows (max {MAX_IMPORT_ROWS})", code="too_many_rows")
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        try:
            phone = normalize_e164(row.get("phone", ""))
        except AppError as exc:
            invalid.append({"row": i, "error": exc.message})
            continue
        if phone in seen:
            dupes += 1
            continue
        seen.add(phone)
        before = db.scalar(select(Contact.id).where(Contact.tenant_id == ctx.tenant_id, Contact.phone_e164 == phone))
        c = get_or_create_contact(db, ctx.tenant_id, phone, name=row.get("name") or None, source="import")
        if row.get("email") and not c.email and "@" in row["email"]:
            c.email = row["email"][:320]
        if row.get("language") in ("en", "hi", "te", "kn"):
            c.language = row["language"]
        if row.get("tags"):
            c.tags = list(dict.fromkeys([*(c.tags or []), *[t.strip() for t in row["tags"].split(";") if t.strip()]]))
        if before:
            existing += 1
        else:
            created += 1
        if row.get("consent_purpose"):
            if not row.get("consent_evidence"):
                invalid.append({"row": i, "error": "consent_purpose given without consent_evidence; consent not recorded"})
            else:
                try:
                    granted = datetime.fromisoformat(row["consent_granted_at"]) if row.get("consent_granted_at") else now
                    if granted.tzinfo is None:
                        raise ValueError
                except ValueError:
                    invalid.append({"row": i, "error": "consent_granted_at must be ISO-8601 with timezone"})
                    continue
                db.add(
                    ContactConsent(
                        tenant_id=ctx.tenant_id,
                        contact_id=c.id,
                        purpose=row["consent_purpose"][:60],
                        source=(row.get("consent_source") or "import")[:60],
                        evidence=row["consent_evidence"][:2000],
                        granted_at=granted,
                        status="granted",
                    )
                )
                consents += 1
    audit_ctx(db, ctx, "contacts.imported", "contact", None, created=created, existing=existing, invalid=len(invalid))
    db.commit()
    return {
        "created": created,
        "existing": existing,
        "duplicates_in_file": dupes,
        "consents_recorded": consents,
        "invalid": invalid[:500],
        "invalid_count": len(invalid),
    }


@router.post("/contacts/{contact_id}/consents", response_model=ConsentOut, status_code=201)
def add_consent(contact_id: uuid.UUID, body: ConsentIn, ctx: TenantContext = Depends(require("consent:write")), db: Session = Depends(get_db)):
    c = get_owned(db, Contact, contact_id, ctx)
    granted = body.granted_at or datetime.now(UTC)
    if body.expires_at and body.expires_at <= granted:
        raise AppError("expires_at must be after granted_at", code="invalid_consent", status_code=422)
    consent = ContactConsent(
        tenant_id=ctx.tenant_id,
        contact_id=c.id,
        purpose=body.purpose,
        source=body.source,
        evidence=body.evidence,
        granted_at=granted,
        expires_at=body.expires_at,
        recording_consent=body.recording_consent,
    )
    db.add(consent)
    audit_ctx(db, ctx, "consent.recorded", "contact", c.id, purpose=body.purpose)
    db.commit()
    return consent


@router.post("/contacts/{contact_id}/consents/{consent_id}/revoke", response_model=ConsentOut)
def revoke_consent(contact_id: uuid.UUID, consent_id: uuid.UUID, ctx: TenantContext = Depends(require("consent:write")), db: Session = Depends(get_db)):
    get_owned(db, Contact, contact_id, ctx)
    consent = get_owned(db, ContactConsent, consent_id, ctx)
    consent.status, consent.revoked_at = "revoked", datetime.now(UTC)
    audit_ctx(db, ctx, "consent.revoked", "contact", contact_id)
    db.commit()
    return consent


@router.get("/suppression")
def list_suppression(ctx: TenantContext = Depends(require("contacts:read")), db: Session = Depends(get_db), limit: int = Query(50, le=200), offset: int = 0):
    stmt = select(SuppressionEntry).where(SuppressionEntry.tenant_id == ctx.tenant_id).order_by(SuppressionEntry.created_at.desc())
    return paginate(db, stmt, limit, offset, SuppressionOut)


@router.post("/suppression", status_code=201)
def add_suppression(body: SuppressionIn, ctx: TenantContext = Depends(require("consent:write")), db: Session = Depends(get_db)) -> dict:
    phone = normalize_e164(body.phone)
    suppress(db, ctx.tenant_id, phone, body.reason, "manual")
    audit_ctx(db, ctx, "suppression.added", "suppression", None, reason=body.reason)
    db.commit()
    return {"status": "suppressed", "phone_e164": phone}


@router.delete("/suppression/{entry_id}", status_code=204)
def remove_suppression(entry_id: uuid.UUID, ctx: TenantContext = Depends(require("tenant:write")), db: Session = Depends(get_db)) -> None:
    entry = get_owned(db, SuppressionEntry, entry_id, ctx)
    if entry.reason in ("opt_out", "complaint"):
        contact = db.scalar(select(Contact).where(Contact.tenant_id == ctx.tenant_id, Contact.phone_e164 == entry.phone_e164))
        fresh = contact and db.scalar(
            select(ContactConsent.id).where(
                ContactConsent.contact_id == contact.id, ContactConsent.status == "granted", ContactConsent.granted_at > entry.created_at
            )
        )
        if not fresh:
            raise AppError("Opt-outs can only be lifted after fresh consent (granted after the opt-out) is recorded", code="forbidden_removal", status_code=409)
    db.delete(entry)
    audit_ctx(db, ctx, "suppression.removed", "suppression", entry_id)
    db.commit()
