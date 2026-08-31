"""add payment provider metadata

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-08-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column(
            "provider",
            sa.String(),
            server_default="INTERNAL_LEDGER",
            nullable=False,
        ),
    )
    op.add_column(
        "payments",
        sa.Column("provider_order_id", sa.String(), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("provider_payment_id", sa.String(), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("provider_status", sa.String(), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column(
            "currency",
            sa.String(),
            server_default="INR",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_payments_provider_order_id",
        "payments",
        ["provider_order_id"],
        unique=True,
    )
    op.create_index(
        "ix_payments_provider_payment_id",
        "payments",
        ["provider_payment_id"],
        unique=True,
    )
    op.add_column(
        "webhook_events",
        sa.Column(
            "provider",
            sa.String(),
            server_default="INTERNAL_LEDGER",
            nullable=False,
        ),
    )
    op.add_column(
        "webhook_events",
        sa.Column("signature_verified", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("webhook_events", "signature_verified")
    op.drop_column("webhook_events", "provider")
    op.drop_index(
        "ix_payments_provider_payment_id",
        table_name="payments",
    )
    op.drop_index(
        "ix_payments_provider_order_id",
        table_name="payments",
    )
    op.drop_column("payments", "currency")
    op.drop_column("payments", "provider_status")
    op.drop_column("payments", "provider_payment_id")
    op.drop_column("payments", "provider_order_id")
    op.drop_column("payments", "provider")
