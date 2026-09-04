"""add priority to merchant approvals

Revision ID: 7d6e5f4a3b2c
Revises: 9c8d7e6f5a4b
Create Date: 2026-09-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7d6e5f4a3b2c"
down_revision: Union[str, Sequence[str], None] = "9c8d7e6f5a4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # "HIGH" when the escalated amount is more than double the merchant's
    # autonomous_transaction_limit at request time, else "NORMAL" -- lets
    # a merchant triage a large review queue. See merchant_approval_
    # service.create_merchant_approval_request and its call site in
    # main.py's request_merchant_approval.
    op.add_column(
        "merchant_approvals",
        sa.Column(
            "priority",
            sa.String(),
            server_default="NORMAL",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("merchant_approvals", "priority")
