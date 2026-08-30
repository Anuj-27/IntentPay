from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.purchase import ProposedPurchase


class PaymentStatus(str, Enum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class PaymentRecord(BaseModel):
    payment_id: str
    product_id: str
    amount: int = Field(gt=0)
    status: PaymentStatus = PaymentStatus.CREATED
    idempotency_key: str


class PaymentExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_id: str = Field(min_length=1, max_length=128)
    purchase: ProposedPurchase
    idempotency_key: str = Field(
        min_length=8,
        max_length=128
    )


class PaymentStatusUpdateRequest(BaseModel):
    new_status: PaymentStatus


class PaymentReconciliationRequest(BaseModel):
    resolved_status: PaymentStatus

class PaymentWebhookRequest(BaseModel):
    event_id: str = Field(min_length=1)
    payment_id: str
    status: PaymentStatus
