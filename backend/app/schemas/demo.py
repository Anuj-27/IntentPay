from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DemoScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1)
    expected_outcome: str = Field(min_length=1)
    api_story: list[str] = Field(default_factory=list)


class DemoScenarioList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    real_money_moved: bool = False
    scenarios: list[DemoScenario]


class DemoScenarioRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    mode: str
    real_money_moved: bool = False
    expected_outcome: str
    observed_outcome: str
    passed: bool
    duration_ms: float = Field(ge=0)
    result: dict[str, Any]

