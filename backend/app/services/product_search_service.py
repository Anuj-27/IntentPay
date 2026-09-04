"""The product discovery pipeline: turns a normalized shopper query into a
ranked list of catalog products.

    query normalization  -->  typo correction  -->  retrieval  -->  ranking

This module is deliberately catalog-driven: every word it can match
against (brand names, product names, models, features, category aliases)
is read fresh from the merchant catalogs on every call. There is no
static "iphone" -> "Apple" rule anywhere here and no cache to invalidate
-- a product a merchant just added is visible on the very next request
because we never keep our own copy of the catalog around.
"""

import logging
from dataclasses import dataclass

from backend.app.data.categories import CATEGORIES, detect_category
from backend.app.schemas.intent import IntentMandate
from backend.app.schemas.merchant import MerchantContract
from backend.app.schemas.product import Product
from backend.app.services.budget_stretch import find_budget_stretch_candidates
from backend.app.services.fuzzy_match import best_fuzzy_match, is_fuzzy_match, similarity_ratio
from backend.app.services.merchant_service import list_merchant_contracts
from backend.app.services.product_filter import filter_products
from backend.app.services.query_normalizer import normalize_query, tokenize


logger = logging.getLogger(__name__)


# A confident text/brand match is allowed to decide the category even when
# the shopper never named one ("iphone" implies smartphones). This floor
# keeps genuinely unrelated gibberish from being assigned a category.
CATEGORY_INFERENCE_SCORE_FLOOR = 28.0


@dataclass(frozen=True)
class CatalogEntry:
    merchant_id: str
    merchant_name: str
    product: Product


@dataclass(frozen=True)
class ProductMatch:
    merchant_id: str
    merchant_name: str
    product: Product
    score: float
    reasons: list[str]
    total_amount: int
    within_budget: bool | None


@dataclass(frozen=True)
class SearchContext:
    """Output of intent understanding + normalization + typo correction,
    before any product is retrieved."""

    normalized_text: str
    search_tokens: tuple[str, ...]
    corrected_tokens: tuple[str, ...]
    correction_applied: bool
    category: str | None
    brand: str | None
    color: str | None = None


def build_catalog_entries(
    db,
    *,
    merchant_id: str | None = None,
    include_out_of_stock: bool = False,
) -> list[CatalogEntry]:
    """The current, live product catalog across every active merchant.
    Always read directly from the merchant contracts (which themselves
    merge in `ProductOverrideDB` when `db` is supplied) -- no snapshot is
    kept between calls, so a product created a second ago is already
    here."""

    entries: list[CatalogEntry] = []
    contracts: list[MerchantContract] = list_merchant_contracts(db=db)

    for contract in contracts:
        if merchant_id is not None and contract.merchant.merchant_id != merchant_id:
            continue
        if not contract.merchant.active:
            continue
        for product in contract.catalog.products:
            if not include_out_of_stock and not product.in_stock:
                continue
            entries.append(
                CatalogEntry(
                    merchant_id=contract.merchant.merchant_id,
                    merchant_name=contract.merchant.display_name,
                    product=product,
                )
            )

    return entries


def _product_tokens(product: Product) -> set[str]:
    text = " ".join(
        value
        for value in (product.brand, product.name, product.model, product.variant)
        if value
    )
    return set(tokenize(text))


def _category_vocabulary() -> set[str]:
    vocabulary: set[str] = set()
    for category in CATEGORIES:
        vocabulary.add(category.category_id)
        for alias in category.aliases:
            vocabulary.update(tokenize(alias))
    return vocabulary


def build_vocabulary(entries: list[CatalogEntry]) -> set[str]:
    """Every word search can plausibly be typo-corrected toward: category
    names, plus every brand/product-name/model/variant/feature word
    currently in the live catalog."""

    vocabulary = _category_vocabulary()
    for entry in entries:
        vocabulary.update(_product_tokens(entry.product))
        for feature in entry.product.features:
            vocabulary.update(tokenize(feature))
    return vocabulary


def correct_tokens(tokens: tuple[str, ...], vocabulary: set[str]) -> tuple[tuple[str, ...], bool]:
    corrected: list[str] = []
    changed = False

    for token in tokens:
        if token in vocabulary:
            corrected.append(token)
            continue
        match = best_fuzzy_match(token, vocabulary)
        if match is not None:
            corrected.append(match[0])
            changed = True
        else:
            corrected.append(token)

    return tuple(corrected), changed


