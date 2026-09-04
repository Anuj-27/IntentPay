from sqlalchemy.orm import Session

from backend.app.data.merchants import merchant_contracts
from backend.app.db.models import MerchantProfileDB, ProductOverrideDB
from backend.app.schemas.merchant import (
    MerchantCapabilities,
    MerchantCapabilityName,
    MerchantCatalog,
    MerchantContract,
    MerchantProfile,
)
from backend.app.schemas.merchant_policy import MerchantPolicy
from backend.app.schemas.product import Product


DEFAULT_MAX_TRANSACTION_AMOUNT = 50_000
DEFAULT_HUMAN_APPROVAL_THRESHOLD = 20_000


def _contract_from_registered_profile(profile: MerchantProfileDB) -> MerchantContract:
    return MerchantContract(
        merchant=MerchantProfile(
            merchant_id=profile.merchant_id,
            display_name=profile.display_name,
            currency=profile.currency,
            active=profile.active,
            official_domains=[],
            capabilities=MerchantCapabilities(
                catalog_search=profile.catalog_search,
                inventory_check=profile.inventory_check,
                checkout=profile.checkout,
                refunds=profile.refunds,
            ),
            policy=MerchantPolicy(
                merchant_id=profile.merchant_id,
                max_transaction_amount=profile.max_transaction_amount,
                human_approval_threshold=profile.human_approval_threshold,
            ),
        ),
        catalog=MerchantCatalog(merchant_id=profile.merchant_id, products=[]),
    )


def find_registered_merchant_contract(
    merchant_id: str,
    db: Session,
) -> MerchantContract | None:
    profile = (
        db.query(MerchantProfileDB)
        .filter(MerchantProfileDB.merchant_id == merchant_id)
        .first()
    )
    if profile is None:
        return None
    return _contract_from_registered_profile(profile)


def merchant_id_is_taken(db: Session, merchant_id: str) -> bool:
    if merchant_id in merchant_contracts:
        return True
    existing = (
        db.query(MerchantProfileDB)
        .filter(MerchantProfileDB.merchant_id == merchant_id)
        .first()
    )
    return existing is not None


def register_merchant_profile(
    db: Session,
    merchant_id: str,
    display_name: str,
    *,
    commit: bool = True,
) -> MerchantProfileDB:
    profile = MerchantProfileDB(
        merchant_id=merchant_id,
        display_name=display_name,
        max_transaction_amount=DEFAULT_MAX_TRANSACTION_AMOUNT,
        human_approval_threshold=DEFAULT_HUMAN_APPROVAL_THRESHOLD,
    )
    db.add(profile)
    if commit:
        db.commit()
        db.refresh(profile)
    else:
        db.flush()
    return profile


def _product_from_override(row: ProductOverrideDB) -> Product:
    return Product(
        product_id=row.product_id,
        name=row.name,
        category=row.category,
        price=row.price,
        brand=row.brand,
        color=row.color,
        model=row.model,
        variant=row.variant,
        currency=row.currency,
        image_url=row.image_url,
        images=list(row.images or []),
        product_url=row.product_url,
        rating=row.rating,
        features=list(row.features or []),
        attributes=dict(row.attributes or {}),
        in_stock=row.in_stock,
    )


def apply_merchant_product_overlay(
    contract: MerchantContract,
    db: Session,
) -> MerchantContract:
    overrides = {
        row.product_id: row
        for row in db.query(ProductOverrideDB)
        .filter(ProductOverrideDB.merchant_id == contract.merchant.merchant_id)
        .all()
    }

    merged_products: list[Product] = []
    seen_product_ids: set[str] = set()

    for product in contract.catalog.products:
        seen_product_ids.add(product.product_id)
        override = overrides.get(product.product_id)
        if override is None:
            merged_products.append(product)
        elif override.is_active:
            merged_products.append(_product_from_override(override))

    for product_id, override in overrides.items():
        if product_id in seen_product_ids or not override.is_active:
            continue
        merged_products.append(_product_from_override(override))

    return contract.model_copy(
        update={
            "catalog": contract.catalog.model_copy(
                update={"products": merged_products}
            )
        }
    )


def find_merchant_contract(
    merchant_id: str,
    db: Session | None = None,
    apply_overlay: bool = True,
) -> MerchantContract | None:
    """Resolve a merchant's identity, optionally merging its product
    overlay. `db` alone controls whether self-registered merchants (who
    only exist in the database) can be found at all; `apply_overlay`
    separately controls whether their catalog is buyer-facing-merged or
    left as the raw baseline. Dashboard management code needs the raw
    baseline to tell static products apart from ones the merchant added --
    passing an already-merged contract there would make every product
    look non-custom on the next read."""

    contract = merchant_contracts.get(merchant_id)

    if contract is None:
        if db is None:
            return None
        contract = find_registered_merchant_contract(merchant_id, db)
        if contract is None:
            return None
    else:
        contract = contract.model_copy(deep=True)

    if db is not None and apply_overlay:
        contract = apply_merchant_product_overlay(contract, db)

    return contract


