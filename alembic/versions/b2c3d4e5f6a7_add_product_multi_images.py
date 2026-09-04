"""add multi-image support to merchant product overrides

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "merchant_product_overrides",
        sa.Column("images", sa.JSON(), nullable=True),
    )

    # Backfill: any row that already has a single `image_url` becomes a
    # one-item primary image list, so existing merchant-added products
    # keep their image after this migration instead of losing it until
    # the merchant re-saves the product.
    connection = op.get_bind()
    override_table = sa.table(
        "merchant_product_overrides",
        sa.column("merchant_id", sa.String()),
        sa.column("product_id", sa.String()),
        sa.column("image_url", sa.String()),
        sa.column("images", sa.JSON()),
    )
    rows = connection.execute(
        sa.select(
            override_table.c.merchant_id,
            override_table.c.product_id,
            override_table.c.image_url,
        )
    ).fetchall()
    for merchant_id, product_id, image_url in rows:
        images = [{"url": image_url, "is_primary": True}] if image_url else []
        connection.execute(
            override_table.update()
            .where(
                override_table.c.merchant_id == merchant_id,
                override_table.c.product_id == product_id,
            )
            .values(images=images)
        )

    with op.batch_alter_table("merchant_product_overrides") as batch_op:
        batch_op.alter_column(
            "images",
            existing_type=sa.JSON(),
            nullable=False,
            server_default="[]",
        )


def downgrade() -> None:
    op.drop_column("merchant_product_overrides", "images")
