"""Walmart.com online sourcing: clearance / deals / rollback listing pages -> product pages.

Patterns follow scraper-bank/Walmart.com-Scrapers (Playwright + stealth, a fresh browser context
per page behind a residential proxy, images/fonts blocked, __NEXT_DATA__ first, DOM fallback).

Guardrail: an item is kept only when Walmart.com is the seller. Third-party marketplace items are
dropped on the listing tile when it names the seller, and always re-checked on the product page.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .config import USER_AGENTS, WALMART_ONLY_FACET, Settings
from .models import CaptchaError, ListingTile, WalmartItem
from .proxies import ProxyPool

log = logging.getLogger("oa_scout.walmart")

BASE = "https://www.walmart.com"
WALMART_SELLERS = {"walmart.com", "walmart"}
_NEXT_DATA = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_PRICE = re.compile(r"(\d[\d,]*\.?\d{0,2})")
_ITEM_ID = re.compile(r"/ip/(?:[^/?#]+/)?(\d{6,14})")
_CAPTCHA_MARKERS = ("robot or human", "px-captcha", "press &amp; hold", "press & hold",
                    "verify your identity", "/blocked?")


# ---------------------------------------------------------------------------
# Parsing helpers (pure, unit-tested)
# ---------------------------------------------------------------------------
def walk(obj: Any) -> Iterator[dict]:
    """Every dict inside a JSON tree, top-down, in document order."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            yield cur
            stack.extend(reversed(list(cur.values())))
        elif isinstance(cur, list):
            stack.extend(reversed(cur))


def extract_next_data(html: str) -> dict | None:
    m = _NEXT_DATA.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def parse_price(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, str):
        m = _PRICE.search(value.replace(",", ""))
        if m:
            try:
                price = float(m.group(1))
                return price if price > 0 else None
            except ValueError:
                return None
    return None


