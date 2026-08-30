"""initial schema

Revision ID: 5bde7f9f6089
Revises:
Create Date: 2026-08-30 16:05:47.646739

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5bde7f9f6089'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column(
            "payment_id",
            sa.String(),
            nullable=False
        ),
        sa.Column(
            "product_id",
            sa.String(),
            nullable=False
        ),
        sa.Column(
            "amount",
            sa.Integer(),
            nullable=False
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False
        ),
        sa.Column(
            "idempotency_key",
            sa.String(),
            nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False
        ),
        sa.PrimaryKeyConstraint(
            "payment_id"
        ),
        sa.UniqueConstraint(
            "idempotency_key"
        ),
    )

    op.create_table(
        "webhook_events",
        sa.Column(
            "event_id",
            sa.String(),
            nullable=False
        ),
        sa.Column(
            "payment_id",
            sa.String(),
            nullable=False
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False
        ),
        sa.Column(
            "processed",
            sa.Boolean(),
            nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False
        ),
        sa.PrimaryKeyConstraint(
            "event_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("webhook_events")
    op.drop_table("payments")
