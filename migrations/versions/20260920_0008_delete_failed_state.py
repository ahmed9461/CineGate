"""Allow durable permanent deletion failure state.

Revision ID: 20260920_0008
Revises: 20260920_0007
Create Date: 2026-09-20
"""

from alembic import op

revision = "20260920_0008"
down_revision = "20260920_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_deliveries_status",
        "deliveries",
        type_="check",
    )
    op.create_check_constraint(
        "ck_deliveries_status",
        "deliveries",
        "status IN ("
        "'pending', 'sending', 'sent', 'deleting', 'deleted', 'delete_failed'"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_deliveries_status",
        "deliveries",
        type_="check",
    )
    op.create_check_constraint(
        "ck_deliveries_status",
        "deliveries",
        "status IN ('pending', 'sending', 'sent', 'deleting', 'deleted')",
    )
