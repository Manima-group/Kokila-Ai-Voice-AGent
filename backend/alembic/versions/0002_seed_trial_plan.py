"""seed trial plan

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Free trial: inbound + testing only. Paid plans are created by the Super Admin (pricing is configurable).
    op.execute(
        "INSERT INTO plans (id, code, name, price_minor, currency, interval_months, included_minutes, "
        "overage_per_minute_minor, max_agents, max_concurrent_calls, max_users, features, is_active, is_public, "
        "created_at, updated_at) VALUES "
        "(gen_random_uuid(), 'trial', 'Free Trial', 0, 'INR', 1, 30, NULL, 1, 1, 3, "
        '\'{"outbound": false, "calendar": true, "integrations": true}\', true, false, now(), now()) '
        "ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM plans WHERE code = 'trial'")
