"""Add manager and viewer tenant roles for the Calling Agent product.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "role in ('owner','admin','staff','member')"
NEW = "role in ('owner','admin','manager','staff','member','viewer')"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_memberships_role"), "memberships", type_="check")
    op.create_check_constraint(op.f("ck_memberships_role"), "memberships", NEW)


def downgrade() -> None:
    # Refuses (constraint violation) while manager/viewer memberships exist, so no role is silently rewritten.
    op.drop_constraint(op.f("ck_memberships_role"), "memberships", type_="check")
    op.create_check_constraint(op.f("ck_memberships_role"), "memberships", OLD)