def list_merchant_dashboard_products(
    contract: MerchantContract,
    db: Session,
) -> list[dict]:
    """Every product the merchant owns, including deactivated ones, for
    the merchant's own dashboard view (buyers never see this list)."""

    overrides = {
        row.product_id: row
        for row in db.query(ProductOverrideDB)
        .filter(ProductOverrideDB.merchant_id == contract.merchant.merchant_id)
        .all()
    }

    entries: dict[str, dict] = {}

    for product in contract.catalog.products:
        entries[product.product_id] = {
            "product": product,
            "is_custom": False,
            "is_active": True,
        }

    for product_id, override in overrides.items():
        entries[product_id] = {
            "product": _product_from_override(override),
            "is_custom": product_id not in entries,
            "is_active": override.is_active,
        }

    return list(entries.values())


def upsert_merchant_product(
    db: Session,
    contract: MerchantContract,
    product: Product,
) -> ProductOverrideDB:
    existing = (
        db.query(ProductOverrideDB)
        .filter(
            ProductOverrideDB.merchant_id == contract.merchant.merchant_id,
            ProductOverrideDB.product_id == product.product_id,
        )
        .first()
    )

    if existing is None:
        existing = ProductOverrideDB(
            merchant_id=contract.merchant.merchant_id,
            product_id=product.product_id,
            is_active=True,
        )
        db.add(existing)

    existing.name = product.name
    existing.category = product.category
    existing.price = product.price
    existing.brand = product.brand
    existing.color = product.color
    existing.model = product.model
    existing.variant = product.variant
    existing.currency = product.currency
    existing.image_url = product.image_url
    existing.images = [image.model_dump() for image in product.images]
    existing.product_url = product.product_url
    existing.rating = product.rating
    existing.features = list(product.features)
    existing.attributes = dict(product.attributes)
    existing.in_stock = product.in_stock

    db.commit()
    db.refresh(existing)
    return existing


def set_merchant_product_active_state(
    db: Session,
    contract: MerchantContract,
    product_id: str,
    is_active: bool,
) -> ProductOverrideDB | None:
    existing = (
        db.query(ProductOverrideDB)
        .filter(
            ProductOverrideDB.merchant_id == contract.merchant.merchant_id,
            ProductOverrideDB.product_id == product_id,
        )
        .first()
    )

    if existing is None:
        base_product = next(
            (
                product
                for product in contract.catalog.products
                if product.product_id == product_id
            ),
            None,
        )
        if base_product is None:
            return None
        existing = ProductOverrideDB(
            merchant_id=contract.merchant.merchant_id,
            product_id=base_product.product_id,
            name=base_product.name,
            category=base_product.category,
            price=base_product.price,
            brand=base_product.brand,
            color=base_product.color,
            model=base_product.model,
            variant=base_product.variant,
            currency=base_product.currency,
            image_url=base_product.image_url,
            images=[image.model_dump() for image in base_product.images],
            product_url=base_product.product_url,
            rating=base_product.rating,
            features=list(base_product.features),
            attributes=dict(base_product.attributes),
            in_stock=base_product.in_stock,
        )
        db.add(existing)

    existing.is_active = is_active
    db.commit()
    db.refresh(existing)
    return existing


def list_merchant_contracts(db: Session | None = None) -> list[MerchantContract]:
    contracts = [
        contract.model_copy(deep=True)
        for contract in merchant_contracts.values()
    ]
    if db is not None:
        # The static demo merchants (MERCHANT-001/002/003) need their
        # ProductOverrideDB overlay merged in too, exactly like
        # `find_merchant_contract` already does -- otherwise a price/
        # image/feature edit (or deactivation) made through the merchant
        # dashboard is invisible to every caller that lists *all*
        # merchants at once (chat/search discovery, /merchants,
        # /categories), even though it's correctly reflected by the
        # single-merchant catalog endpoints buyers and the dashboard use.
        contracts = [
            apply_merchant_product_overlay(contract, db)
            for contract in contracts
        ]
        registered_profiles = db.query(MerchantProfileDB).all()
        contracts.extend(
            apply_merchant_product_overlay(
                _contract_from_registered_profile(profile), db
            )
            for profile in registered_profiles
        )
    return contracts


def find_merchant_contracts_for_category(
    category: str,
) -> list[MerchantContract]:
    normalized_category = category.strip().casefold()
    return [
        contract
        for contract in list_merchant_contracts()
        if any(
            product.category.casefold() == normalized_category
            for product in contract.catalog.products
        )
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
