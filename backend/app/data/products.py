from backend.app.schemas.product import Product


products = [
    Product(
        product_id="PROD-001",
        name="Sony Basic Wireless",
        category="headphones",
        price=3200,
        brand="Sony",
        color="black",
        rating=4.2,
        features=[
            "30-hour battery",
            "basic microphone"
        ],
        in_stock=True
    ),

    Product(
        product_id="PROD-002",
        name="Sony Premium Wireless",
        category="headphones",
        price=4800,
        brand="Sony",
        color="black",
        rating=4.7,
        features=[
            "40-hour battery",
            "ANC",
            "fast charging",
            "better microphone"
        ],
        in_stock=True
    ),

    Product(
        product_id="PROD-003",
        name="JBL Tune Wireless",
        category="headphones",
        price=3500,
        brand="JBL",
        color="blue",
        rating=4.5,
        features=[
            "35-hour battery",
            "fast charging"
        ],
        in_stock=True
    ),

    Product(
        product_id="PROD-004",
        name="Sony Ultra Wireless",
        category="headphones",
        price=5500,
        brand="Sony",
        color="black",
        rating=4.8,
        features=[
            "50-hour battery",
            "advanced ANC",
            "fast charging",
            "premium microphone",
            "multipoint connection"
        ],
        in_stock=True
    )
]