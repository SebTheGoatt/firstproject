"""Photos never keep camera metadata (GPS above all): a work photo must not reveal where a customer lives."""

import base64
import io

from PIL import Image

from app.media import normalize_photo

GPS = {34853: {1: "N", 2: (30.0, 4.0, 0.0), 3: "W", 4: (95.0, 25.0, 0.0)}}   # Spring, TX


def data_url(fmt: str, mime: str) -> str:
    img, buf = Image.new("RGB", (32, 32), (46, 125, 79)), io.BytesIO()
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    exif[0x8825] = GPS[34853]
    if fmt == "PNG":
        from PIL.PngImagePlugin import PngInfo
        info = PngInfo(); info.add_text("Comment", "123 Example St")
        img.save(buf, fmt, exif=exif, pnginfo=info)
    else:
        img.save(buf, fmt, exif=exif)
    return f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode()}"


def decoded(url: str) -> bytes:
    return base64.b64decode(url.split(",", 1)[1])


def test_jpeg_png_and_webp_lose_their_metadata_and_still_open():
    for fmt, mime in (("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")):
        before = decoded(data_url(fmt, mime))
        assert b"PhoneMaker" in before, fmt
        after = decoded(normalize_photo(data_url(fmt, mime)))
        assert b"PhoneMaker" not in after and b"Example St" not in after, fmt
        img = Image.open(io.BytesIO(after)); img.load()
        assert img.size == (32, 32) and not img.getexif(), fmt
        assert img.getpixel((5, 5))[1] > 100, fmt          # still the green test image


def test_photos_without_metadata_are_unchanged():
    buf = io.BytesIO(); Image.new("RGB", (8, 8)).save(buf, "PNG")
    url = f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
    assert normalize_photo(url) == url
