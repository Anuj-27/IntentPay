from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SafetyControlStatus(str, Enum):
    ENFORCED = "ENFORCED"
    LIMITATION = "LIMITATION"


class SafetyControl(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control_id: str = Field(min_length=1, max_length=128)
    status: SafetyControlStatus
    description: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)


class SafetyManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = "IntentPay"
    privacy_mode: str
    controls: list[SafetyControl]
    limitations: list[str] = Field(default_factory=list)


class RecommendationIntegrityViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1)


class RecommendationIntegrityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: bool
    reason_code: str
    cheapest_valid_product_id: str | None = None
    recommended_product_id: str | None = None
    recommended_price_premium: int | None = None
    violations: list[RecommendationIntegrityViolation] = Field(
        default_factory=list
    )

