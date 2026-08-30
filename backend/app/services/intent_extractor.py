import re

from backend.app.schemas.intent import IntentMandate


AMOUNT_PATTERN = r"(?P<amount>\d{1,3}(?:,\d{2,3})+|\d{3,7})"

BUDGET_PATTERNS = (
    re.compile(
        rf"(?:under|below|up\s+to|upto|within|not\s+more\s+than|"
        rf"max(?:imum)?(?:\s+budget)?|budget(?:\s+of|\s+is)?)"
        rf"\s*(?:₹|rs\.?|inr)?\s*{AMOUNT_PATTERN}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:₹|rs\.?|inr)\s*{AMOUNT_PATTERN}",
        re.IGNORECASE,
    ),
)


def extract_budget_from_text(message: str) -> int:
    for pattern in BUDGET_PATTERNS:
        match = pattern.search(message)
        if match:
            return int(match.group("amount").replace(",", ""))

    raise ValueError("Could not determine maximum budget.")


def extract_quantity_from_text(message: str) -> int:
    text = message.casefold()
    patterns = (
        re.compile(r"(?:buy|purchase|get(?:\s+me)?|need|want)\s+(\d{1,3})\b"),
        re.compile(
            r"\b(\d{1,3})\s+(?:(?:sony|jbl)\s+)?"
            r"(?:wireless\s+)?headphones?\b"
        ),
    )

    for pattern in patterns:
        match = pattern.search(text)
        if match:
            quantity = int(match.group(1))
            if quantity < 1:
                raise ValueError("Quantity must be at least 1.")
            return quantity

    return 1


def subscription_is_explicitly_allowed(message: str) -> bool:
    text = message.casefold()
    return any(
        phrase in text
        for phrase in (
            "subscription is okay",
            "subscription is ok",
            "allow subscription",
            "subscription allowed",
            "subscriptions are okay",
        )
    )


def autonomous_selection_is_explicitly_allowed(message: str) -> bool:
    text = message.casefold()
    return any(
        phrase in text
        for phrase in (
            "choose for me",
            "you decide",
            "automatically choose",
            "pick for me",
        )
    )


def _preference_level(text: str, value: str) -> str:
    soft_phrases = (
        f"prefer {value}",
        f"preferably {value}",
        f"{value} preferred",
        f"{value} if possible",
    )
    return "PREFERRED" if any(phrase in text for phrase in soft_phrases) else "EXACT"


def extract_intent_from_text(message: str) -> IntentMandate:
    text = message.casefold()

    if "headphone" in text:
        product_category = "headphones"
    else:
        raise ValueError("Could not determine product category.")

    max_budget = extract_budget_from_text(message)
    quantity = extract_quantity_from_text(message)

    known_brands = {
        "sony": "Sony",
        "jbl": "JBL",
    }
    brand = next(
        (canonical for token, canonical in known_brands.items() if token in text),
        None,
    )
    brand_preference = (
        _preference_level(text, brand.casefold())
        if brand is not None
        else "ANY"
    )

    known_colors = ("black", "blue", "white", "red")
    color = next((known_color for known_color in known_colors if known_color in text), None)
    color_preference = (
        _preference_level(text, color)
        if color is not None
        else "ANY"
    )

    feature_map = {
        "anc": "ANC",
        "noise cancellation": "ANC",
        "noise cancelling": "ANC",
        "fast charging": "fast charging",
        "battery": "battery",
        "microphone": "microphone",
        "mic": "microphone",
    }
    preferred_features = []
    for phrase, feature in feature_map.items():
        if phrase in text and feature not in preferred_features:
            preferred_features.append(feature)

    priority = "BEST_VALUE"
    if "cheapest" in text or "lowest price" in text:
        priority = "CHEAPEST"
    elif "best rated" in text or "highest rated" in text:
        priority = "HIGHEST_RATING"

    return IntentMandate(
        product_category=product_category,
        max_budget=max_budget,
        quantity=quantity,
        color=color,
        color_preference=color_preference,
        brand=brand,
        brand_preference=brand_preference,
        subscription_allowed=subscription_is_explicitly_allowed(message),
        autonomous_selection_allowed=(
            autonomous_selection_is_explicitly_allowed(message)
        ),
        priority=priority,
        preferred_features=preferred_features,
    )
