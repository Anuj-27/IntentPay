from backend.app.data.expanded_products import tech_products, vision_products
from backend.app.data.merchant_policies import (
    merchant_policy,
    tech_merchant_policy,
    vision_merchant_policy,
)
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
        official_domains=["demostore.example"],
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


tech_merchant_contract = MerchantContract(
    merchant=MerchantProfile(
        merchant_id="MERCHANT-002",
        display_name="DemoTech",
        active=True,
        official_domains=["demotech.example"],
        capabilities=MerchantCapabilities(
            catalog_search=True,
            inventory_check=True,
            checkout=True,
            refunds=True,
        ),
        policy=tech_merchant_policy,
    ),
    catalog=MerchantCatalog(
        merchant_id="MERCHANT-002",
        products=tech_products,
    ),
)


vision_merchant_contract = MerchantContract(
    merchant=MerchantProfile(
        merchant_id="MERCHANT-003",
        display_name="DemoVision",
        active=True,
        official_domains=["demovision.example"],
        capabilities=MerchantCapabilities(
            catalog_search=True,
            inventory_check=True,
            checkout=True,
            refunds=True,
        ),
        policy=vision_merchant_policy,
    ),
    catalog=MerchantCatalog(
        merchant_id="MERCHANT-003",
        products=vision_products,
    ),
)


merchant_contracts = {
    demo_merchant_contract.merchant.merchant_id: (
        demo_merchant_contract
    ),
    tech_merchant_contract.merchant.merchant_id: tech_merchant_contract,
    vision_merchant_contract.merchant.merchant_id: vision_merchant_contract,
}
