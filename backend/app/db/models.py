from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    Boolean,
    Text,
    JSON,
    ForeignKey,
    func,
)

from backend.app.db.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class IntentDB(Base):
    __tablename__ = "intents"

    intent_id = Column(String, primary_key=True)
    mandate = Column(JSON, nullable=False)
    selected_product_id = Column(String, nullable=True)
    selection_confirmed = Column(Boolean, default=False, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PaymentDB(Base):
    __tablename__ = "payments"

    payment_id = Column(
        String,
        primary_key=True
    )

    product_id = Column(
        String,
        nullable=False
    )

    intent_id = Column(
        String,
        ForeignKey("intents.intent_id"),
        nullable=True,
        index=True,
    )

    amount = Column(
        Integer,
        nullable=False
    )

    status = Column(
        String,
        nullable=False
    )

    idempotency_key = Column(
        String,
        unique=True,
        nullable=False
    )

    created_at = Column(
        DateTime,
        default=utc_now,
        nullable=False
    )

    updated_at = Column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False
    )


class WebhookEventDB(Base):
    __tablename__ = "webhook_events"

    event_id = Column(
        String,
        primary_key=True
    )

    payment_id = Column(
        String,
        nullable=False
    )

    status = Column(
        String,
        nullable=False
    )

    processed = Column(
        Boolean,
        default=True,
        nullable=False
    )

    created_at = Column(
        DateTime,
        default=utc_now,
        nullable=False
    )


class AuditLogDB(Base):
    __tablename__ = "audit_logs"

    audit_id = Column(
        String,
        primary_key=True
    )

    event_type = Column(
        String,
        nullable=False,
        index=True
    )

    component = Column(
        String,
        nullable=False
    )

    entity_type = Column(
        String,
        nullable=True
    )

    entity_id = Column(
        String,
        nullable=True,
        index=True
    )

    decision = Column(
        String,
        nullable=True
    )

    reason_code = Column(
        String,
        nullable=True
    )

    message = Column(
        Text,
        nullable=False
    )

    amount = Column(
        Integer,
        nullable=True
    )

    details = Column(
        JSON,
        nullable=True
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
