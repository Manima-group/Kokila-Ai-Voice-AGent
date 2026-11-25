"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-25 16:19:56.724274
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("create extension if not exists vector")
    op.create_table(
        "capability_catalog",
        sa.Column("key", sa.String(length=96), nullable=False),
        sa.Column("requirement_id", sa.String(length=40), nullable=False),
        sa.Column("module", sa.String(length=40), nullable=False),
        sa.Column("product", sa.String(length=24), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quota_metric", sa.String(length=64), nullable=True),
        sa.Column("purchasable", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_capability_catalog")),
    )
    op.create_table(
        "organizations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("policy_revision", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status in ('active','suspended')", name=op.f("ck_organizations_status")),
        sa.CheckConstraint("type in ('personal','business')", name=op.f("ck_organizations_type")),
        sa.CheckConstraint("policy_revision > 0", name=op.f("ck_organizations_policy_revision_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
    )
    op.create_table(
        "plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("product", sa.String(length=24), nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("limits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("price_minor >= 0", name=op.f("ck_plans_price_nonneg")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
        sa.UniqueConstraint("code", "version", name="uq_plans_code_version"),
    )
    op.create_table(
        "platform_audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_tenant_id", sa.UUID(), nullable=True),
        sa.Column("target_ref", sa.String(length=160), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_audit_events")),
    )
    op.create_index("ix_platform_audit_created", "platform_audit_events", ["created_at"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("platform_role", sa.String(length=32), nullable=True),
        sa.Column("mfa_secret_enc", sa.Text(), nullable=True),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status in ('active','disabled')", name=op.f("ck_users_status")),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_normalized")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "webhook_receipts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=160), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_receipts")),
        sa.UniqueConstraint("provider", "event_id", name="uq_webhook_receipts_provider_event"),
    )
    op.create_table(
        "assistant_identity_preferences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.String(length=8), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("display_name", sa.String(length=40), nullable=False),
        sa.Column("spoken_name", sa.String(length=60), nullable=False),
        sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("pronunciation_hint", sa.String(length=120), nullable=True),
        sa.Column("wake_phrase", sa.String(length=60), nullable=True),
        sa.Column("wake_status", sa.String(length=16), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("voice_profile_id", sa.String(length=64), nullable=True),
        sa.Column("response_length", sa.String(length=8), nullable=False),
        sa.Column("speaking_rate", sa.Float(), nullable=False),
        sa.Column("allow_personal_override", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(scope = 'tenant' and user_id is null and agent_id is null) or (scope = 'user' and user_id is not null and agent_id is null) or (scope = 'agent' and agent_id is not null and user_id is null)",
            name=op.f("ck_assistant_identity_preferences_one_target"),
        ),
        sa.CheckConstraint(
            "response_length in ('short','medium','long')",
            name=op.f("ck_assistant_identity_preferences_response_length"),
        ),
        sa.CheckConstraint("scope in ('tenant','user','agent')", name=op.f("ck_assistant_identity_preferences_scope")),
        sa.CheckConstraint(
            "wake_status in ('disabled','pending','validated','unsupported')",
            name=op.f("ck_assistant_identity_preferences_wake_status"),
        ),
        sa.CheckConstraint(
            "char_length(display_name) between 1 and 40",
            name=op.f("ck_assistant_identity_preferences_display_name_len"),
        ),
        sa.CheckConstraint(
            "speaking_rate >= 0.5 and speaking_rate <= 2.0",
            name=op.f("ck_assistant_identity_preferences_speaking_rate"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_assistant_identity_preferences_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("fk_assistant_identity_preferences_updated_by")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_assistant_identity_preferences_user_id")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_identity_preferences")),
    )
    op.create_index(
        "uq_identity_agent",
        "assistant_identity_preferences",
        ["tenant_id", "agent_id"],
        unique=True,
        postgresql_where=sa.text("scope = 'agent'"),
    )
    op.create_index(
        "uq_identity_tenant_scope",
        "assistant_identity_preferences",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("scope = 'tenant'"),
    )
    op.create_index(
        "uq_identity_user",
        "assistant_identity_preferences",
        ["tenant_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("scope = 'user'"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_ref", sa.String(length=160), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name=op.f("fk_audit_events_tenant_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index("ix_audit_events_tenant_created", "audit_events", ["tenant_id", "created_at"], unique=False)
    op.create_table(
        "capability_dependencies",
        sa.Column("capability_key", sa.String(length=96), nullable=False),
        sa.Column("depends_on", sa.String(length=96), nullable=False),
        sa.CheckConstraint("capability_key <> depends_on", name=op.f("ck_capability_dependencies_no_self_edge")),
        sa.ForeignKeyConstraint(
            ["capability_key"],
            ["capability_catalog.key"],
            name=op.f("fk_capability_dependencies_capability_key"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["depends_on"],
            ["capability_catalog.key"],
            name=op.f("fk_capability_dependencies_depends_on"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("capability_key", "depends_on", name=op.f("pk_capability_dependencies")),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("next_sequence", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "channel in ('web_voice','web_text','embed','telephony')", name=op.f("ck_conversations_channel")
        ),
        sa.CheckConstraint("status in ('active','archived')", name=op.f("ck_conversations_status")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name=op.f("fk_conversations_tenant_id"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_conversations_user_id")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_conversations_tenant_id_id"),
    )
    op.create_index(
        "ix_conversations_tenant_user_updated", "conversations", ["tenant_id", "user_id", "updated_at"], unique=False
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role in ('owner','admin','staff','member')", name=op.f("ck_memberships_role")),
        sa.CheckConstraint("status in ('active','invited','suspended')", name=op.f("ck_memberships_status")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name=op.f("fk_memberships_tenant_id"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_memberships_user_id"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memberships")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_memberships_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
    )
    op.create_index("ix_memberships_user", "memberships", ["user_id"], unique=False)
    op.create_table(
        "memory_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_message_id", sa.UUID(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(), nullable=True),
        sa.Column("embedding_model", sa.String(length=96), nullable=True),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("(scope = 'personal') = (user_id is not null)", name=op.f("ck_memory_items_scope_owner")),
        sa.CheckConstraint("kind in ('semantic','episodic','procedural')", name=op.f("ck_memory_items_kind")),
        sa.CheckConstraint("scope in ('personal','organization')", name=op.f("ck_memory_items_scope")),
        sa.CheckConstraint("confidence >= 0 and confidence <= 1", name=op.f("ck_memory_items_confidence_range")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name=op.f("fk_memory_items_tenant_id"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_memory_items_user_id")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_items")),
    )
    op.create_index(
        "ix_memory_items_fts",
        "memory_items",
        [sa.literal_column("to_tsvector('simple', content)")],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index("ix_memory_items_tenant_user", "memory_items", ["tenant_id", "user_id", "updated_at"], unique=False)
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status in ('pending','dispatched','failed')", name=op.f("ck_outbox_events_status")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name=op.f("fk_outbox_events_tenant_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
    )
    op.create_index(
        "ix_outbox_due",
        "outbox_events",
        ["status", "next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "plan_capabilities",
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("capability_key", sa.String(length=96), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("limits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["capability_key"], ["capability_catalog.key"], name=op.f("fk_plan_capabilities_capability_key")
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name=op.f("fk_plan_capabilities_plan_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("plan_id", "capability_key", name=op.f("pk_plan_capabilities")),
    )
    op.create_table(
        "platform_capability_controls",
        sa.Column("capability_key", sa.String(length=96), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["capability_key"], ["capability_catalog.key"], name=op.f("fk_platform_capability_controls_capability_key")
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name=op.f("fk_platform_capability_controls_updated_by")),
        sa.PrimaryKeyConstraint("capability_key", name=op.f("pk_platform_capability_controls")),
    )
    op.create_table(
        "policy_revisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("changed_by", sa.UUID(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], name=op.f("fk_policy_revisions_changed_by")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name=op.f("fk_policy_revisions_tenant_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_revisions")),
        sa.UniqueConstraint("tenant_id", "revision", name="uq_policy_revisions_tenant_revision"),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mfa", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_refresh_tokens_user_id"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index("ix_refresh_tokens_family", "refresh_tokens", ["family_id"], unique=False)
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=True),
        sa.Column("provider_ref", sa.String(length=128), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status in ('trialing','active','past_due','cancelled')", name=op.f("ck_subscriptions_status")
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], name=op.f("fk_subscriptions_plan_id")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name=op.f("fk_subscriptions_tenant_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
    )
    op.create_index(
        "uq_subscriptions_one_active",
        "subscriptions",
        ["tenant_id"],
        unique=True,
        postgresql_where="status in ('trialing','active','past_due')",
    )
    op.create_table(
        "tenant_capability_overrides",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("capability_key", sa.String(length=96), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("limits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("revision > 0", name=op.f("ck_tenant_capability_overrides_revision_positive")),
        sa.ForeignKeyConstraint(
            ["capability_key"], ["capability_catalog.key"], name=op.f("fk_tenant_capability_overrides_capability_key")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_tenant_capability_overrides_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name=op.f("fk_tenant_capability_overrides_updated_by")),
        sa.PrimaryKeyConstraint("tenant_id", "capability_key", name=op.f("pk_tenant_capability_overrides")),
    )
    op.create_table(
        "tool_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("tool_key", sa.String(length=96), nullable=False),
        sa.Column("tool_version", sa.BigInteger(), nullable=False),
        sa.Column("capability_key", sa.String(length=96), nullable=False),
        sa.Column("side_effect", sa.String(length=16), nullable=False),
        sa.Column("args", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("args_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("policy_revision", sa.BigInteger(), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status in ('requested','validating','awaiting_approval','queued','running','succeeded','failed','cancelled','unknown_outcome')",
            name=op.f("ck_tool_runs_status"),
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name=op.f("fk_tool_runs_requested_by")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name=op.f("fk_tool_runs_tenant_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_runs")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tool_runs_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tool_runs_tenant_idempotency"),
    )
    op.create_index(
        "ix_tool_runs_tenant_status_created", "tool_runs", ["tenant_id", "status", "created_at"], unique=False
    )
    op.create_table(
        "usage_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("source_event_id", sa.String(length=128), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("cost_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("quantity >= 0 and cost_minor >= 0", name=op.f("ck_usage_events_nonneg")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name=op.f("fk_usage_events_tenant_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_events")),
        sa.UniqueConstraint("tenant_id", "metric", "source_event_id", name="uq_usage_events_tenant_metric_source"),
    )
    op.create_index("ix_usage_tenant_metric_time", "usage_events", ["tenant_id", "metric", "occurred_at"], unique=False)
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column("approver_id", sa.UUID(), nullable=True),
        sa.Column("args_hash", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "decision in ('pending','approved','denied','expired')", name=op.f("ck_approval_requests_decision")
        ),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], name=op.f("fk_approval_requests_approver_id")),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name=op.f("fk_approval_requests_requested_by")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["tool_runs.tenant_id", "tool_runs.id"],
            name=op.f("fk_approval_requests_tenant_id_run_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name=op.f("fk_approval_requests_tenant_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_requests")),
        sa.UniqueConstraint("run_id", name="uq_approval_requests_one_per_run"),
    )
    op.create_table(
        "assistant_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("mic_muted", sa.Boolean(), nullable=False),
        sa.Column("speaker_muted", sa.Boolean(), nullable=False),
        sa.Column("policy_revision", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "state in ('idle','listening','thinking','speaking','awaiting_approval','reconnecting','ended')",
            name=op.f("ck_assistant_sessions_state"),
        ),
        sa.CheckConstraint(
            "generation >= 0 and last_sequence >= 0", name=op.f("ck_assistant_sessions_counters_nonneg")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            name=op.f("fk_assistant_sessions_tenant_id_conversation_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name=op.f("fk_assistant_sessions_tenant_id"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_assistant_sessions_user_id")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_sessions")),
    )
    op.create_index(
        "ix_assistant_sessions_tenant_user", "assistant_sessions", ["tenant_id", "user_id", "created_at"], unique=False
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=False),
        sa.Column("client_turn_id", sa.String(length=64), nullable=True),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("played_chars", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=96), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role in ('user','assistant','tool','system')", name=op.f("ck_messages_role")),
        sa.CheckConstraint("status in ('final','interrupted','failed')", name=op.f("ck_messages_status")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            name=op.f("fk_messages_tenant_id_conversation_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name=op.f("fk_messages_tenant_id"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_messages_user_id")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint("conversation_id", "sequence", name="uq_messages_conversation_sequence"),
        sa.UniqueConstraint("tenant_id", "conversation_id", "client_turn_id", name="uq_messages_client_turn"),
    )
    op.create_index("ix_messages_conversation_sequence", "messages", ["conversation_id", "sequence"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_messages_conversation_sequence", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_assistant_sessions_tenant_user", table_name="assistant_sessions")
    op.drop_table("assistant_sessions")
    op.drop_table("approval_requests")
    op.drop_index("ix_usage_tenant_metric_time", table_name="usage_events")
    op.drop_table("usage_events")
    op.drop_index("ix_tool_runs_tenant_status_created", table_name="tool_runs")
    op.drop_table("tool_runs")
    op.drop_table("tenant_capability_overrides")
    op.drop_index(
        "uq_subscriptions_one_active",
        table_name="subscriptions",
        postgresql_where="status in ('trialing','active','past_due')",
    )
    op.drop_table("subscriptions")
    op.drop_index("ix_refresh_tokens_family", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("policy_revisions")
    op.drop_table("platform_capability_controls")
    op.drop_table("plan_capabilities")
    op.drop_index("ix_outbox_due", table_name="outbox_events", postgresql_where=sa.text("status = 'pending'"))
    op.drop_table("outbox_events")
    op.drop_index("ix_memory_items_tenant_user", table_name="memory_items")
    op.drop_index("ix_memory_items_fts", table_name="memory_items", postgresql_using="gin")
    op.drop_table("memory_items")
    op.drop_index("ix_memberships_user", table_name="memberships")
    op.drop_table("memberships")
    op.drop_index("ix_conversations_tenant_user_updated", table_name="conversations")
    op.drop_table("conversations")
    op.drop_table("capability_dependencies")
    op.drop_index("ix_audit_events_tenant_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index(
        "uq_identity_user", table_name="assistant_identity_preferences", postgresql_where=sa.text("scope = 'user'")
    )
    op.drop_index(
        "uq_identity_tenant_scope",
        table_name="assistant_identity_preferences",
        postgresql_where=sa.text("scope = 'tenant'"),
    )
    op.drop_index(
        "uq_identity_agent", table_name="assistant_identity_preferences", postgresql_where=sa.text("scope = 'agent'")
    )
    op.drop_table("assistant_identity_preferences")
    op.drop_table("webhook_receipts")
    op.drop_table("users")
    op.drop_index("ix_platform_audit_created", table_name="platform_audit_events")
    op.drop_table("platform_audit_events")
    op.drop_table("plans")
    op.drop_table("organizations")
    op.drop_table("capability_catalog")