def _brand_vocabulary(entries: list[CatalogEntry]) -> dict[str, str]:
    """casefolded brand -> canonical display brand, sourced from whatever
    products the merchants currently sell."""

    brands: dict[str, str] = {}
    for entry in entries:
        brands.setdefault(entry.product.brand.casefold(), entry.product.brand)
    return brands


def infer_brand(tokens: tuple[str, ...], entries: list[CatalogEntry]) -> str | None:
    brand_vocabulary = _brand_vocabulary(entries)
    if not brand_vocabulary:
        return None

    for token in tokens:
        if len(token) < 3:
            continue
        match = best_fuzzy_match(token, brand_vocabulary.keys())
        if match is not None:
            return brand_vocabulary[match[0]]
    return None


def _color_vocabulary(entries: list[CatalogEntry]) -> dict[str, str]:
    """casefolded color -> canonical display color, sourced from whatever
    colors the current catalog actually has -- not a fixed English color
    list, so it naturally covers whatever a merchant's products use."""

    colors: dict[str, str] = {}
    for entry in entries:
        if entry.product.color:
            colors.setdefault(entry.product.color.casefold(), entry.product.color)
    return colors


def infer_color(tokens: tuple[str, ...], entries: list[CatalogEntry]) -> str | None:
    color_vocabulary = _color_vocabulary(entries)
    if not color_vocabulary:
        return None

    for token in tokens:
        if len(token) < 3:
            continue
        match = best_fuzzy_match(token, color_vocabulary.keys())
        if match is not None:
            return color_vocabulary[match[0]]
    return None


def _category_from_alias_tokens(tokens: tuple[str, ...]) -> str | None:
    best: tuple[int, str] | None = None
    for category in CATEGORIES:
        for alias in category.aliases:
            for alias_word in tokenize(alias):
                for token in tokens:
                    if is_fuzzy_match(token, alias_word):
                        candidate = (len(alias_word), category.category_id)
                        if best is None or candidate > best:
                            best = candidate
    return best[1] if best else None


def _category_from_catalog_match(
    tokens: tuple[str, ...],
    entries: list[CatalogEntry],
) -> str | None:
    if not tokens or not entries:
        return None

    best_category: str | None = None
    best_score = 0.0

    for entry in entries:
        product_tokens = _product_tokens(entry.product)
        if not product_tokens:
            continue

        matched = sum(
            1
            for token in tokens
            if any(is_fuzzy_match(token, product_token) for product_token in product_tokens)
        )
        if matched == 0:
            continue

        name_ratio = similarity_ratio(" ".join(tokens), entry.product.name.casefold())
        score = (matched / len(tokens)) * 60 + name_ratio * 40

        if score > best_score:
            best_score = score
            best_category = entry.product.category

    if best_score >= CATEGORY_INFERENCE_SCORE_FLOOR:
        return best_category
    return None


def resolve_search_context(
    db,
    text: str,
    *,
    merchant_id: str | None = None,
) -> SearchContext:
    """Intent extraction -> normalization -> typo correction -> category
    and brand inference, all in one pass over the *current* catalog."""

    normalized = normalize_query(text)
    entries = build_catalog_entries(db, merchant_id=merchant_id)
    vocabulary = build_vocabulary(entries)

    corrected_tokens, correction_applied = correct_tokens(normalized.search_tokens, vocabulary)
    # Also correct the joined-bigram tokens ("i" + "phone" -> "iphone") so a
    # split brand name still resolves, without polluting the primary token
    # list used for overlap scoring.
    corrected_bigrams, bigram_corrected = correct_tokens(normalized.joined_bigrams, vocabulary)
    correction_applied = correction_applied or bigram_corrected

    all_candidate_tokens = tuple(corrected_tokens) + tuple(corrected_bigrams)

    category = detect_category(text)
    if category is None and corrected_tokens:
        category = detect_category(" ".join(corrected_tokens))
    if category is None and all_candidate_tokens:
        category = _category_from_alias_tokens(all_candidate_tokens)
    if category is None and all_candidate_tokens:
        category = _category_from_catalog_match(all_candidate_tokens, entries)

    brand = infer_brand(all_candidate_tokens, entries)
    color = infer_color(all_candidate_tokens, entries)

    if correction_applied:
        logger.info(
            "product_search: corrected query tokens %s -> %s (category=%s, brand=%s)",
            normalized.search_tokens,
            corrected_tokens,
            category,
            brand,
        )

    return SearchContext(
        normalized_text=normalized.raw_text,
        search_tokens=normalized.search_tokens,
        corrected_tokens=all_candidate_tokens,
        correction_applied=correction_applied,
        category=category,
        brand=brand,
        color=color,
    )


