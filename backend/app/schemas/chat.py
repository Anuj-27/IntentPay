from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas.product import Product
from backend.app.schemas.visual_intent import (
    SupportedImageMediaType,
    VisualProductCandidate,
)


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatProductSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str
    merchant_name: str
    product: Product
    score: float = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list, max_length=8)
    total_amount: int = Field(gt=0)
    within_budget: bool | None = None


class ChatUpsellSuggestion(BaseModel):
    """An above-budget alternative surfaced by IntentPay's existing
    budget-stretch/upsell engine (see `product_search_service.
    find_upsell_candidates`), never invented purely from fuzzy text
    similarity."""

    model_config = ConfigDict(extra="forbid")

    merchant_id: str
    merchant_name: str
    product: Product
    total_amount: int = Field(gt=0)
    over_budget_amount: int
    over_budget_percent: float
    rating_gain: float
    new_features: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list, max_length=8)
    status: Literal["REQUIRES_REAUTHORIZATION"] = "REQUIRES_REAUTHORIZATION"


class ChatIntentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str | None = None
    brand: str | None = None
    color: str | None = None
    max_budget: int | None = None
    quantity: int = Field(default=1, ge=1, le=100)
    preferences: list[str] = Field(default_factory=list, max_length=12)
    brand_preference: Literal["ANY", "PREFERRED", "EXACT"] = "ANY"
    color_preference: Literal["ANY", "PREFERRED", "EXACT"] = "ANY"
    priority: Literal["CHEAPEST", "BEST_VALUE", "HIGHEST_RATING"] = "BEST_VALUE"
    subscription_allowed: bool = False
    autonomous_selection_allowed: bool = False


class ProductAssistantChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1, max_length=20)
    image_base64: str | None = Field(default=None, min_length=16, max_length=7_000_000)
    media_type: SupportedImageMediaType | None = None
    max_budget: int | None = Field(default=None, gt=0)
    quantity: int = Field(default=1, ge=1, le=100)
    merchant_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_image_pair_and_user_turn(self):
        if (self.image_base64 is None) != (self.media_type is None):
            raise ValueError("image_base64 and media_type must be provided together.")
        if not any(message.role == "user" for message in self.messages):
            raise ValueError("At least one user message is required.")
        return self


class ProductAssistantChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: str
    suggestions: list[ChatProductSuggestion] = Field(default_factory=list, max_length=8)
    upsell_candidates: list[ChatUpsellSuggestion] = Field(default_factory=list, max_length=5)
    visual_candidate: VisualProductCandidate | None = None
    # How the products in `suggestions` were found. IMAGE_MATCH means an
    # uploaded photo was successfully analyzed and its extracted identity
    # was resolved against the catalog -- the catalog product (and its
    # image_url) is always the one returned, never anything derived
    # directly from the upload.
    match_type: Literal["IMAGE_MATCH", "TEXT_MATCH", "NONE"] = "NONE"
    intent: ChatIntentSummary
    next_action: Literal[
        "PROVIDE_CATEGORY",
        "PROVIDE_PRODUCT_HINT",
        "PROVIDE_BUDGET",
        "CHOOSE_PRODUCT",
        "OPEN_VERIFICATION",
        "NONE",
    ]
    discovery_only: bool = True
    image_retained: bool = False
    external_provider_used: bool = False