def normalize_upc(raw: Any) -> str:
    """Digits only; a 13-digit EAN with a leading 0 becomes the 12-digit UPC-A Amazon indexes."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 14 and digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 13 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) in (8, 12, 13) else ""


def is_walmart_seller(name: str) -> bool:
    return name.strip().lower() in WALMART_SELLERS


def looks_like_captcha(html: str, url: str = "") -> bool:
    head = html[:20000].lower()
    return "/blocked" in url or any(marker in head for marker in _CAPTCHA_MARKERS)


def _price_from_price_info(info: Any) -> float | None:
    if not isinstance(info, dict):
        return None
    current = info.get("currentPrice")
    if isinstance(current, dict):
        price = parse_price(current.get("price")) or parse_price(current.get("priceString"))
        if price:
            return price
    return parse_price(info.get("linePrice")) or parse_price(info.get("itemPrice"))


def _abs(url: str) -> str:
    return urljoin(BASE, url.split("?")[0]) if url else ""


def parse_listing_json(next_data: dict) -> list[ListingTile]:
    tiles: dict[str, ListingTile] = {}
    for d in walk(next_data):
        item_id = d.get("usItemId")
        name = d.get("name")
        if not item_id or not isinstance(name, str):
            continue
        if d.get("__typename") not in (None, "Product"):
            continue
        if "canonicalUrl" not in d and "priceInfo" not in d:
            continue  # breadcrumbs, ads and other look-alikes
        item_id = str(item_id)
        if item_id in tiles:
            continue
        url = _abs(d.get("canonicalUrl") or f"/ip/{item_id}")
        price = _price_from_price_info(d.get("priceInfo")) or parse_price(d.get("price"))
        tiles[item_id] = ListingTile(item_id, name.strip(), url, price, str(d.get("sellerName") or ""))
    return list(tiles.values())


def parse_listing_dom(html: str) -> list[ListingTile]:
    soup = BeautifulSoup(html, "html.parser")
    tiles: dict[str, ListingTile] = {}
    for tile in soup.select("[data-item-id]"):
        link = tile.select_one("a[href*='/ip/']")
        if link is None:
            continue
        href = link.get("href", "")
        m = _ITEM_ID.search(href)
        item_id = (tile.get("data-item-id") or (m.group(1) if m else "")).strip()
        if not item_id or item_id in tiles:
            continue
        title_el = tile.select_one("[data-automation-id='product-title']") or link
        price_el = tile.select_one("[data-automation-id='product-price']")
        price = None
        if price_el is not None:
            text = price_el.get_text(" ", strip=True)
            m = re.search(r"current price\s*\$?\s*(\d[\d,]*\.?\d*)", text, re.I)
            price = parse_price(m.group(1)) if m else parse_price(text)
        tiles[item_id] = ListingTile(item_id, title_el.get_text(" ", strip=True), _abs(href), price, "")
    return list(tiles.values())


def parse_listing(html: str) -> list[ListingTile]:
    data = extract_next_data(html)
    tiles = parse_listing_json(data) if data else []
    return tiles or parse_listing_dom(html)


def _find_product(next_data: dict) -> dict | None:
    initial = next_data.get("props", {}).get("pageProps", {}).get("initialData", {})
    for candidate in (initial.get("data", {}).get("product"), initial.get("product")):
        if isinstance(candidate, dict) and candidate.get("usItemId"):
            return candidate
    for d in walk(next_data):
        if d.get("usItemId") and ("upc" in d or "sellerName" in d) and "name" in d:
            return d
    return None


def _json_ld(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        out.extend(d for d in (data if isinstance(data, list) else [data]) if isinstance(d, dict))
    return out


def parse_product(html: str, url: str, tile: ListingTile | None = None) -> tuple[WalmartItem | None, str]:
    """Returns (item, "") or (None, reason it was skipped)."""
    soup = BeautifulSoup(html, "html.parser")
    data = extract_next_data(html)
    product = _find_product(data) if data else None
    ld = _json_ld(soup)

    title = upc = seller = ""
    price: float | None = None
    item_id = tile.item_id if tile else ""
    in_stock = True

    if product:
        title = str(product.get("name") or "")
        upc = normalize_upc(product.get("upc"))
        seller = str(product.get("sellerDisplayName") or product.get("sellerName") or "")
        price = _price_from_price_info(product.get("priceInfo"))
        item_id = str(product.get("usItemId") or item_id)
        status = str(product.get("availabilityStatus") or "").upper()
        in_stock = status not in ("OUT_OF_STOCK", "NOT_AVAILABLE")

    # JSON-LD and DOM fallbacks for anything still missing
    for d in ld:
        if d.get("@type") not in ("Product", "ProductGroup"):
            continue
        title = title or str(d.get("name") or "")
        if not upc:
            for key in ("gtin12", "gtin13", "gtin", "gtin14", "gtin8"):
                upc = normalize_upc(d.get(key))
                if upc:
                    break
        if price is None:
            offers = d.get("offers")
            offers = offers[0] if isinstance(offers, list) and offers else offers
            if isinstance(offers, dict):
                price = parse_price(offers.get("price"))
                seller = seller or str((offers.get("seller") or {}).get("name") or "")

    if not title:
        h1 = soup.select_one("h1#main-title") or soup.select_one("h1[itemprop='name']")
        title = h1.get_text(" ", strip=True) if h1 else (tile.title if tile else "")
    if price is None:
        el = soup.select_one("[itemprop='price']") or soup.select_one("[data-fs-element='price']")
        if el is not None:
            price = parse_price(el.get("content") or el.get_text(" ", strip=True))
    if price is None and tile:
        price = tile.price

    seller_info = soup.select_one("[data-testid='product-seller-info']")
    seller_text = seller_info.get_text(" ", strip=True).lower() if seller_info else ""
    sold_by_walmart = is_walmart_seller(seller) if seller else "sold and shipped by walmart.com" in seller_text
    if seller_text and "sold and shipped by" in seller_text and "walmart.com" not in seller_text:
        sold_by_walmart = False   # the page itself names another seller

    if not sold_by_walmart:
        return None, f"third-party seller ({seller or 'unknown'})"
    if not in_stock:
        return None, "out of stock online"
    if not upc:
        return None, "no UPC"
    if not price:
        return None, "no price"
    return WalmartItem(item_id, title.strip(), round(price, 2), url, upc, seller or "Walmart.com"), ""


def page_url(start_url: str, page: int, walmart_only: bool) -> str:
    parts = urlsplit(start_url)
    query = dict(parse_qsl(parts.query))
    if page > 1:
        query["page"] = str(page)
    if walmart_only:
        query.setdefault("facet", WALMART_ONLY_FACET)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, safe=":"), ""))


# ---------------------------------------------------------------------------
# Stealth: playwright-stealth 2.x (Stealth class) or 1.x (stealth_async)
# ---------------------------------------------------------------------------
try:
    from playwright_stealth import Stealth  # type: ignore[attr-defined]

    _stealth = Stealth()

    async def apply_stealth(context, page) -> None:  # noqa: ARG001
        await _stealth.apply_stealth_async(context)
except ImportError:  # pragma: no cover - depends on installed version
    try:
        from playwright_stealth import stealth_async  # type: ignore[attr-defined]

        async def apply_stealth(context, page) -> None:  # noqa: ARG001
            await stealth_async(page)
    except ImportError:
        async def apply_stealth(context, page) -> None:  # noqa: ARG001
            log.warning("playwright-stealth is not installed; running without it")


# ---------------------------------------------------------------------------
# Browser crawler
# ---------------------------------------------------------------------------
class WalmartCrawler:
    def __init__(self, settings: Settings, proxies: ProxyPool):
        self.s = settings
        self.proxies = proxies
        self._pw = None
        self._browser = None
        self._sem = asyncio.Semaphore(settings.walmart_concurrency)

    async def __aenter__(self) -> "WalmartCrawler":
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        launch: dict[str, Any] = {
            "headless": self.s.headless,
            "args": ["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
        }
        if self.s.chromium_path:
            launch["executable_path"] = self.s.chromium_path
        if self.proxies.enabled:
            # Each context brings its own proxy; this placeholder satisfies older Chromium builds.
            launch["proxy"] = {"server": "http://per-context"}
        self._browser = await self._pw.chromium.launch(**launch)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()

    async def _fetch_once(self, url: str, wait_for_next_data: bool) -> str:
        assert self._browser is not None
        proxy = self.proxies.next()
        context = await self._browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": random.choice((1366, 1440, 1536, 1920)), "height": random.choice((768, 900, 1080))},
            locale="en-US",
            timezone_id="America/Chicago",
            proxy=proxy.for_playwright() if proxy else None,
        )
        try:
            page = await context.new_page()
            await apply_stealth(context, page)

            async def block_heavy(route):
                if route.request.resource_type in ("image", "media", "font"):
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/*", block_heavy)
            response = await page.goto(url, wait_until="domcontentloaded", timeout=self.s.page_timeout_ms)
            if wait_for_next_data:
                try:
                    await page.wait_for_selector("script#__NEXT_DATA__", state="attached", timeout=10_000)
                except Exception:  # noqa: BLE001 - fall back to whatever rendered
                    pass
            html = await page.content()
            if looks_like_captcha(html, page.url):
                raise CaptchaError(f"captcha at {url} (proxy {proxy.masked() if proxy else 'direct'})")
            if response is not None and response.status >= 400:
                raise RuntimeError(f"HTTP {response.status} at {url}")
            return html
        finally:
            await context.close()

    async def fetch(self, url: str, wait_for_next_data: bool = True) -> str:
        """Fetch with retries; each retry gets a new context and a new proxy IP."""
        last: Exception | None = None
        for attempt in range(self.s.retries + 1):
            async with self._sem:
                await asyncio.sleep(random.uniform(*self.s.walmart_delay_s))
                try:
                    return await self._fetch_once(url, wait_for_next_data)
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    log.debug("attempt %d failed for %s: %s", attempt + 1, url, exc)
        assert last is not None
        raise last

    async def listing(self, start_url: str, page: int) -> list[ListingTile]:
        url = page_url(start_url, page, self.s.walmart_only_facet)
        tiles = parse_listing(await self.fetch(url))
        log.info("listing %s -> %d tiles", url, len(tiles))
        return tiles

    async def product(self, tile: ListingTile) -> tuple[WalmartItem | None, str]:
        html = await self.fetch(tile.url)
        return parse_product(html, tile.url, tile)
