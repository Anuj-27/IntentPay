from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.buyer_agent import BuyerAgentEvaluationResult
from backend.app.schemas.protocol import CommerceContext


class FlowStageStatus(str, Enum):
    PASSED = "PASSED"
    STOPPED = "STOPPED"
    READY = "READY"
    NOT_RUN = "NOT_RUN"


class FlowStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str = Field(min_length=1, max_length=128)
    status: FlowStageStatus
    reason_code: str = Field(min_length=1, max_length=128)


class EndToEndOrchestrationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_context: CommerceContext
    evaluation: BuyerAgentEvaluationResult
    stage_trace: list[FlowStage]
    next_action: str
    payment_executed: bool = False

