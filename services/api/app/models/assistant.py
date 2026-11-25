from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, tenant_fk, uuid_pk


def _tenant_col() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)


class Conversation(Base, Timestamps):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_conversations_tenant_id_id"),
        CheckConstraint("channel in ('web_voice','web_text','embed','telephony')", name="channel"),
        CheckConstraint("status in ('active','archived')", name="status"),
        Index("ix_conversations_tenant_user_updated", "tenant_id", "user_id", "updated_at"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_col()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New conversation")
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    next_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        tenant_fk("conversation_id", "conversations"),
        UniqueConstraint("conversation_id", "sequence", name="uq_messages_conversation_sequence"),
        UniqueConstraint("tenant_id", "conversation_id", "client_turn_id", name="uq_messages_client_turn"),
        CheckConstraint("role in ('user','assistant','tool','system')", name="role"),
        CheckConstraint("status in ('final','interrupted','failed')", name="status"),
        Index("ix_messages_conversation_sequence", "conversation_id", "sequence"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_col()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    turn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    client_turn_id: Mapped[str | None] = mapped_column(String(64))
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="final")
    # Characters of the reply actually played before an interruption (§4 step 6).
    played_chars: Mapped[int | None] = mapped_column(Integer)
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(96))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class AssistantSession(Base, Timestamps):
    """Voice/text session with server-authoritative mute state (§23.1a, §27.2)."""

    __tablename__ = "assistant_sessions"
    __table_args__ = (
        tenant_fk("conversation_id", "conversations"),
        CheckConstraint(
            "state in ('idle','listening','thinking','speaking','awaiting_approval','reconnecting','ended')",
            name="state",
        ),
        CheckConstraint("generation >= 0 and last_sequence >= 0", name="counters_nonneg"),
        Index("ix_assistant_sessions_tenant_user", "tenant_id", "user_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_col()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="idle")
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Both default true until an explicit user gesture (§27.2).
    mic_muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    speaker_muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    policy_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemoryItem(Base, Timestamps):
    __tablename__ = "memory_items"
    __table_args__ = (
        CheckConstraint("kind in ('semantic','episodic','procedural')", name="kind"),
        CheckConstraint("scope in ('personal','organization')", name="scope"),
        CheckConstraint("(scope = 'personal') = (user_id is not null)", name="scope_owner"),
        CheckConstraint("confidence >= 0 and confidence <= 1", name="confidence_range"),
        Index("ix_memory_items_tenant_user", "tenant_id", "user_id", "updated_at"),
        Index("ix_memory_items_fts", text("to_tsvector('simple', content)"), postgresql_using="gin"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_col()
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    confidence: Mapped[float] = mapped_column(nullable=False, default=1.0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding: Mapped[list[float] | None] = mapped_column(Vector())
    embedding_model: Mapped[str | None] = mapped_column(String(96))
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)


class AssistantIdentityPreference(Base, Timestamps):
    """KOK-20 identity preferences (§28.2)."""

    __tablename__ = "assistant_identity_preferences"
    __table_args__ = (
        CheckConstraint("scope in ('tenant','user','agent')", name="scope"),
        CheckConstraint(
            "(scope = 'tenant' and user_id is null and agent_id is null) or "
            "(scope = 'user' and user_id is not null and agent_id is null) or "
            "(scope = 'agent' and agent_id is not null and user_id is null)",
            name="one_target",
        ),
        CheckConstraint("wake_status in ('disabled','pending','validated','unsupported')", name="wake_status"),
        CheckConstraint("response_length in ('short','medium','long')", name="response_length"),
        CheckConstraint("speaking_rate >= 0.5 and speaking_rate <= 2.0", name="speaking_rate"),
        CheckConstraint("char_length(display_name) between 1 and 40", name="display_name_len"),
        Index("uq_identity_tenant_scope", "tenant_id", unique=True, postgresql_where=text("scope = 'tenant'")),
        Index("uq_identity_user", "tenant_id", "user_id", unique=True, postgresql_where=text("scope = 'user'")),
        Index("uq_identity_agent", "tenant_id", "agent_id", unique=True, postgresql_where=text("scope = 'agent'")),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_col()
    scope: Mapped[str] = mapped_column(String(8), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    display_name: Mapped[str] = mapped_column(String(40), nullable=False)
    spoken_name: Mapped[str] = mapped_column(String(60), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    pronunciation_hint: Mapped[str | None] = mapped_column(String(120))
    wake_phrase: Mapped[str | None] = mapped_column(String(60))
    wake_status: Mapped[str] = mapped_column(String(16), nullable=False, default="disabled")
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    voice_profile_id: Mapped[str | None] = mapped_column(String(64))
    response_length: Mapped[str] = mapped_column(String(8), nullable=False, default="medium")
    speaking_rate: Mapped[float] = mapped_column(nullable=False, default=1.0)
    allow_personal_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    updated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
