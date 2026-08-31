from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.decision import DecisionType
from backend.app.schemas.product import Product
from backend.app.schemas.purchase import ProposedPurchase


class RejectionReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1)


class RejectedProductResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: Product
    reasons: list[RejectionReason]


class RankedProductResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: Product
    score: float = Field(ge=0)
    matched_features: list[str] = Field(
        default_factory=list
    )

    score_breakdown: dict[str, int | float] = Field(
        default_factory=dict
    )

    explanation: dict[str, int | float] = Field(
        default_factory=dict
    )


class StretchCandidateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: Product
    decision: DecisionType

    over_budget_amount: int = Field(gt=0)
    over_budget_percent: float = Field(gt=0)
    proposed_total: int = Field(gt=0)

    compared_with: str = Field(min_length=1, max_length=128)
    rating_gain: float

    new_features: list[str] = Field(
        default_factory=list
    )

    message: str


class BuyerAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = Field(min_length=1, max_length=128)
    decision: DecisionType
    reason_code: str
    message: str

    recommended_product: Product | None = None
    selected_product: Product | None = None

    alternative_products: list[Product] = Field(
        default_factory=list
    )

    ranked_products: list[RankedProductResult] = Field(
        default_factory=list
    )

    rejected_products: list[RejectedProductResult] = Field(
        default_factory=list
    )

    stretch_candidates: list[StretchCandidateResult] = Field(
        default_factory=list
    )

    proposed_purchase: ProposedPurchase | None = None


class PurchaseVerificationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: bool

    catalog_unit_price: int | None = None
    expected_total: int | None = None

    violations: list[RejectionReason] = Field(
        default_factory=list
    )


class DecisionDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: DecisionType
    reason_code: str
    message: str

    violations: list[RejectionReason] = Field(
        default_factory=list
    )


class MerchantPolicyEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "NOT_EVALUATED",
        "REJECTED",
        "REVIEW_REQUIRED",
        "APPROVED",
    ]
    requires_human_approval: bool
    reason_code: str
    message: str

    threshold: int | None = None
    amount: int | None = None


class BuyerAgentEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    buyer_agent: BuyerAgentResult

    verification: PurchaseVerificationSummary | None = None
    intent_decision: DecisionDetails | None = None
    merchant_policy: MerchantPolicyEvaluation | None = None

    final_decision: DecisionDetails

    ready_for_payment: bool = False
