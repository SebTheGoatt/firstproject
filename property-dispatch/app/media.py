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


def _strip_jpeg(raw: bytes) -> bytes:
    """Drop APP1 (EXIF/XMP, where phones put GPS), APP13 (IPTC) and comments; keep JFIF, ICC color and image data."""
    out, i = bytearray(raw[:2]), 2
    while i + 4 <= len(raw) and raw[i] == 0xFF:
        marker = raw[i + 1]
        if marker == 0xDA:                                   # start of scan: the rest is image data
            return bytes(out + raw[i:])
        size = int.from_bytes(raw[i + 2:i + 4], "big")
        if size < 2 or i + 2 + size > len(raw):
            break
        if marker not in (0xE1, 0xED, 0xFE):
            out += raw[i:i + 2 + size]
        i += 2 + size
    raise ValueError("unexpected JPEG layout")


def _strip_png(raw: bytes) -> bytes:
    """Drop the EXIF, text and time chunks."""
    out, i = bytearray(raw[:8]), 8
    while i + 12 <= len(raw):
        size = int.from_bytes(raw[i:i + 4], "big")
        kind, end = raw[i + 4:i + 8], i + 12 + size
        if end > len(raw):
            break
        if kind not in (b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"tIME"):
            out += raw[i:end]
        i = end
        if kind == b"IEND":
            return bytes(out)
    raise ValueError("unexpected PNG layout")


def _strip_webp(raw: bytes) -> bytes:
    """Drop the EXIF and XMP chunks and clear their flags in the VP8X header."""
    if raw[8:12] != b"WEBP":
        raise ValueError("not WebP")
    out, i = bytearray(), 12
    while i + 8 <= len(raw):
        kind, size = raw[i:i + 4], int.from_bytes(raw[i + 4:i + 8], "little")
        end = i + 8 + size + (size & 1)
        if i + 8 + size > len(raw):
            raise ValueError("unexpected WebP layout")
        chunk = bytearray(raw[i:min(end, len(raw))])
        if kind == b"VP8X" and size >= 1:
            chunk[8] &= ~0x0C & 0xFF
        if kind not in (b"EXIF", b"XMP "):
            out += chunk
        i = end
    return b"RIFF" + (len(out) + 4).to_bytes(4, "little") + b"WEBP" + bytes(out)


def strip_metadata(content_type: str, raw: bytes) -> bytes:
    """Remove camera metadata, above all GPS, so a photo never reveals where a customer lives. The crew app
    already re-encodes photos, which drops it; this is the server-side guarantee. A file we can't walk is kept as is."""
    strip = {"image/jpeg": _strip_jpeg, "image/png": _strip_png, "image/webp": _strip_webp}[content_type]
    try:
        return strip(raw)
    except (ValueError, IndexError):
        return raw


def normalize_photo(data_url: str) -> str:
    """Validate and return a canonical data URL for storage, with camera metadata removed."""
    content_type, raw = parse_photo(data_url)
    raw = strip_metadata(content_type, raw)
    return f"data:{content_type};base64,{base64.b64encode(raw).decode()}"
