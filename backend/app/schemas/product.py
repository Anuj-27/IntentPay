from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator


ProductAttributeValue: TypeAlias = str | int | float | bool


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)

    price: int = Field(gt=0)

    brand: str = Field(min_length=1, max_length=100)
    color: str | None = None

    model: str | None = Field(default=None, max_length=100)
    variant: str | None = Field(default=None, max_length=100)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    image_url: str | None = Field(default=None, max_length=2048)
    product_url: str | None = Field(default=None, max_length=2048)

    rating: float = Field(ge=0, le=5)

    features: list[str] = Field(default_factory=list)
    attributes: dict[str, ProductAttributeValue] = Field(default_factory=dict)

    in_stock: bool = True

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value):
        if isinstance(value, str):
            return value.strip().casefold()
        return value

    @field_validator("model", "variant", mode="before")
    @classmethod
    def strip_optional_text(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("attributes", mode="before")
    @classmethod
    def normalize_attribute_keys(cls, value):
        if value is None:
            return {}
        return {
            str(key).strip().casefold(): attribute_value
            for key, attribute_value in value.items()
            if str(key).strip()
        }
