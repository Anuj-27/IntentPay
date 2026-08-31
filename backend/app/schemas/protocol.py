from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas.payment import PaymentStatus
from backend.app.schemas.purchase import ProposedPurchase


PROTOCOL_VERSION = "1.0"


class CommerceArtifactType(str, Enum):
    INTENT_MANDATE = "INTENT_MANDATE"
    MERCHANT_CONTRACT = "MERCHANT_CONTRACT"
    PROPOSED_PURCHASE = "PROPOSED_PURCHASE"
    TRUST_DECISION = "TRUST_DECISION"
    PAYMENT_COMMAND = "PAYMENT_COMMAND"
    PROVIDER_RESULT = "PROVIDER_RESULT"
    WEBHOOK_EVENT = "WEBHOOK_EVENT"


class ExternalProtocolName(str, Enum):
    UCP = "UCP"
    AP2 = "AP2"
    ACP = "ACP"
    X402 = "X402"


class ExternalProtocolStatus(str, Enum):
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class ExternalProtocolDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol: ExternalProtocolName
    status: ExternalProtocolStatus
    inspiration: list[str] = Field(default_factory=list)
    disclaimer: str = Field(min_length=1)


class ProtocolManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: Literal["IntentPay"] = "IntentPay"
    internal_protocol: Literal[
        "INTENTPAY_COMMERCE_BOUNDARY"
    ] = "INTENTPAY_COMMERCE_BOUNDARY"
    protocol_version: Literal["1.0"] = PROTOCOL_VERSION
    supported_artifacts: list[CommerceArtifactType]
    supported_payment_providers: list[str]
    external_protocols: list[ExternalProtocolDeclaration]
    disclaimer: str = Field(min_length=1)


class CommerceContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["1.0"] = PROTOCOL_VERSION
    correlation_id: UUID
    intent_id: str = Field(min_length=1, max_length=128)
    merchant_id: str = Field(min_length=1, max_length=128)


class PaymentProvider(str, Enum):
    INTERNAL_LEDGER = "INTERNAL_LEDGER"
    RAZORPAY_TEST = "RAZORPAY_TEST"


class ProviderPaymentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: CommerceContext
    provider: PaymentProvider = PaymentProvider.INTERNAL_LEDGER
    idempotency_key: str = Field(min_length=8, max_length=128)
    currency: Literal["INR"] = "INR"
    authorized_amount: int = Field(gt=0)
    purchase: ProposedPurchase

    @model_validator(mode="after")
    def validate_authorized_amount(self):
        if self.authorized_amount != self.purchase.total_amount:
            raise ValueError(
                "Provider command amount must match the purchase total."
            )

        return self


class ProviderPaymentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: CommerceContext
    provider: PaymentProvider
    provider_reference: str = Field(min_length=1, max_length=256)
    product_id: str = Field(min_length=1, max_length=128)
    currency: Literal["INR"] = "INR"
    amount: int = Field(gt=0)
    status: PaymentStatus


class ProtocolViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1)


class ProviderResultVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: bool
    violations: list[ProtocolViolation] = Field(default_factory=list)


class PaymentExecutionBoundaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_created: bool
    protocol_context: CommerceContext
    final_decision: dict
    message: str | None = None
    payment_command: ProviderPaymentCommand | None = None
    provider_result: ProviderPaymentResult | None = None
    provider_verification: ProviderResultVerification | None = None
    payment_result: dict | None = None
