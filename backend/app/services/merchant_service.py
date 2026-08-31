from backend.app.data.merchants import merchant_contracts
from backend.app.schemas.merchant import (
    MerchantCapabilityName,
    MerchantContract,
)
from backend.app.schemas.product import Product


def find_merchant_contract(
    merchant_id: str,
) -> MerchantContract | None:
    contract = merchant_contracts.get(merchant_id)

    if contract is None:
        return None

    return contract.model_copy(deep=True)


def list_merchant_contracts() -> list[MerchantContract]:
    return [
        contract.model_copy(deep=True)
        for contract in merchant_contracts.values()
    ]


def find_catalog_product(
    contract: MerchantContract,
    product_id: str,
) -> Product | None:
    return next(
        (
            product
            for product in contract.catalog.products
            if product.product_id == product_id
        ),
        None,
    )


def check_merchant_access(
    contract: MerchantContract,
    required_capabilities: tuple[
        MerchantCapabilityName,
        ...,
    ] = (),
) -> dict:
    if not contract.merchant.active:
        return {
            "available": False,
            "reason_code": "MERCHANT_INACTIVE",
            "message": "The merchant is not active for agent commerce.",
        }

    for capability in required_capabilities:
        if not getattr(contract.merchant.capabilities, capability):
            return {
                "available": False,
                "reason_code": (
                    f"MERCHANT_{capability.upper()}_UNAVAILABLE"
                ),
                "message": (
                    f"The merchant does not expose the '{capability}' "
                    "capability to agents."
                ),
            }

    return {
        "available": True,
        "reason_code": "MERCHANT_ACCESS_AVAILABLE",
        "message": "The required merchant capabilities are available.",
    }
