"""Turns a free-text shopper message into a clean list of search tokens.

This stage is intentionally dumb: it strips shopping-intent filler words
("I want to buy...") and typo'd verbs so what's left is the product the
user is actually asking about. It does not know about any product,
brand, or category name -- that keeps it generic instead of a growing
pile of per-product special cases.
"""

import re
from dataclasses import dataclass


# Generic filler around a shopping request -- verbs of intent and their
# common misspellings/prepositions, not any particular product. Removing
# these turns "I want to by iphone" into just "iphone" before search runs.
STOPWORDS = {
    "i", "im", "we", "youd", "id",
    "want", "wnat", "wan", "wanna",
    "need", "ned",
    "would", "like", "liek",
    "to", "for", "of", "an", "a", "the",
    "buy", "by", "bui", "buuy",
    "purchase", "purchse", "puchase",
    "get", "gt",
    "show", "shwo", "find", "fnd", "looking", "look", "search",
    "me", "us", "my",
    "please", "pls", "plz",
    "some", "any", "one", "ones",
    "with", "and", "under", "below", "within", "upto", "up",
}

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class NormalizedQuery:
    raw_text: str
    all_tokens: tuple[str, ...]
    """Every alphanumeric token in the message, stopwords included --
    useful for budget/quantity extraction elsewhere."""
    search_tokens: tuple[str, ...]
    """Tokens with shopping-intent filler removed: the part of the
    sentence that actually names a product."""
    joined_bigrams: tuple[str, ...]
    """Adjacent search tokens concatenated (e.g. "i" + "phone" ->
    "iphone"), so a user who splits a brand name across two words still
    matches the catalog's single-word product name."""


def normalize_text(text: str) -> str:
    return " ".join(text.strip().casefold().split())


def tokenize(text: str) -> list[str]:
    return _TOKEN_PATTERN.findall(text.casefold())


def normalize_query(text: str) -> NormalizedQuery:
    all_tokens = tokenize(text)
    search_tokens = [token for token in all_tokens if token not in STOPWORDS and len(token) > 1]

    bigrams = tuple(
        f"{left}{right}"
        for left, right in zip(search_tokens, search_tokens[1:])
    )

    return NormalizedQuery(
        raw_text=text,
        all_tokens=tuple(all_tokens),
        search_tokens=tuple(search_tokens),
        joined_bigrams=bigrams,
    )


# A small, generic controlled vocabulary of spec-sheet feature synonyms --
# not product names or brands, so it stays reusable across every category
# instead of being a pile of per-product special cases.
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

# Generic "<number><unit> [descriptor]" capture -- e.g. "16GB RAM", "48MP
# camera", "512GB storage" -- for spec-sheet numbers that aren't in the
# fixed FEATURE_ALIASES vocabulary above. Matches any product category;
# nothing here names a specific product or brand.
_NUMERIC_FEATURE_PATTERN = re.compile(r"\b(\d+)\s?(gb|tb|mp|mah|inch|ghz)\b")
_NUMERIC_FEATURE_DESCRIPTOR_PATTERN = re.compile(
    r"^\s*(ram|storage|memory|battery|display|screen|camera)"
)


def extract_feature_phrases(text: str) -> list[str]:
    normalized = text.casefold()
    phrases: list[str] = []

    for phrase, feature in FEATURE_ALIASES.items():
        if phrase in normalized and feature not in phrases:
            phrases.append(feature)

    for match in _NUMERIC_FEATURE_PATTERN.finditer(normalized):
        number, unit = match.groups()
        descriptor_match = _NUMERIC_FEATURE_DESCRIPTOR_PATTERN.match(
            normalized[match.end():match.end() + 12]
        )
        phrase = (
            f"{number}{unit.upper()} {descriptor_match.group(1).upper()}"
            if descriptor_match
            else f"{number}{unit.upper()}"
        )
        if phrase not in phrases:
            phrases.append(phrase)

    return phrases
