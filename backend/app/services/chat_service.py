import re

from backend.app.data.categories import canonicalize_category, detect_category
from backend.app.schemas.chat import (
    ChatIntentSummary,
    ChatProductSuggestion,
    ProductAssistantChatRequest,
    ProductAssistantChatResponse,
)
from backend.app.schemas.visual_intent import VisualIntentRequest, VisualProductCandidate
from backend.app.services.intent_extractor import (
    extract_budget_from_text,
    extract_quantity_from_text,
)
from backend.app.services.merchant_service import list_merchant_contracts
from backend.app.services.visual_intent_service import get_configured_visual_analyzer


KNOWN_BRANDS = {
    "sony": "Sony",
    "jbl": "JBL",
    "google": "Google",
    "samsung": "Samsung",
    "lenovo": "Lenovo",
    "asus": "ASUS",
    "fitbit": "Fitbit",
    "canon": "Canon",
}

FEATURE_ALIASES = {
    "anc": "ANC",
    "noise cancellation": "ANC",
    "noise cancelling": "ANC",
    "fast charging": "fast charging",
    "battery": "battery",
    "microphone": "microphone",
    "mic": "microphone",
    "5g": "5G",
    "oled": "OLED display",
    "amoled": "AMOLED display",
    "gps": "GPS",
    "sleep tracking": "sleep tracking",
    "4k": "4K video",
    "backlit keyboard": "backlit keyboard",
}


def _tokens(value: str | None) -> set[str]:
    if not value:
        return set()
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) > 1
    }


def _last_user_message(request: ProductAssistantChatRequest) -> str:
    return next(
        message.content
        for message in reversed(request.messages)
        if message.role == "user"
    )


def _conversation_text(request: ProductAssistantChatRequest) -> str:
    return "\n".join(
        message.content
        for message in request.messages
        if message.role == "user"
    )


def _optional_budget(request: ProductAssistantChatRequest, text: str) -> int | None:
    message_budget = None
    try:
        message_budget = extract_budget_from_text(text)
    except ValueError:
        pass

    if (
        request.max_budget is not None
        and message_budget is not None
        and request.max_budget != message_budget
    ):
        raise ValueError("max_budget conflicts with the maximum amount in the chat.")
    return request.max_budget if request.max_budget is not None else message_budget


def _brand_from_text(text: str) -> str | None:
    normalized = text.casefold()
    return next(
        (brand for token, brand in KNOWN_BRANDS.items() if token in normalized),
        None,
    )


def _features_from_text(text: str) -> list[str]:
    normalized = text.casefold()
    features: list[str] = []
    for phrase, feature in FEATURE_ALIASES.items():
        if phrase in normalized and feature not in features:
            features.append(feature)
    return features


def _suggest_products(
    *,
    category: str,
    text: str,
    visual_candidate: VisualProductCandidate | None,
    budget: int | None,
    quantity: int,
    merchant_id: str | None,
) -> list[ChatProductSuggestion]:
    candidate_text = " ".join(
        value
        for value in (
            text,
            visual_candidate.product_name if visual_candidate else None,
            visual_candidate.model if visual_candidate else None,
            visual_candidate.variant if visual_candidate else None,
        )
        if value
    )
    requested_tokens = _tokens(candidate_text)
    requested_brand = (
        visual_candidate.brand
        if visual_candidate and visual_candidate.brand
        else _brand_from_text(text)
    )
    requested_features = _features_from_text(text)
    if visual_candidate:
        requested_features.extend(
            feature
            for feature in visual_candidate.visible_features
            if feature not in requested_features
        )

    rows: list[ChatProductSuggestion] = []
    for contract in list_merchant_contracts():
        if merchant_id is not None and contract.merchant.merchant_id != merchant_id:
            continue
        if not contract.merchant.active:
            continue
        for product in contract.catalog.products:
            if not product.in_stock or product.category != category:
                continue

            product_tokens = _tokens(
                " ".join(value for value in (product.name, product.model, product.variant) if value)
            )
            overlap = len(requested_tokens & product_tokens)
            score = 30.0
            reasons = ["category matched"]

            if requested_brand:
                if product.brand.casefold() == requested_brand.casefold():
                    score += 25
                    reasons.append("brand matched")
                else:
                    score -= 8

            if overlap:
                score += min(30.0, 10.0 * overlap)
                reasons.append("model or product name matched")

            matched_features = [
                feature
                for feature in requested_features
                if any(feature.casefold() in value.casefold() for value in product.features)
            ]
            if matched_features:
                score += min(15.0, 5.0 * len(matched_features))
                reasons.append(f"{len(matched_features)} preferred feature(s) matched")

            total_amount = product.price * quantity
            within_budget = None
            if budget is not None:
                within_budget = total_amount <= budget
                if within_budget:
                    score += 20
                    reasons.append("within maximum budget")
                else:
                    score -= 15
                    reasons.append("above maximum budget")

            rows.append(
                ChatProductSuggestion(
                    merchant_id=contract.merchant.merchant_id,
                    merchant_name=contract.merchant.display_name,
                    product=product,
                    score=min(round(max(score, 0), 2), 100),
                    reasons=reasons,
                    total_amount=total_amount,
                    within_budget=within_budget,
                )
            )

    if budget is not None:
        affordable = [row for row in rows if row.within_budget]
        if affordable:
            rows = affordable
    return sorted(
        rows,
        key=lambda row: (-row.score, row.product.price, -row.product.rating),
    )[:5]


