from pydantic import BaseModel, Field

class Product(BaseModel):
    product_id: str
    name: str
    category: str

    price: int = Field(gt = 0)

    brand: str
    color: str | None = None

    rating: float = Field(ge = 0, le = 5)

    features: list[str] = Field(default_factory= list)

    in_stock: bool = True
