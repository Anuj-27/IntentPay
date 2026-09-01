from dataclasses import dataclass
import re


@dataclass(frozen=True)
class CategoryDefinition:
    category_id: str
    display_name: str
    aliases: tuple[str, ...]
    common_attributes: tuple[str, ...]


CATEGORIES = (
    CategoryDefinition(
        category_id="headphones",
        display_name="Headphones",
        aliases=("headphone", "headphones", "earphone", "earphones", "headset"),
        common_attributes=("connectivity", "battery_hours", "noise_cancellation"),
    ),
    CategoryDefinition(
        category_id="smartphones",
        display_name="Smartphones",
        aliases=("phone", "phones", "smartphone", "smartphones", "mobile", "mobiles"),
        common_attributes=("ram_gb", "storage_gb", "screen_size_inches"),
    ),
    CategoryDefinition(
        category_id="laptops",
        display_name="Laptops",
        aliases=("laptop", "laptops", "notebook", "notebooks"),
        common_attributes=("processor", "ram_gb", "storage_gb"),
    ),
    CategoryDefinition(
        category_id="smartwatches",
        display_name="Smartwatches",
        aliases=(
            "smartwatch",
            "smartwatches",
            "smart watch",
            "smart watches",
            "fitness watch",
        ),
        common_attributes=("display", "battery_days", "gps"),
    ),
    CategoryDefinition(
        category_id="cameras",
        display_name="Cameras",
        aliases=("camera", "cameras", "dslr", "mirrorless", "mirrorless camera"),
        common_attributes=("sensor", "megapixels", "lens_mount"),
    ),
)


CATEGORIES_BY_ID = {
    category.category_id: category
    for category in CATEGORIES
}


def canonicalize_category(value: str) -> str | None:
    normalized = " ".join(value.strip().casefold().split())
    for category in CATEGORIES:
        if normalized == category.category_id or normalized in category.aliases:
            return category.category_id
    return None


def detect_category(text: str) -> str | None:
    normalized = " ".join(text.casefold().split())
    matches: list[tuple[int, str]] = []

    for category in CATEGORIES:
        for alias in category.aliases:
            if re.search(
                rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])",
                normalized,
            ):
                matches.append((len(alias), category.category_id))

    if not matches:
        return None

    matches.sort(reverse=True)
    return matches[0][1]
