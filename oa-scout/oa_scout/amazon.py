"""Amazon data resolver: UPC -> ASIN, Buy Box price, Prime status, category Sales Rank,
and the number of sellers (all offers and FBA offers). Async HTTP through the rotating proxy pool.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re

from dataclasses import dataclass

import aiohttp
from bs4 import BeautifulSoup

from .config import USER_AGENTS, Settings
from .models import AmazonListing, CaptchaError
from .proxies import ProxyPool

log = logging.getLogger("oa_scout.amazon")

BASE = "https://www.amazon.com"
_CAPTCHA_MARKERS = ("validatecaptcha", "type the characters you see", "enter the characters you see",
                    "to discuss automated access to amazon data")
_RANK = re.compile(r"#\s*([\d,]+)\s+in\s+(.+?)\s*(?:\(|#|$)")
_PRICE = re.compile(r"\$\s*(\d[\d,]*\.\d{2})")
_BUYBOX_PRICE_SELECTORS = (
    "#corePrice_feature_div .a-price .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
    "#apex_desktop .a-price .a-offscreen",
    "#price_inside_buybox",
    "#newBuyBoxPrice",
    "#priceblock_ourprice",
    "#priceblock_dealprice",
)


# ---------------------------------------------------------------------------
# Parsing helpers (pure, unit-tested)
# ---------------------------------------------------------------------------
def looks_like_captcha(html: str) -> bool:
    head = html[:30000].lower()
    return any(marker in head for marker in _CAPTCHA_MARKERS)


def _money(text: str | None) -> float | None:
    if not text:
        return None
    m = _PRICE.search(text.replace("\xa0", " "))
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    return value if value > 0 else None


def parse_search(html: str) -> list[tuple[str, str]]:
    """Organic (non-sponsored) results as (asin, title), in page order."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []
    for result in soup.select("div[data-component-type='s-search-result'][data-asin]"):
        asin = (result.get("data-asin") or "").strip()
        if not asin or "AdHolder" in (result.get("class") or []):
            continue
        if result.select_one(".puis-sponsored-label-text, .s-sponsored-label-text"):
            continue
        # The title block holds brand and product name in separate h2s; join them.
        parts = [h.get_text(" ", strip=True) for h in result.select("[data-cy='title-recipe'] h2, h2")]
        title = " ".join(dict.fromkeys(p for p in parts if p))
        out.append((asin, title))
    return out


def parse_sales_rank(soup: BeautifulSoup) -> tuple[int | None, str]:
    """Top-level category rank: 'Best Sellers Rank: #4,512 in Kitchen & Dining (See Top 100...)'."""
    blocks = soup.select("#detailBulletsWrapper_feature_div, #productDetails_detailBullets_sections1, "
                         "#productDetails_db_sections, #prodDetails, #SalesRank")
    for block in blocks:
        text = " ".join(block.get_text(" ", strip=True).split())
        idx = text.find("Best Sellers Rank")
        if idx < 0:
            continue
        m = _RANK.search(text[idx:])
        if m:
            return int(m.group(1).replace(",", "")), m.group(2).strip(" :")
    return None, ""


def parse_product(html: str, asin: str) -> AmazonListing:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("#productTitle")
    title = title_el.get_text(" ", strip=True) if title_el else ""

    availability = soup.select_one("#availability")
    avail_text = availability.get_text(" ", strip=True).lower() if availability else ""
    unavailable = bool(soup.select_one("#outOfStock")) or "currently unavailable" in avail_text \
        or "out of stock" in avail_text
    price = None
    if not unavailable:
        for sel in _BUYBOX_PRICE_SELECTORS:
            el = soup.select_one(sel)
            if el is not None:
                price = _money(el.get_text(" ", strip=True))
                if price:
                    break
        if price is None:
            hidden = soup.select_one("input#attach-base-product-price")
            if hidden is not None:
                try:
                    price = float(hidden.get("value") or 0) or None
                except ValueError:
                    price = None

    buybox = soup.select_one("#desktop_buybox") or soup.select_one("#buybox") or soup
    box_text = " ".join(buybox.get_text(" ", strip=True).split()).lower()
    merchant = soup.select_one("#merchantInfoFeature_feature_div")
    merchant_text = " ".join(merchant.get_text(" ", strip=True).split()).lower() if merchant else ""
    ships_from_amazon = bool(re.search(r"ships from:?\s*amazon", box_text)) or \
        merchant_text.startswith("shipper / seller amazon") or "shipper amazon" in merchant_text
    visible_prime = any("aok-hidden" not in (i.get("class") or [])
                        for i in buybox.select("i.a-icon-prime, #prime-badge"))
    is_prime = price is not None and (visible_prime or ships_from_amazon)
    amazon_sells = bool(re.search(r"sold by:?\s*amazon\.com", box_text)) or \
        merchant_text.endswith("seller amazon.com") or "shipper / seller amazon.com amazon.com" in merchant_text

    rank, category = parse_sales_rank(soup)
    return AmazonListing(asin, title, price, is_prime, rank, category, None, None, amazon_sells)


