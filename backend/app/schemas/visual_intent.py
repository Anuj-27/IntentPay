from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.schemas.product import Product


SupportedImageMediaType = Literal["image/jpeg", "image/png", "image/webp"]


class VisualIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_base64: str = Field(min_length=16, max_length=7_000_000)
    media_type: SupportedImageMediaType
    user_message: str | None = Field(default=None, max_length=1000)
    max_budget: int | None = Field(default=None, gt=0)
    quantity: int = Field(default=1, ge=1, le=100)
    merchant_id: str | None = Field(default=None, min_length=1, max_length=128)


class VisualProductCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    brand: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    variant: str | None = Field(default=None, max_length=100)
    displayed_price: int | None = Field(default=None, gt=0)
    currency: Literal["INR"] | None = None
    merchant_name: str | None = Field(default=None, max_length=200)
    merchant_domain: str | None = Field(default=None, max_length=253)
    visible_features: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0, le=1)
    extraction_method: Literal["OPENAI_VISION", "LOCAL_OCR"] = "OPENAI_VISION"

    @field_validator("merchant_domain", mode="before")
    @classmethod
    def normalize_domain(cls, value):
        if not isinstance(value, str):
            return value
        normalized = value.strip().casefold()
        for prefix in ("https://", "http://", "www."):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
        return normalized.split("/", 1)[0] or None


class VisualCatalogMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str
    merchant_name: str
    official_domains: list[str]
    product: Product
    match_score: float = Field(ge=0, le=100)
    evidence: list[str] = Field(default_factory=list)


class VisualIntentAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["READY_FOR_CONFIRMATION", "REASK"]
    reason_code: str
    message: str
    candidate: VisualProductCandidate
    matches: list[VisualCatalogMatch] = Field(default_factory=list)
    selected_match: VisualCatalogMatch | None = None
    max_budget: int | None = None
    quantity: int
    requires_user_confirmation: bool = True
    image_retained: bool = False
    displayed_price_is_authorization: bool = False


class VisualIntentConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = Field(min_length=1, max_length=128)
    product_id: str = Field(min_length=1, max_length=128)
    max_budget: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=100)
    confirmed: Literal[True]


class VisualIntentConfirmationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["CONFIRMED"] = "CONFIRMED"
    reason_code: str = "VISUAL_PRODUCT_CONFIRMED"
    intent_id: str
    intent: dict[str, Any]
    merchant_id: str
    product: Product
    evaluation: dict[str, Any]
    razorpay_test_request: dict[str, Any] | None = None
    next_step: str


class VisualAnalyzerConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["LOCAL_OCR", "OPENAI_VISION"]
    local_ocr_available: bool
    openai_configured: bool
    sends_images_to_external_provider: bool
    message: str
