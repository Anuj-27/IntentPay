from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.protocol import (
    CommerceContext,
    ProviderPaymentCommand,
    ProviderPaymentResult,
    ProviderResultVerification,
)


class RazorpayConfigurationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["RAZORPAY_TEST"] = "RAZORPAY_TEST"
    configured: bool
    test_mode_only: bool = True
    key_id_hint: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    message: str


class RazorpayOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: int = Field(gt=0, description="Amount in paise.")
    currency: Literal["INR"] = "INR"
    receipt: str = Field(min_length=1, max_length=40)
    notes: dict[str, str] = Field(default_factory=dict)


class RazorpayOrderEntity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=128)
    entity: Literal["order"] = "order"
    amount: int = Field(gt=0)
    amount_paid: int = Field(ge=0)
    amount_due: int = Field(ge=0)
    currency: Literal["INR"] = "INR"
    receipt: str = Field(min_length=1, max_length=40)
    status: Literal["created", "attempted", "paid"]
    attempts: int = Field(default=0, ge=0)


class RazorpayProviderOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    REJECTED = "REJECTED"
    UNCERTAIN = "UNCERTAIN"


class RazorpayProviderCallResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: RazorpayProviderOutcome
    reason_code: str
    message: str
    order: RazorpayOrderEntity | None = None
    provider_http_status: int | None = None


class RazorpayOrderViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class RazorpayOrderVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: bool
    violations: list[RazorpayOrderViolation] = Field(default_factory=list)


class RazorpayCheckoutOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    amount: int = Field(gt=0, description="Amount in paise.")
    currency: Literal["INR"] = "INR"
    order_id: str
    name: str = "IntentPay Demo"
    description: str


class RazorpayPaymentExecutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_created: bool
    protocol_context: CommerceContext
    final_decision: dict[str, Any]
    reason_code: str
    message: str
    payment_command: ProviderPaymentCommand | None = None
    order_request: RazorpayOrderRequest | None = None
    provider_order: RazorpayOrderEntity | None = None
    provider_result: ProviderPaymentResult | None = None
    provider_verification: ProviderResultVerification | None = None
    order_verification: RazorpayOrderVerification | None = None
    checkout_options: RazorpayCheckoutOptions | None = None
    payment_result: dict[str, Any] | None = None


class RazorpayCheckoutVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    razorpay_order_id: str = Field(min_length=1, max_length=128)
    razorpay_payment_id: str = Field(min_length=1, max_length=128)
    razorpay_signature: str = Field(min_length=1, max_length=256)


class RazorpayCheckoutVerificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: bool
    reason_code: str
    message: str
    payment_id: str
    provider_order_id: str | None = None
    provider_payment_id: str | None = None
    awaiting_captured_webhook: bool = True


class RazorpayWebhookResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    processed: bool
    signature_verified: bool
    reason_code: str
    message: str
    event_id: str
    event_type: str | None = None
    payment_id: str | None = None
    payment: dict[str, Any] | None = None


class RazorpayReconciliationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    reason_code: str
    message: str
    payment: dict[str, Any] | None = None
    provider_order: RazorpayOrderEntity | None = None
    order_verification: RazorpayOrderVerification | None = None

