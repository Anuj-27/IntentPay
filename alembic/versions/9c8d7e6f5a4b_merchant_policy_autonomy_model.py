"""replace merchant human-approval threshold with an autonomy/scale model

Revision ID: 9c8d7e6f5a4b
Revises: e6f7a8b9c0d1
Create Date: 2026-09-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9c8d7e6f5a4b"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `human_approval_threshold` was the sole trigger for ESCALATE. It
    # becomes `autonomous_transaction_limit`: the ceiling of the
    # autonomous-execution envelope, not an always-escalate line -- see
    # merchant_policy_engine.evaluate_merchant_policy.
    op.alter_column(
        "merchant_profiles",
        "human_approval_threshold",
        new_column_name="autonomous_transaction_limit",
    )
    op.add_column(
        "merchant_profiles",
        sa.Column("daily_autonomous_amount_limit", sa.Integer(), nullable=True),
    )
    op.add_column(
        "merchant_profiles",
        sa.Column("daily_autonomous_transaction_limit", sa.Integer(), nullable=True),
    )
    op.add_column(
        "merchant_profiles",
        sa.Column("high_value_review_threshold", sa.Integer(), nullable=True),
    )
    op.add_column(
        "merchant_profiles",
        sa.Column(
            "require_human_review_for_policy_exceptions",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.add_column(
        "merchant_profiles",
        sa.Column(
            "require_human_review_for_high_risk",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )

    # Running total of what a merchant's policy has let the AI agent
    # execute autonomously today (UTC calendar day) -- see
    # merchant_usage_service.py. One row per (merchant, day), incremented
    # atomically exactly once per real autonomous order.
    op.create_table(
        "merchant_autonomous_usage",
        sa.Column("merchant_id", sa.String(), primary_key=True),
        sa.Column("usage_date", sa.Date(), primary_key=True),
        sa.Column("amount_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("transaction_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_table("merchant_autonomous_usage")
    op.drop_column("merchant_profiles", "require_human_review_for_high_risk")
    op.drop_column("merchant_profiles", "require_human_review_for_policy_exceptions")
    op.drop_column("merchant_profiles", "high_value_review_threshold")
    op.drop_column("merchant_profiles", "daily_autonomous_transaction_limit")
    op.drop_column("merchant_profiles", "daily_autonomous_amount_limit")
    op.alter_column(
        "merchant_profiles",
        "autonomous_transaction_limit",
        new_column_name="human_approval_threshold",
    )
