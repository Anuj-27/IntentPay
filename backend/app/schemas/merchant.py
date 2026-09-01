from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from backend.app.schemas.merchant_policy import MerchantPolicy
from backend.app.schemas.product import Product


MerchantCapabilityName = Literal[
    "catalog_search",
    "inventory_check",
    "checkout",
    "refunds",
]


class MerchantCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_search: bool = False
    inventory_check: bool = False
    checkout: bool = False
    refunds: bool = False


class MerchantProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=200)
    contract_version: str = Field(
        default="1.0",
        pattern=r"^\d+\.\d+$",
    )
    currency: Literal["INR"] = "INR"
    active: bool = False
    official_domains: list[str] = Field(default_factory=list)
    capabilities: MerchantCapabilities
    policy: MerchantPolicy


class MerchantCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = Field(min_length=1, max_length=128)
    products: list[Product] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_product_ids(self):
        product_ids = [
            product.product_id
            for product in self.products
        ]

        if len(product_ids) != len(set(product_ids)):
            raise ValueError(
                "Merchant catalog contains duplicate product IDs."
            )

        return self


class MerchantContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant: MerchantProfile
    catalog: MerchantCatalog

    @model_validator(mode="after")
    def validate_merchant_ids(self):
        merchant_id = self.merchant.merchant_id

        if self.merchant.policy.merchant_id != merchant_id:
            raise ValueError(
                "Merchant policy belongs to a different merchant."
            )

        if self.catalog.merchant_id != merchant_id:
            raise ValueError(
                "Merchant catalog belongs to a different merchant."
            )

        return self
