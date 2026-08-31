from pydantic import BaseModel, ConfigDict, Field


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)

    price: int = Field(gt=0)

    brand: str = Field(min_length=1, max_length=100)
    color: str | None = None

    rating: float = Field(ge=0, le=5)

    features: list[str] = Field(default_factory=list)

    in_stock: bool = True
