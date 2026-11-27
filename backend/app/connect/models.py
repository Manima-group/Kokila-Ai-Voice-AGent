import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin


class ConnectorConnection(IdMixin, TimestampMixin, TenantMixin, Base):
    """A tenant's connection to a business system. `status` is 'connected' ONLY after a successful live verification."""

    __tablename__ = "connector_connections"
    __table_args__ = (UniqueConstraint("tenant_id", "connector_key", "name"),)
    connector_key: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str | None] = mapped_column(Text)
    encrypted_credentials: Mapped[str | None] = mapped_column(Text)
    scopes: Mapped[list] = mapped_column(JSONB, default=list)
    read_only: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | connected | failed | revoked
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    verified_identity: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
