import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin


class Agent(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    template: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | published | archived
    provider: Mapped[str] = mapped_column(String(30), default="mock")
    provider_agent_id: Mapped[str | None] = mapped_column(String(120), index=True)
    provider_llm_id: Mapped[str | None] = mapped_column(String(120))
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    latest_version: Mapped[int] = mapped_column(Integer, default=0)
    sync_status: Mapped[str] = mapped_column(String(20), default="not_synced")  # not_synced | synced | failed
    sync_error: Mapped[str | None] = mapped_column(Text)


class AgentVersion(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version"),)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentTool(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "agent_tools"
    __table_args__ = (UniqueConstraint("agent_id", "name"),)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    enabled: Mapped[bool] = mapped_column(default=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)


class KnowledgeSource(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "knowledge_sources"
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="text")  # text | url | file
    provider_kb_id: Mapped[str | None] = mapped_column(String(120))


class KnowledgeDocument(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "knowledge_documents"
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="active")
    flagged_injection: Mapped[bool] = mapped_column(default=False)