def build_product_assistant_chat(
    request: ProductAssistantChatRequest,
) -> ProductAssistantChatResponse:
    text = _conversation_text(request)
    last_user_message = _last_user_message(request)
    budget = _optional_budget(request, text)
    quantity = request.quantity
    try:
        parsed_quantity = extract_quantity_from_text(last_user_message)
        if request.quantity == 1 and parsed_quantity > 1:
            quantity = parsed_quantity
    except ValueError:
        pass

    visual_candidate = None
    visual_error = None
    if request.image_base64 is not None:
        visual_request = VisualIntentRequest(
            image_base64=request.image_base64,
            media_type=request.media_type,
            user_message=last_user_message,
            max_budget=budget,
            quantity=quantity,
            merchant_id=request.merchant_id,
        )
        try:
            visual_candidate = get_configured_visual_analyzer()(visual_request)
        except RuntimeError as error:
            visual_error = str(error)

    text_category = detect_category(text)
    visual_category = (
        canonicalize_category(visual_candidate.category)
        if visual_candidate and visual_candidate.confidence >= 0.70
        else None
    )
    category = visual_category or text_category
    brand = (
        visual_candidate.brand
        if visual_candidate and visual_candidate.brand
        else _brand_from_text(text)
    )
    preferences = _features_from_text(text)
    if visual_candidate:
        preferences.extend(
            feature
            for feature in visual_candidate.visible_features
            if feature not in preferences
        )

    intent = ChatIntentSummary(
        category=category,
        brand=brand,
        max_budget=budget,
        quantity=quantity,
        preferences=preferences,
    )

    if category is None:
        reply = (
            "Tell me what you want to buy, such as a smartphone, laptop, "
            "camera, smartwatch, or headphones. You can also drop a product "
            "image here."
        )
        if visual_candidate and visual_candidate.confidence < 0.70:
            reply = (
                "I received the image, but I cannot identify the product "
                "confidently yet. Add the model name or describe the category "
                "so I can search approved catalogs safely."
            )
        if visual_error:
            reply += " The image analyzer was unavailable, so a text description is needed."
        return ProductAssistantChatResponse(
            reply=reply,
            intent=intent,
            visual_candidate=visual_candidate,
            next_action="PROVIDE_PRODUCT_HINT" if request.image_base64 else "PROVIDE_CATEGORY",
        )

    suggestions = _suggest_products(
        category=category,
        text=text,
        visual_candidate=visual_candidate,
        budget=budget,
        quantity=quantity,
        merchant_id=request.merchant_id,
    )

    if budget is None:
        reply = (
            f"I found {len(suggestions)} approved {category} option(s). "
            "These are discovery suggestions only. Tell me your maximum "
            "budget before I prepare a bounded purchase intent."
        )
        next_action = "PROVIDE_BUDGET"
    elif not suggestions:
        reply = (
            f"I could not find an in-stock {category} product within ₹{budget} "
            f"for quantity {quantity}. Increase the maximum budget or try "
            "another category."
        )
        next_action = "PROVIDE_BUDGET"
    else:
        reply = (
            f"I found {len(suggestions)} approved {category} option(s) within "
            f"your maximum of ₹{budget}. Compare the cards, then choose one "
            "to open the separate verification flow. Nothing is authorized "
            "from chat."
        )
        next_action = "CHOOSE_PRODUCT"

    if visual_candidate:
        reply = (
            f"Visual candidate: {visual_candidate.product_name} "
            f"({round(visual_candidate.confidence * 100)}% confidence). "
            + reply
        )
    if visual_error:
        reply += " The local vision model was unavailable; OCR/text fallback was used."

    return ProductAssistantChatResponse(
        reply=reply,
        suggestions=suggestions,
        visual_candidate=visual_candidate,
        intent=intent,
        next_action=next_action,
    )
