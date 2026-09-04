import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.schemas.product import Product


MERCHANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")


class MerchantLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=200)


class MerchantRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)

    @field_validator("merchant_id")
    @classmethod
    def validate_merchant_id(cls, value: str) -> str:
        if not MERCHANT_ID_PATTERN.match(value):
            raise ValueError(
                "Merchant ID must be 3-64 characters: letters, numbers, "
                "hyphens, or underscores only."
            )
        return value


class MerchantForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = Field(min_length=1, max_length=128)


class MerchantForgotPasswordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    # IntentPay has no email/SMS transport configured, so (Test Mode,
    # like the rest of the project) the token is returned directly
    # instead of being emailed. None when the merchant ID has no account,
    # so the UI can't use this response to enumerate valid merchant IDs.
    reset_token: str | None = None
    expires_in_seconds: int | None = None


class MerchantResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reset_token: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=200)


class MerchantResetPasswordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reset: bool


class MerchantSessionInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str
    display_name: str


class MerchantCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: Product
    is_custom: bool
    is_active: bool


class MerchantDashboardCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str
    display_name: str
    count: int
    products: list[MerchantCatalogEntry]
