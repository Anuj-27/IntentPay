"""add merchant self-registration

Revision ID: a1b2c3d4e5f6
Revises: f4a5b6c7d8e9
Create Date: 2026-09-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "merchant_profiles",
        sa.Column("merchant_id", sa.String(), primary_key=True),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column(
            "currency", sa.String(), server_default="INR", nullable=False
        ),
        sa.Column(
            "active", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
        sa.Column(
            "catalog_search",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "inventory_check",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "checkout", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
        sa.Column(
            "refunds", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
        sa.Column("max_transaction_amount", sa.Integer(), nullable=True),
        sa.Column("human_approval_threshold", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("merchant_profiles")
