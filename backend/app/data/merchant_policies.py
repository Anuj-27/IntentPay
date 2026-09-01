from backend.app.schemas.merchant_policy import MerchantPolicy

merchant_policy = MerchantPolicy(
    merchant_id="MERCHANT-001",
    max_transaction_amount=10000,
    human_approval_threshold=3500,
)

tech_merchant_policy = MerchantPolicy(
    merchant_id="MERCHANT-002",
    max_transaction_amount=150000,
    human_approval_threshold=100000,
)

vision_merchant_policy = MerchantPolicy(
    merchant_id="MERCHANT-003",
    max_transaction_amount=150000,
    human_approval_threshold=100000,
)
