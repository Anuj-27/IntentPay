import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy import pool

from backend.app.db.database import Base

# IMPORTANT:
# Import all SQLAlchemy models so Alembic knows about them.
from backend.app.db.models import (
    IntentDB,
    PaymentDB,
    WebhookEventDB,
    AuditLogDB,
    MerchantCredentialDB,
    MerchantPasswordResetDB,
    MerchantProfileDB,
    ProductOverrideDB,
    MerchantApprovalDB,
)


load_dotenv()

config = context.config


if config.config_file_name is not None:
    fileConfig(config.config_file_name)


DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not configured in the .env file"
    )


target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations without creating
    a live database connection.
    """

    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={
            "paramstyle": "named"
        },
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations using a real
    PostgreSQL connection.
    """

    connectable = create_engine(
        DATABASE_URL,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