FEATURE_SCORE_WEIGHT = 4.0


def _score_entry(
    entry: CatalogEntry,
    *,
    corrected_tokens: tuple[str, ...],
    category: str | None,
    brand: str | None,
    color: str | None,
    matched_features: list[str],
) -> tuple[float, list[str]]:
    product = entry.product
    score = 0.0
    reasons: list[str] = []

    if category is not None and product.category == category:
        score += 20.0
        reasons.append("category matched")

    query_text = " ".join(corrected_tokens)
    product_name_cf = product.name.casefold()

    if query_text and query_text in product_name_cf:
        score += 40.0
        reasons.append("product name matched")
    elif corrected_tokens and any(
        token in product_name_cf for token in corrected_tokens if len(token) > 2
    ):
        score += 20.0
        reasons.append("product name partially matched")

    product_tokens = _product_tokens(product)
    if corrected_tokens:
        overlap = sum(
            1
            for token in corrected_tokens
            if any(is_fuzzy_match(token, product_token) for product_token in product_tokens)
        )
        if overlap:
            score += min(30.0, 10.0 * overlap)
            reasons.append("model or product name matched")

    if brand:
        if product.brand.casefold() == brand.casefold():
            score += 25.0
            reasons.append("brand matched")
        elif is_fuzzy_match(brand.casefold(), product.brand.casefold()):
            score += 15.0
            reasons.append("brand closely matched")
        else:
            score -= 8.0

    if color:
        if product.color and product.color.casefold() == color.casefold():
            score += 18.0
            reasons.append("color matched")
        elif product.color:
            score -= 6.0

    if query_text:
        fuzzy = similarity_ratio(query_text, product_name_cf)
        if fuzzy > 0.35:
            score += fuzzy * 15.0
            reasons.append("similar to your search")

    if matched_features:
        score += min(15.0, FEATURE_SCORE_WEIGHT * len(matched_features))
        reasons.append(f"{len(matched_features)} preferred feature(s) matched")

    return score, reasons


def _attribute_search_tokens(product: Product) -> set[str]:
    text = " ".join(
        f"{key.replace('_', ' ')} {value}" for key, value in product.attributes.items()
    )
    return set(tokenize(text))


def _matched_features(product: Product, requested_features: list[str]) -> list[str]:
    feature_text = " ".join(product.features).casefold()
    attribute_tokens = _attribute_search_tokens(product)

    matched = []
    for feature in requested_features:
        if feature.casefold() in feature_text:
            matched.append(feature)
            continue
        feature_tokens = set(tokenize(feature))
        if feature_tokens and feature_tokens & attribute_tokens:
            matched.append(feature)
    return matched


