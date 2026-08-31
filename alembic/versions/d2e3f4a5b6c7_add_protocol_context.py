"""add protocol context to persisted intents

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-08-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "intents",
        sa.Column("correlation_id", sa.String(), nullable=True),
    )
    op.add_column(
        "intents",
        sa.Column(
            "protocol_version",
            sa.String(),
            server_default="1.0",
            nullable=False,
        ),
    )

    op.execute(
        "UPDATE intents "
        "SET correlation_id = intent_id "
        "WHERE correlation_id IS NULL"
    )

    op.alter_column(
        "intents",
        "correlation_id",
        existing_type=sa.String(),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_intents_correlation_id",
        "intents",
        ["correlation_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_intents_correlation_id",
        "intents",
        type_="unique",
    )
    op.drop_column("intents", "protocol_version")
    op.drop_column("intents", "correlation_id")