@dataclass
class OfferPage:
    total: int | None           # every offer on the listing (the pinned Buy Box offer included)
    on_page: int                # offers read from this page
    fba_new: int                # New-condition offers that ship from Amazon (FBA + Amazon itself)
    amazon_sells: bool          # Amazon.com is one of the sellers


def parse_offers(html: str) -> OfferPage:
    """All-offers-display page. Used / renewed offers don't compete with a New item, so they are
    left out of the FBA count."""
    soup = BeautifulSoup(html, "html.parser")
    pinned = soup.select("#aod-pinned-offer")
    others = soup.select("#aod-offer")
    total = None
    total_el = soup.select_one("#aod-total-offer-count")
    if total_el is not None:
        try:
            total = int(total_el.get("value") or "") + len(pinned)  # the count excludes the pinned offer
        except ValueError:
            total = None
    fba = 0
    amazon_sells = False
    for offer in pinned + others:
        def text(sel: str) -> str:
            el = offer.select_one(sel)
            return " ".join(el.get_text(" ", strip=True).split()).lower() if el else ""
        condition = text("#aod-offer-heading")
        ships, sold = text("#aod-offer-shipsFrom"), text("#aod-offer-soldBy")
        if "sold by amazon.com" in sold:
            amazon_sells = True
        if (not condition or condition.startswith("new")) and "ships from amazon" in ships:
            fba += 1
    return OfferPage(total, len(pinned) + len(others), fba, amazon_sells)


# ---------------------------------------------------------------------------
# HTTP resolver
# ---------------------------------------------------------------------------
class AmazonResolver:
    def __init__(self, settings: Settings, proxies: ProxyPool):
        self.s = settings
        self.proxies = proxies
        self._session: aiohttp.ClientSession | None = None
        self._sem = asyncio.Semaphore(settings.amazon_concurrency)

    async def __aenter__(self) -> "AmazonResolver":
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.s.http_timeout_s),
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate",
                "Upgrade-Insecure-Requests": "1",
            },
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._session is not None:
            await self._session.close()

    async def _get_once(self, url: str, referer: str = "") -> str:
        assert self._session is not None
        proxy = self.proxies.next()
        async with self._sem:
            await asyncio.sleep(random.uniform(*self.s.amazon_delay_s))
            async with self._session.get(
                url,
                proxy=proxy.for_http() if proxy else None,
                headers={"User-Agent": random.choice(USER_AGENTS), **({"Referer": referer} if referer else {})},
            ) as resp:
                if resp.status == 404:
                    return ""
                text = await resp.text(errors="replace")
                if resp.status in (429, 503) or looks_like_captcha(text):
                    raise CaptchaError(f"bot check at {url} (HTTP {resp.status}, "
                                       f"proxy {proxy.masked() if proxy else 'direct'})")
                resp.raise_for_status()
                return text

    async def get(self, url: str, referer: str = "") -> str:
        last: Exception | None = None
        for attempt in range(self.s.retries + 1):
            try:
                return await self._get_once(url, referer)
            except (CaptchaError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last = exc
                log.debug("attempt %d failed for %s: %s", attempt + 1, url, exc)
        assert last is not None
        raise last

    async def seller_counts(self, asin: str) -> tuple[int | None, int | None, bool]:
        """(total sellers, competing New FBA sellers, Amazon sells it)."""
        total: int | None = None
        seen = fba = 0
        amazon_sells = False
        for page in range(1, self.s.max_offer_pages + 1):
            url = (f"{BASE}/gp/product/ajax/aodAjaxMain/ref=dp_aod_NEW_mbc?asin={asin}"
                   f"&m=&qid=&smid=&sourcecustomerorglistid=&sourcecustomerorglistitemid=&sr=&pc=dp&pageno={page}")
            html = await self.get(url, referer=f"{BASE}/dp/{asin}")
            if not html:
                break
            offers = parse_offers(html)
            if page == 1 and offers.total is not None:
                total = offers.total
            if offers.on_page == 0:
                break
            seen += offers.on_page
            fba += offers.fba_new
            amazon_sells = amazon_sells or offers.amazon_sells
            if total is not None and seen >= total:
                break
            if fba > self.s.thresholds.max_fba_sellers:
                break  # already past the risk line, no need to read further
        if seen == 0 and total is None:
            return None, None, False
        return (total if total is not None else seen), fba, amazon_sells

    async def resolve(self, upc: str) -> AmazonListing | None:
        results = parse_search(await self.get(f"{BASE}/s?k={upc}"))
        if not results:
            return None
        asin, _ = results[0]
        listing = parse_product(await self.get(f"{BASE}/dp/{asin}?th=1&psc=1"), asin)
        try:
            total, fba, amazon_sells = await self.seller_counts(asin)
            listing.total_sellers, listing.fba_sellers = total, fba
            listing.amazon_sells = listing.amazon_sells or amazon_sells
        except Exception as exc:  # noqa: BLE001 - seller count is a risk flag, not a must-have
            log.warning("seller count failed for %s: %s", asin, exc)
        return listing
