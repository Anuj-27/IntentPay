from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


PreferenceLevel = Literal["ANY", "PREFERRED", "EXACT"]
PurchasePriority = Literal["CHEAPEST", "BEST_VALUE", "HIGHEST_RATING"]
DEFAULT_MERCHANT_ID = "MERCHANT-001"


class IntentMandate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = Field(
        default=DEFAULT_MERCHANT_ID,
        min_length=1,
        max_length=128,
    )
    product_category: str = Field(min_length=1, max_length=100)

    max_budget: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=100)

    color: str | None = None
    color_preference: PreferenceLevel = "ANY"

    brand: str | None = None
    brand_preference: PreferenceLevel = "ANY"

    subscription_allowed: bool = False
    autonomous_selection_allowed: bool = False

    priority: PurchasePriority = "BEST_VALUE"
    preferred_features: list[str] = Field(default_factory=list)

    @field_validator("product_category", mode="before")
    @classmethod
    def normalize_category(cls, value):
        if isinstance(value, str):
            return value.strip().casefold()
        return value

    @field_validator("merchant_id", mode="before")
    @classmethod
    def normalize_merchant_id(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("brand", "color", mode="before")
    @classmethod
    def strip_optional_text(cls, value):
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("preferred_features", mode="before")
    @classmethod
    def normalize_features(cls, value):
        if value is None:
            return []

        normalized = []
        seen = set()
        for feature in value:
            cleaned = feature.strip()
            key = cleaned.casefold()
            if cleaned and key not in seen:
                normalized.append(cleaned)
                seen.add(key)
        return normalized

    @model_validator(mode="after")
    def validate_preferences(self):
        if self.color_preference in {"PREFERRED", "EXACT"} and self.color is None:
            raise ValueError(
                "color must be provided when color_preference is PREFERRED or EXACT"
            )
        if self.brand_preference in {"PREFERRED", "EXACT"} and self.brand is None:
            raise ValueError(
                "brand must be provided when brand_preference is PREFERRED or EXACT"
            )
        return self


class IntentSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=128)
