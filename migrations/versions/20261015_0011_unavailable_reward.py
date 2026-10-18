"""Preserve unavailable earned rewards outside the active advertising slot.

Revision ID: 20261015_0011
Revises: 20260920_0010
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision = "20261015_0011"
down_revision = "20260920_0010"
branch_labels = None
depends_on = None

_OLD_STATUSES = (
    "'pending', 'client_completed', 'provider_confirmed', "
    "'rewarded', 'delivering', 'delivered', 'expired'"
)
_ACTIVE = (
    "status IN ('pending', 'client_completed', 'provider_confirmed', "
    "'rewarded', 'delivering')"
)


def upgrade() -> None:
    op.add_column(
        "reward_sessions", sa.Column("unavailable_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "reward_sessions", sa.Column("unavailable_reason", sa.String(length=64)),
    )
    op.drop_constraint("ck_reward_sessions_status", "reward_sessions", type_="check")
    op.create_check_constraint(
        "ck_reward_sessions_status", "reward_sessions",
        f"status IN ({_OLD_STATUSES}, 'unavailable')",
    )
    op.drop_index("uq_reward_sessions_active_user", table_name="reward_sessions")
    op.create_index(
        "uq_reward_sessions_active_user", "reward_sessions", ["telegram_user_id"],
        unique=True,
        postgresql_where=sa.text(f"{_ACTIVE} AND unavailable_at IS NULL"),
    )


def downgrade() -> None:
    # Older code cannot represent retained entitlements or their parallel resumes.
    # Refuse before changing anything; never expire credits to force an old index.
    op.execute("LOCK TABLE reward_sessions IN ACCESS EXCLUSIVE MODE")
    retained = op.get_bind().scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM reward_sessions "
        "WHERE status = 'unavailable' OR unavailable_at IS NOT NULL)"
    ))
    if retained:
        raise RuntimeError(
            "Cannot downgrade: retained unavailable reward history exists. "
            "Keep migration 20261015_0011 or restore a pre-upgrade backup; "
            "do not discard earned entitlements."
        )
    op.drop_index("uq_reward_sessions_active_user", table_name="reward_sessions")
    op.create_index(
        "uq_reward_sessions_active_user", "reward_sessions", ["telegram_user_id"],
        unique=True, postgresql_where=sa.text(_ACTIVE),
    )
    op.drop_constraint("ck_reward_sessions_status", "reward_sessions", type_="check")
    op.create_check_constraint(
        "ck_reward_sessions_status", "reward_sessions", f"status IN ({_OLD_STATUSES})",
    )
    op.drop_column("reward_sessions", "unavailable_reason")
    op.drop_column("reward_sessions", "unavailable_at")
