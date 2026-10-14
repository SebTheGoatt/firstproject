"""Crew photos are stored as small data: URLs (resized in the browser before
upload) and served back as real image responses."""

import base64
import binascii
import re

MAX_PHOTO_BYTES = 700_000          # after decoding; the crew app resizes to ~1600px JPEG first
ALLOWED_TYPES = ("image/jpeg", "image/png", "image/webp")
DATA_URL = re.compile(r"^data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=\s]+)$")
MAGIC = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}


class MediaError(ValueError):
    pass


def parse_photo(data_url: str) -> tuple[str, bytes]:
    m = DATA_URL.match(data_url or "")
    if not m:
        raise MediaError("Photos must be JPEG, PNG or WebP images.")
    content_type = m.group(1)
    try:
        raw = base64.b64decode(m.group(2), validate=False)
    except (binascii.Error, ValueError) as exc:
        raise MediaError("That photo couldn't be read.") from exc
    if len(raw) > MAX_PHOTO_BYTES:
        raise MediaError("That photo is too large. Please try a smaller one.")
    if not raw.startswith(MAGIC[content_type]):
        raise MediaError("That file isn't a valid image.")
    return content_type, raw


def normalize_photo(data_url: str) -> str:
    """Validate and return a canonical data URL for storage."""
    content_type, raw = parse_photo(data_url)
    return f"data:{content_type};base64,{base64.b64encode(raw).decode()}"
