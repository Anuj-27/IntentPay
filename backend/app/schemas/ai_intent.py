from pydantic import BaseModel, Field


class NaturalLanguageIntentRequest(BaseModel):
    message: str = Field(
        min_length=3,
        max_length=2000
    )