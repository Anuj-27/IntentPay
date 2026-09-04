from pydantic import BaseModel, ConfigDict, Field, model_validator


class MerchantPolicySettingsUpdate(BaseModel):
    """What a merchant can edit about their own policy from the dashboard.
    Deliberately narrow -- autonomous_transaction_limit is the field that
    actually matters day to day; the hard ceiling and daily caps stay
    operator-configured to avoid a merchant accidentally disabling their
    own safety rails from a single form field."""

    model_config = ConfigDict(extra="forbid")

    autonomous_transaction_limit: int = Field(gt=0)


class MerchantPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = Field(min_length=1, max_length=128)

    # Absolute hard-reject ceiling -- a fraud/liability cap, distinct from
    # autonomous-execution eligibility below. A transaction above this is
    # never processed by this system at all, reviewed or not.
    max_transaction_amount: int | None = Field(
        default=None,
        gt=0,
    )

    # The maximum amount the AI agent can execute autonomously under this
    # policy. This is NOT "everything above this is manually approved" --
    # it is the boundary of the autonomous envelope. What happens to a
    # transaction outside that envelope is governed by
    # `require_human_review_for_policy_exceptions` below.
    autonomous_transaction_limit: int | None = Field(
        default=None,
        gt=0,
    )

    # Aggregate ceilings so a merchant's total autonomous exposure stays
    # bounded even when every individual transaction is small -- the
    # scale-safety valve. Tracked per calendar day (UTC) in
    # `MerchantAutonomousUsageDB` / merchant_usage_service.py.
    daily_autonomous_amount_limit: int | None = Field(
        default=None,
        gt=0,
    )
    daily_autonomous_transaction_limit: int | None = Field(
        default=None,
        gt=0,
    )

    # Optional, stricter bar than `autonomous_transaction_limit` -- lets a
    # cautious merchant flag high-value orders for review even while they
    # are still within the normal autonomous envelope.
    high_value_review_threshold: int | None = Field(
        default=None,
        gt=0,
    )

    # Decides how ANY of the exceptions above are handled: True routes to
    # ESCALATE (a human review queue exists for this merchant), False
    # routes to BLOCK (no review queue -- the merchant would rather hard
    # reject than hold a queue). Real and deterministic: it only depends
    # on this policy object, never on Intent/Trust-layer signals.
    require_human_review_for_policy_exceptions: bool = True

    # Reserved for a future risk-scoring signal. There is no risk engine
    # in this codebase today, so this field is stored and validated but
    # deliberately evaluates as a no-op in evaluate_merchant_policy --
    # documented there, not faked with an invented heuristic.
    require_human_review_for_high_risk: bool = False

    @model_validator(mode="after")
    def validate_threshold_order(self):
        if (
            self.autonomous_transaction_limit is not None
            and self.max_transaction_amount is not None
            and self.autonomous_transaction_limit
            > self.max_transaction_amount
        ):
            raise ValueError(
                "The autonomous transaction limit cannot exceed "
                "the hard transaction limit."
            )

        if (
            self.high_value_review_threshold is not None
            and self.autonomous_transaction_limit is not None
            and self.high_value_review_threshold
            > self.autonomous_transaction_limit
        ):
            raise ValueError(
                "The high-value review threshold cannot exceed "
                "the autonomous transaction limit."
            )

        return self
