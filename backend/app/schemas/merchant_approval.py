from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas.buyer_agent import BuyerAgentEvaluationResult


ApprovalStatus = Literal["PENDING", "APPROVED", "REJECTED", "EXPIRED"]
ApprovalDecision = Literal["APPROVE", "REJECT"]


class MerchantApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str
    intent_id: str
    merchant_id: str
    product_id: str
    amount: int = Field(gt=0)
    status: ApprovalStatus
    requested_reason_code: str
    requested_message: str
    reviewer_merchant_id: str | None = None
    decision_reason: str | None = None
    expires_at: datetime
    created_at: datetime
    decided_at: datetime | None = None


class MerchantApprovalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ApprovalDecision
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_rejection_reason(self):
        if self.decision == "REJECT" and not (self.reason or "").strip():
            raise ValueError("A reason is required when rejecting an approval.")
        if self.reason is not None:
            self.reason = self.reason.strip() or None
        return self


class MerchantApprovalListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str
    approvals: list[MerchantApproval] = Field(default_factory=list)


class MerchantApprovalDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval: MerchantApproval
    evaluation: BuyerAgentEvaluationResult
    next_action: str
    ready_for_payment: bool
    razorpay_test_request: dict[str, Any] | None = None
