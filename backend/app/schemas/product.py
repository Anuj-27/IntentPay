import re
from typing import TypeAlias
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ProductAttributeValue: TypeAlias = str | int | float | bool

ALLOWED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")

# A merchant uploading a photo from their device (rather than pasting a
# hosted URL) is sent to the backend as a base64 data URI -- there is no
# file-storage service in this project to upload to instead. ~6.7M base64
# characters covers a ~5MB image (the same client-side cap already used
# for chat's visual-search image attachments).
MAX_IMAGE_URL_LENGTH = 7_000_000
DATA_URI_PATTERN = re.compile(
    r"^data:image/(jpeg|jpg|png|webp);base64,[A-Za-z0-9+/]+=*$"
)


class ProductImage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=MAX_IMAGE_URL_LENGTH)
    is_primary: bool = False

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        cleaned = value.strip()

        if cleaned.startswith("data:"):
            if not DATA_URI_PATTERN.match(cleaned):
                raise ValueError(
                    "Uploaded product images must be a JPEG, PNG, or WebP file "
                    "encoded as a base64 data URL."
                )
            return cleaned

        parsed = urlsplit(cleaned)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(
                "Product image URLs must be absolute http(s) URLs, or an "
                "uploaded image file."
            )

        path = parsed.path.casefold()
        if "." in path.rsplit("/", 1)[-1]:
            # Only enforce an extension allow-list when the URL actually
            # has one -- many real CDN/image-hosting URLs (Unsplash,
            # signed S3 links, etc.) have none, and rejecting those would
            # make the validator worse than useless for a live catalog.
            if not path.endswith(ALLOWED_IMAGE_EXTENSIONS):
                raise ValueError(
                    "Product image URLs must end in .jpg, .jpeg, .png, or .webp "
                    "when a file extension is present."
                )
        return cleaned


def _normalize_images(
    images: list | None,
    legacy_image_url: str | None,
) -> list[dict]:
    """Builds the canonical `images` list from whichever of `images` /
    legacy `image_url` the caller supplied, de-duplicating URLs and
    guaranteeing exactly one `is_primary` entry (the first one) when the
    list is non-empty. Blank entries are dropped rather than raising, so a
    merchant leaving an image row empty never breaks product creation."""

    raw_entries: list[dict] = []
    if images:
        for entry in images:
            if isinstance(entry, str):
                raw_entries.append({"url": entry})
            elif isinstance(entry, dict):
                raw_entries.append(entry)
            else:
                raw_entries.append({"url": entry.url, "is_primary": entry.is_primary})
    elif legacy_image_url:
        raw_entries.append({"url": legacy_image_url, "is_primary": True})

    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for entry in raw_entries:
        url = str(entry.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append({"url": url, "is_primary": bool(entry.get("is_primary"))})

    if deduped and not any(entry["is_primary"] for entry in deduped):
        deduped[0]["is_primary"] = True
    elif deduped:
        # Exactly one primary: keep the first flagged entry, demote the rest.
        primary_seen = False
        for entry in deduped:
            if entry["is_primary"] and not primary_seen:
                primary_seen = True
            elif entry["is_primary"]:
                entry["is_primary"] = False

    return deduped


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)

    price: int = Field(gt=0)

    brand: str = Field(min_length=1, max_length=100)
    color: str | None = None

    model: str | None = Field(default=None, max_length=100)
    variant: str | None = Field(default=None, max_length=100)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")

    # `image_url` is kept for backward compatibility with existing rows
    # and API callers; `images` is the source of truth going forward and
    # is always populated (from `image_url` when only the legacy field is
    # given). The first entry, or whichever has `is_primary=True`, is the
    # product's primary image.
    image_url: str | None = Field(default=None, max_length=MAX_IMAGE_URL_LENGTH)
    images: list[ProductImage] = Field(default_factory=list, max_length=10)
    product_url: str | None = Field(default=None, max_length=2048)

    rating: float = Field(ge=0, le=5)

    features: list[str] = Field(default_factory=list)
    attributes: dict[str, ProductAttributeValue] = Field(default_factory=dict)

    in_stock: bool = True

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value):
        if isinstance(value, str):
            return value.strip().casefold()
        return value

    @field_validator("model", "variant", mode="before")
    @classmethod
    def strip_optional_text(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("attributes", mode="before")
    @classmethod
    def normalize_attribute_keys(cls, value):
        if value is None:
            return {}
        return {
            str(key).strip().casefold(): attribute_value
            for key, attribute_value in value.items()
            if str(key).strip()
        }

    @model_validator(mode="before")
    @classmethod
    def reconcile_images(cls, data):
        if not isinstance(data, dict):
            return data

        data = dict(data)
        data["images"] = _normalize_images(data.get("images"), data.get("image_url"))
        return data

    @model_validator(mode="after")
    def sync_legacy_image_url(self):
        if self.images:
            primary = next((image for image in self.images if image.is_primary), self.images[0])
            if self.image_url != primary.url:
                self.image_url = primary.url
        elif self.image_url:
            self.images = [ProductImage(url=self.image_url, is_primary=True)]
        return self

    @property
    def primary_image_url(self) -> str | None:
        if self.images:
            primary = next((image for image in self.images if image.is_primary), self.images[0])
            return primary.url
        return self.image_url
