from pydantic import BaseModel, Field


class MerchantPolicy(BaseModel):
    merchant_id: str

    human_approval_threshold: int | None = Field(
        default=None,
        gt=0
    )