def search_catalog(
    db,
    *,
    context: SearchContext,
    budget: int | None,
    quantity: int,
    merchant_id: str | None = None,
    requested_features: list[str] | None = None,
    limit: int = 5,
) -> list[ProductMatch]:
    """Retrieval + filtering + ranking: score every in-stock product in
    scope, apply the budget as a hard cut for the *primary* result set
    (fuzzy similarity is never allowed to push an over-budget product into
    this list -- see `find_upsell_candidates` for the above-budget path),
    then return the best matches."""

    entries = build_catalog_entries(db, merchant_id=merchant_id)
    if context.category is not None:
        entries = [entry for entry in entries if entry.product.category == context.category]

    matches: list[ProductMatch] = []
    for entry in entries:
        matched_features = _matched_features(entry.product, requested_features or [])
        score, reasons = _score_entry(
            entry,
            corrected_tokens=context.corrected_tokens,
            category=context.category,
            brand=context.brand,
            color=context.color,
            matched_features=matched_features,
        )

        total_amount = entry.product.price * quantity
        within_budget = None
        if budget is not None:
            within_budget = total_amount <= budget
            # An explicit budget is a hard financial ceiling. Above-budget
            # products are handled only by `find_upsell_candidates`; they
            # must never enter the normal suggestion/ranking set.
            if not within_budget:
                continue
            score += 20.0
            reasons.append("within maximum budget")

        if not reasons:
            continue

        matches.append(
            ProductMatch(
                merchant_id=entry.merchant_id,
                merchant_name=entry.merchant_name,
                product=entry.product,
                score=round(min(max(score, 0.0), 100.0), 2),
                reasons=reasons,
                total_amount=total_amount,
                within_budget=within_budget,
            )
        )

    if budget is not None:
        # A strong user constraint (the budget ceiling) must never be
        # overridden just because an over-budget product scored higher on
        # fuzzy similarity. Above-budget items belong in the separate
        # upsell path, not the primary result set.
        affordable = [match for match in matches if match.within_budget]
        matches = affordable

    if context.brand is not None:
        # A named brand narrows the results when a matching product
        # exists ("show me Google phones" after "Samsung phones" should
        # drop the Samsung options, not just re-rank them below Google
        # ones); falls back to the unfiltered set if nothing matches so a
        # brand the catalog doesn't carry still surfaces alternatives
        # instead of an empty response.
        brand_matches = [
            match
            for match in matches
            if match.product.brand.casefold() == context.brand.casefold()
        ]
        if brand_matches:
            matches = brand_matches

    if context.color is not None:
        # "Only black ones" should narrow the results when a matching
        # color exists; if nothing in the current category comes in that
        # color, fall back to the unfiltered set rather than showing
        # nothing (this is a stated preference, not a budget-style hard
        # constraint).
        color_matches = [
            match
            for match in matches
            if match.product.color and match.product.color.casefold() == context.color.casefold()
        ]
        if color_matches:
            matches = color_matches

    matches.sort(key=lambda match: (-match.score, match.product.price, -match.product.rating))
    return matches[:limit]


@dataclass(frozen=True)
class UpsellMatch:
    merchant_id: str
    merchant_name: str
    product: Product
    total_amount: int
    over_budget_amount: int
    over_budget_percent: float
    rating_gain: float
    new_features: list[str]
    reasons: list[str]
    status: str = "REQUIRES_REAUTHORIZATION"


def find_upsell_candidates(
    db,
    *,
    category: str,
    budget: int,
    quantity: int,
    merchant_id: str | None = None,
    limit: int = 3,
) -> list[UpsellMatch]:
    """Above-budget alternatives worth surfacing, reusing IntentPay's
    existing budget-stretch/upsell engine (`product_filter.filter_products`
    + `budget_stretch.find_budget_stretch_candidates`) instead of
    reinventing upsell rules for chat. Only "meaningfully better" products
    within the engine's stretch tolerance come back -- an arbitrary
    expensive product never qualifies just because it fuzzy-matched the
    query."""

    candidates: list[UpsellMatch] = []

    for contract in list_merchant_contracts(db=db):
        if merchant_id is not None and contract.merchant.merchant_id != merchant_id:
            continue
        if not contract.merchant.active:
            continue

        category_products = [
            product
            for product in contract.catalog.products
            if product.category == category
        ]
        if not category_products:
            continue

        try:
            intent = IntentMandate(
                merchant_id=contract.merchant.merchant_id,
                product_category=category,
                max_budget=budget,
                quantity=quantity,
            )
        except ValueError:
            continue

        allowed_products, rejected_products = filter_products(intent, category_products)
        stretch_candidates = find_budget_stretch_candidates(
            intent, allowed_products, rejected_products
        )

        for stretch in stretch_candidates:
            product = stretch["product"]
            candidates.append(
                UpsellMatch(
                    merchant_id=contract.merchant.merchant_id,
                    merchant_name=contract.merchant.display_name,
                    product=product,
                    total_amount=stretch["proposed_total"],
                    over_budget_amount=stretch["over_budget_amount"],
                    over_budget_percent=stretch["over_budget_percent"],
                    rating_gain=stretch["rating_gain"],
                    new_features=stretch["new_features"],
                    reasons=["above budget", "meaningfully better than your top match"],
                    status="REQUIRES_REAUTHORIZATION",
                )
            )

    candidates.sort(key=lambda match: match.over_budget_percent)
    return candidates[:limit]
