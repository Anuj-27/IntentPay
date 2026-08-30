"""persist intent mandates and bind payments to intents

Revision ID: c1d2e3f4a5b6
Revises: a58603001e60
Create Date: 2026-08-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "a58603001e60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "intents",
        sa.Column("intent_id", sa.String(), nullable=False),
        sa.Column("mandate", sa.JSON(), nullable=False),
        sa.Column("selected_product_id", sa.String(), nullable=True),
        sa.Column("selection_confirmed", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("intent_id"),
    )

    op.add_column(
        "payments",
        sa.Column("intent_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_payments_intent_id",
        "payments",
        ["intent_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_payments_intent_id_intents",
        "payments",
        "intents",
        ["intent_id"],
        ["intent_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_payments_intent_id_intents",
        "payments",
        type_="foreignkey",
    )
    op.drop_index("ix_payments_intent_id", table_name="payments")
    op.drop_column("payments", "intent_id")
    op.drop_table("intents")
