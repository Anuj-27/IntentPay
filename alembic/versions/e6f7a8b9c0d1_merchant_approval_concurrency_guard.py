"""guard against duplicate concurrent merchant approvals

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-09-04
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX_NAME = "ux_merchant_approvals_active_request"


def upgrade() -> None:
    # A partial unique index is the actual concurrency guard: the
    # application already checks for an existing PENDING/APPROVED
    # approval before inserting a new one, but that check-then-insert has
    # a race window under concurrent requests. This makes the database
    # itself reject a second PENDING row for the same (intent, product,
    # amount) rather than relying on request timing.
    op.execute(
        f"""
        CREATE UNIQUE INDEX {INDEX_NAME}
        ON merchant_approvals (intent_id, product_id, amount)
        WHERE status = 'PENDING'
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX {INDEX_NAME}")
