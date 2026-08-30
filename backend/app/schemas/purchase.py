from pydantic import BaseModel, ConfigDict, Field

class ProposedPurchase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=128)

    quantity: int = Field(ge=1)

    unit_price: int = Field(gt=0)

    total_amount: int = Field(gt=0)

    subscription: bool = False


class PurchaseVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_id: str = Field(min_length=1, max_length=128)
    purchase: ProposedPurchase
