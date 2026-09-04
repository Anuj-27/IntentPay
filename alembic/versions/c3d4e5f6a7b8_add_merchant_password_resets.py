"""add merchant password resets

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "merchant_password_resets",
        sa.Column("token_hash", sa.String(), primary_key=True),
        sa.Column("merchant_id", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "used", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_merchant_password_resets_merchant_id",
        "merchant_password_resets",
        ["merchant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_merchant_password_resets_merchant_id",
        table_name="merchant_password_resets",
    )
    op.drop_table("merchant_password_resets")
