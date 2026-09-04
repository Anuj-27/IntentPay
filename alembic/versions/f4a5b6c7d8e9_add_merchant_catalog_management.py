"""add merchant catalog management

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-09-02
"""

import hashlib
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Demo-only credential. Documented in README.md and meant to be rotated
# before any non-local deployment; IntentPay never uses these accounts
# to move real money regardless.
DEMO_PASSWORD = "IntentPayDemo!2026"
PBKDF2_ITERATIONS = 200_000
SEEDED_MERCHANT_IDS = ("MERCHANT-001", "MERCHANT-002", "MERCHANT-003")


def _hash_password(password: str) -> tuple[str, str]:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return digest.hex(), salt.hex()


def upgrade() -> None:
    op.create_table(
        "merchant_credentials",
        sa.Column("merchant_id", sa.String(), primary_key=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("password_salt", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "merchant_product_overrides",
        sa.Column("merchant_id", sa.String(), primary_key=True),
        sa.Column("product_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("brand", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("variant", sa.String(), nullable=True),
        sa.Column(
            "currency", sa.String(), server_default="INR", nullable=False
        ),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("product_url", sa.String(), nullable=True),
        sa.Column(
            "rating", sa.Float(), server_default="0", nullable=False
        ),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column(
            "in_stock", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    credentials_table = sa.table(
        "merchant_credentials",
        sa.column("merchant_id", sa.String),
        sa.column("password_hash", sa.String),
        sa.column("password_salt", sa.String),
    )
    op.bulk_insert(
        credentials_table,
        [
            {
                "merchant_id": merchant_id,
                "password_hash": password_hash,
                "password_salt": password_salt,
            }
            for merchant_id in SEEDED_MERCHANT_IDS
            for password_hash, password_salt in [_hash_password(DEMO_PASSWORD)]
        ],
    )


def downgrade() -> None:
    op.drop_table("merchant_product_overrides")
    op.drop_table("merchant_credentials")
