"""add merchant approval workflow

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-09-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "merchant_approvals",
        sa.Column("approval_id", sa.String(), nullable=False),
        sa.Column("intent_id", sa.String(), nullable=False),
        sa.Column("merchant_id", sa.String(), nullable=False),
        sa.Column("product_id", sa.String(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("requested_reason_code", sa.String(), nullable=False),
        sa.Column("requested_message", sa.Text(), nullable=False),
        sa.Column("reviewer_merchant_id", sa.String(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["intent_id"],
            ["intents.intent_id"],
        ),
        sa.PrimaryKeyConstraint("approval_id"),
    )
    op.create_index(
        "ix_merchant_approvals_intent_id",
        "merchant_approvals",
        ["intent_id"],
    )
    op.create_index(
        "ix_merchant_approvals_merchant_id",
        "merchant_approvals",
        ["merchant_id"],
    )
    op.create_index(
        "ix_merchant_approvals_status",
        "merchant_approvals",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_merchant_approvals_status",
        table_name="merchant_approvals",
    )
    op.drop_index(
        "ix_merchant_approvals_merchant_id",
        table_name="merchant_approvals",
    )
    op.drop_index(
        "ix_merchant_approvals_intent_id",
        table_name="merchant_approvals",
    )
    op.drop_table("merchant_approvals")
