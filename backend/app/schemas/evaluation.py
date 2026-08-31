from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.decision import DecisionType
from backend.app.schemas.intent import IntentMandate


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=128)
    category: str = Field(min_length=1, max_length=128)
    intent: IntentMandate
    confirmed_product_id: str | None = None
    expected_decision: DecisionType
    expected_reason_code: str = Field(min_length=1, max_length=128)
    expected_product_id: str | None = None


class EvaluationCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: str
    passed: bool
    expected_decision: DecisionType
    actual_decision: DecisionType
    expected_reason_code: str
    actual_reason_code: str
    expected_product_id: str | None = None
    actual_product_id: str | None = None
    latency_ms: float = Field(ge=0)


class EvaluationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    pass_rate_percent: float = Field(ge=0, le=100)
    decision_accuracy_percent: float = Field(ge=0, le=100)
    reason_code_accuracy_percent: float = Field(ge=0, le=100)
    product_accuracy_percent: float = Field(ge=0, le=100)
    unsafe_allow_count: int = Field(ge=0)
    unsafe_allow_rate_percent: float = Field(ge=0, le=100)
    false_block_count: int = Field(ge=0)
    reauthorization_count: int = Field(ge=0)
    policy_escalation_count: int = Field(ge=0)
    average_decision_latency_ms: float = Field(ge=0)
    p95_decision_latency_ms: float = Field(ge=0)
    outcome_counts: dict[str, int]


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_name: str
    dataset_version: str
    synthetic_data_only: bool = True
    metrics: EvaluationMetrics
    case_results: list[EvaluationCaseResult] = Field(default_factory=list)


class EvaluationDatasetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_name: str
    dataset_version: str
    total_cases: int
    returned_cases: int
    synthetic_data_only: bool = True
    cases: list[EvaluationCase]

