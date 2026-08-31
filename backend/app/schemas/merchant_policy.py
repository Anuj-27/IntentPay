from pydantic import BaseModel, ConfigDict, Field, model_validator


class MerchantPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = Field(min_length=1, max_length=128)

    max_transaction_amount: int | None = Field(
        default=None,
        gt=0,
    )

    human_approval_threshold: int | None = Field(
        default=None,
        gt=0,
    )

    @model_validator(mode="after")
    def validate_threshold_order(self):
        if (
            self.max_transaction_amount is not None
            and self.human_approval_threshold is not None
            and self.human_approval_threshold
            > self.max_transaction_amount
        ):
            raise ValueError(
                "Human approval threshold cannot exceed "
                "the hard transaction limit."
            )

        return self
