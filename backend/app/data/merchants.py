from backend.app.data.merchant_policies import merchant_policy
from backend.app.data.products import products
from backend.app.schemas.merchant import (
    MerchantCapabilities,
    MerchantCatalog,
    MerchantContract,
    MerchantProfile,
)
from backend.app.schemas.intent import DEFAULT_MERCHANT_ID


demo_merchant_contract = MerchantContract(
    merchant=MerchantProfile(
        merchant_id=DEFAULT_MERCHANT_ID,
        display_name="DemoStore",
        active=True,
        capabilities=MerchantCapabilities(
            catalog_search=True,
            inventory_check=True,
            checkout=True,
            refunds=True,
        ),
        policy=merchant_policy,
    ),
    catalog=MerchantCatalog(
        merchant_id=DEFAULT_MERCHANT_ID,
        products=products,
    ),
)


merchant_contracts = {
    demo_merchant_contract.merchant.merchant_id: (
        demo_merchant_contract
    ),
}
