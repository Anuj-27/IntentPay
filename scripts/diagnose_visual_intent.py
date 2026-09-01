import base64
import binascii
from pathlib import Path
import struct
import sys
import zlib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.schemas.visual_intent import VisualIntentRequest
from backend.app.services.visual_intent_service import get_configured_visual_analyzer


MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def synthetic_png() -> bytes:
    width = 64
    height = 64
    row = b"\x00" + (b"\x2b\x6c\xd4" * width)
    pixels = row * height

    def chunk(kind: bytes, data: bytes) -> bytes:
        payload = kind + data
        return (
            struct.pack(">I", len(data))
            + payload
            + struct.pack(">I", binascii.crc32(payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk("IHDR".encode(), struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk("IDAT".encode(), zlib.compress(pixels))
        + chunk("IEND".encode(), b"")
    )


if len(sys.argv) != 2:
    raise SystemExit("Usage: diagnose_visual_intent.py <image-path|--synthetic>")

if sys.argv[1] == "--synthetic":
    image_bytes = synthetic_png()
    media_type = "image/png"
else:
    image_path = Path(sys.argv[1])
    media_type = MEDIA_TYPES.get(image_path.suffix.casefold())
    if media_type is None:
        raise SystemExit("Use a PNG, JPEG, or WebP image.")
    image_bytes = image_path.read_bytes()

request = VisualIntentRequest(
    image_base64=base64.b64encode(image_bytes).decode("ascii"),
    media_type=media_type,
    user_message="Diagnose visual product extraction.",
)

try:
    candidate = get_configured_visual_analyzer()(request)
except Exception as error:
    print(f"Error type: {type(error).__name__}")
    print(f"Status: {getattr(error, 'status_code', None)}")
    print(f"Code: {getattr(error, 'code', None)}")
    print(f"Message: {str(error)[:1500]}")
else:
    print(candidate.model_dump_json(indent=2))
