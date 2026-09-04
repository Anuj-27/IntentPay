from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    Boolean,
    Text,
    JSON,
    ForeignKey,
    Index,
    func,
    text,
)

from backend.app.db.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class IntentDB(Base):
    __tablename__ = "intents"

    intent_id = Column(String, primary_key=True)
    correlation_id = Column(String, unique=True, nullable=False)
    protocol_version = Column(String, default="1.0", nullable=False)
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

    provider = Column(
        String,
        default="INTERNAL_LEDGER",
        nullable=False,
    )

    provider_order_id = Column(
        String,
        unique=True,
        nullable=True,
        index=True,
    )

    provider_payment_id = Column(
        String,
        unique=True,
        nullable=True,
        index=True,
    )

    provider_status = Column(
        String,
        nullable=True,
    )

    currency = Column(
        String,
        default="INR",
        nullable=False,
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

    provider = Column(
        String,
        default="INTERNAL_LEDGER",
        nullable=False,
    )

    signature_verified = Column(
        Boolean,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        default=utc_now,
        nullable=False
    )


class MerchantCredentialDB(Base):
    __tablename__ = "merchant_credentials"

    merchant_id = Column(String, primary_key=True)
    password_hash = Column(String, nullable=False)
    password_salt = Column(String, nullable=False)
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


class MerchantPasswordResetDB(Base):
    """A one-time password-reset token for a merchant. IntentPay has no
    email/SMS transport configured (Test Mode, like the rest of the
    project), so the raw token is handed back to the caller directly
    instead of being emailed -- only its hash is ever persisted."""

    __tablename__ = "merchant_password_resets"

    token_hash = Column(String, primary_key=True)
    merchant_id = Column(String, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class MerchantProfileDB(Base):
    """A merchant registered through self-signup, distinct from the three
    built-in static demo merchants. See merchant_service.find_merchant_contract."""

    __tablename__ = "merchant_profiles"

    merchant_id = Column(String, primary_key=True)
    display_name = Column(String, nullable=False)
    currency = Column(String, default="INR", nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    catalog_search = Column(Boolean, default=True, nullable=False)
    inventory_check = Column(Boolean, default=True, nullable=False)
    checkout = Column(Boolean, default=True, nullable=False)
    refunds = Column(Boolean, default=True, nullable=False)
    max_transaction_amount = Column(Integer, nullable=True)
    human_approval_threshold = Column(Integer, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ProductOverrideDB(Base):
    __tablename__ = "merchant_product_overrides"

    merchant_id = Column(String, primary_key=True)
    product_id = Column(String, primary_key=True)

    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    price = Column(Integer, nullable=False)
    brand = Column(String, nullable=False)
    color = Column(String, nullable=True)
    model = Column(String, nullable=True)
    variant = Column(String, nullable=True)
    currency = Column(String, default="INR", nullable=False)
    image_url = Column(String, nullable=True)
    images = Column(JSON, nullable=False, default=list)
    product_url = Column(String, nullable=True)
    rating = Column(Float, default=0, nullable=False)
    features = Column(JSON, nullable=False, default=list)
    attributes = Column(JSON, nullable=False, default=dict)
    in_stock = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

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


class MerchantApprovalDB(Base):
    """A merchant decision for one exact, escalated purchase proposal.

    Approval is deliberately bound to the intent, product, and verified
    amount.  It cannot be reused for a different product, quantity, budget,
    or merchant policy evaluation.
    """

    __tablename__ = "merchant_approvals"

    approval_id = Column(String, primary_key=True)
    intent_id = Column(
        String,
        ForeignKey("intents.intent_id"),
        nullable=False,
        index=True,
    )
    merchant_id = Column(String, nullable=False, index=True)
    product_id = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)
    status = Column(String, default="PENDING", nullable=False, index=True)
    requested_reason_code = Column(String, nullable=False)
    requested_message = Column(Text, nullable=False)
    reviewer_merchant_id = Column(String, nullable=True)
    decision_reason = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    decided_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # The real concurrency guard: the database itself refuses a
        # second PENDING row for the same (intent, product, amount)
        # rather than relying on an application-level check-then-insert,
        # which has a race window under concurrent requests. Mirrored in
        # alembic/versions/e6f7a8b9c0d1_merchant_approval_concurrency_guard.py
        # for real deployments; declared here too so the same guard
        # exists in the SQLite schema pytest builds from this model.
        Index(
            "ux_merchant_approvals_active_request",
            "intent_id",
            "product_id",
            "amount",
            unique=True,
            sqlite_where=text("status = 'PENDING'"),
            postgresql_where=text("status = 'PENDING'"),
        ),
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
