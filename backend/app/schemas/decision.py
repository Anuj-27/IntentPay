from enum import Enum

from pydantic import BaseModel

class DecisionType(str, Enum):
    ALLOW = "ALLOW"
    REASK = "REASK"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"

class DecisionResult(BaseModel):
    decision: DecisionType
    reason_code: str
    message: str

    product_id: str | None = None
    requires_user_action: bool = False
