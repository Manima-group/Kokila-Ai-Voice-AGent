import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin


def _user_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)


class AssistantConversation(IdMixin, TimestampMixin, TenantMixin, Base):
    """Owned by one user. Personal-mode conversations are never visible to other users or to business tools."""

    __tablename__ = "assistant_conversations"
    user_id: Mapped[uuid.UUID] = _user_fk()
    mode: Mapped[str] = mapped_column(String(20))  # business | personal
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    status: Mapped[str] = mapped_column(String(20), default="active")


class AssistantMessage(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "assistant_messages"
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("assistant_conversations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = _user_fk()
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    artifacts: Mapped[list] = mapped_column(JSONB, default=list)  # typed metric results, approvals, citations
    provider: Mapped[str | None] = mapped_column(String(30))
    model: Mapped[str | None] = mapped_column(String(80))
    language: Mapped[str | None] = mapped_column(String(10))


class MemoryItem(IdMixin, TimestampMixin, TenantMixin, Base):
    """User-controlled long-term memory. Items proposed by the assistant stay 'pending' until the user approves."""

    __tablename__ = "memory_items"
    user_id: Mapped[uuid.UUID] = _user_fk()
    scope: Mapped[str] = mapped_column(String(20), default="personal")
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | active
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class AssistantAction(IdMixin, TimestampMixin, TenantMixin, Base):
    """A consequential tool action awaiting explicit user approval (bound to exact arguments)."""

    __tablename__ = "assistant_actions"
    user_id: Mapped[uuid.UUID] = _user_fk()
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    tool_key: Mapped[str] = mapped_column(String(60))
    args: Mapped[dict] = mapped_column(JSONB)
    args_hash: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | executed | rejected | failed
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Reminder(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "reminders"
    user_id: Mapped[uuid.UUID] = _user_fk()
    text: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled | sent | cancelled


class Notification(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "notifications"
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(300))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssistantPreference(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "assistant_preferences"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)
    user_id: Mapped[uuid.UUID] = _user_fk()
    assistant_name: Mapped[str] = mapped_column(String(40), default="Kokila")
    language: Mapped[str] = mapped_column(String(10), default="auto")  # auto | en-IN | hi-IN | te-IN
    voice_name: Mapped[str | None] = mapped_column(String(120))
    wake_phrase: Mapped[str | None] = mapped_column(String(60))
    response_length: Mapped[str] = mapped_column(String(10), default="short")
