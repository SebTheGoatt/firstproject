"""Offline tests: profit rules, Walmart and Amazon parsers, proxy rotation, the datastore,
and the full pipeline loop with fake fetchers (including a captcha that must not stop the run)."""
from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from oa_scout import amazon, walmart
from oa_scout.calculator import evaluate, gross_margin_pct, net_profit, title_similarity
from oa_scout.config import Settings, Thresholds
from oa_scout.db import LeadStore
from oa_scout.models import AmazonListing, CaptchaError, Lead, ListingTile, WalmartItem
from oa_scout.pipeline import Pipeline
from oa_scout.proxies import ProxyConfigError, ProxyPool


# ---------------------------------------------------------------- calculator
def test_formulas_match_spec():
    # (40 * 0.85) - 15 - 4.50 = 14.50 ; 14.50 / 40 = 36.25 %
    assert net_profit(40.0, 15.0) == 14.50
    assert gross_margin_pct(14.50, 40.0) == 36.25


@pytest.mark.parametrize("wm, amz, rank, fba, keep, rule", [
    (15.00, 40.00, 5_000, 3, True, "ok"),
    (10.00, 24.00, 5_000, 3, False, "net profit"),   # profit 5.90
    (23.50, 40.00, 5_000, 3, False, "net profit"),   # profit 6.00 -> dropped (<=)
    (60.00, 90.00, 5_000, 3, False, "margin"),       # profit 12.00, margin 13.3 %
    (15.00, 40.00, 80_001, 3, False, "sales rank"),
    (15.00, 40.00, 80_000, 3, True, "ok"),           # exactly at the line is allowed
    (15.00, 40.00, None, 3, False, "no sales rank"),
    (15.00, None, 5_000, 3, False, "no buy box"),
])
def test_rules(wm, amz, rank, fba, keep, rule):
    v = evaluate(wm, amz, rank, fba)
    assert v.keep is keep
    assert v.rule == rule


def test_high_competition_is_flagged_not_dropped():
    v = evaluate(15.0, 40.0, 5_000, 16)
    assert v.keep and v.high_competition
    assert not evaluate(15.0, 40.0, 5_000, 15).high_competition


def test_title_similarity():
    assert title_similarity("Hamilton Beach 2-Slice Toaster, Black", "Hamilton Beach 2 Slice Toaster Black 22633") > 0.6
    assert title_similarity("Hamilton Beach Toaster", "LEGO Star Wars X-Wing") == 0.0


# ---------------------------------------------------------------- walmart
def _next_data(payload: dict) -> str:
    return f'<html><head></head><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script></body></html>'


LISTING = _next_data({"props": {"pageProps": {"initialData": {"searchResult": {"itemStacks": [{"items": [
    {"__typename": "Product", "usItemId": "111", "name": "Toaster", "canonicalUrl": "/ip/Toaster/111",
     "priceInfo": {"currentPrice": {"price": 15.0}}, "sellerName": "Walmart.com"},
    {"__typename": "Product", "usItemId": "222", "name": "Knockoff Toaster", "canonicalUrl": "/ip/Knock/222",
     "priceInfo": {"linePrice": "$9.97"}, "sellerName": "Shady Deals LLC"},
    {"__typename": "AdPlaceholder", "usItemId": "999", "name": "ad"},
]}]}}}}})


def test_listing_from_next_data():
    tiles = walmart.parse_listing(LISTING)
    assert [(t.item_id, t.price, t.seller) for t in tiles] == [("111", 15.0, "Walmart.com"),
                                                               ("222", 9.97, "Shady Deals LLC")]
    assert tiles[0].url == "https://www.walmart.com/ip/Toaster/111"


def test_listing_dom_fallback():
    html = """<div data-item-id="333"><a href="/ip/Blender/333?athbdg=1">x</a>
      <span data-automation-id="product-title">Blender 500W</span>
      <div data-automation-id="product-price"><span>current price $24.88</span></div></div>"""
    [tile] = walmart.parse_listing(html)
    assert (tile.item_id, tile.title, tile.price, tile.url) == ("333", "Blender 500W", 24.88,
                                                                "https://www.walmart.com/ip/Blender/333")


def _product_page(seller="Walmart.com", upc="0012345678905", status="IN_STOCK"):
    return _next_data({"props": {"pageProps": {"initialData": {"data": {"product": {
        "usItemId": "111", "name": "Hamilton Beach 2-Slice Toaster", "upc": upc, "sellerName": seller,
        "availabilityStatus": status, "priceInfo": {"currentPrice": {"price": 15.0}}}}}}}})


def test_product_sold_by_walmart():
    item, why = walmart.parse_product(_product_page(), "https://www.walmart.com/ip/111")
    assert why == ""
    assert (item.upc, item.price, item.seller) == ("012345678905", 15.0, "Walmart.com")


@pytest.mark.parametrize("kwargs, reason", [
    ({"seller": "Shady Deals LLC"}, "third-party seller"),
    ({"upc": ""}, "no UPC"),
    ({"status": "OUT_OF_STOCK"}, "out of stock"),
])
def test_product_guardrails(kwargs, reason):
    item, why = walmart.parse_product(_product_page(**kwargs), "https://www.walmart.com/ip/111")
    assert item is None and why.startswith(reason)


def test_product_dom_fallback_needs_sold_and_shipped_text():
    ld = {"@type": "Product", "name": "Mixer", "gtin13": "0001112223334", "offers": {"price": "19.99"}}
    base = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    ok = base + '<div data-testid="product-seller-info">Sold and shipped by Walmart.com</div>'
    bad = base + '<div data-testid="product-seller-info">Sold and shipped by GadgetHub</div>'
    item, _ = walmart.parse_product(ok, "u")
    assert item and item.upc == "001112223334" and item.price == 19.99
    assert walmart.parse_product(bad, "u")[0] is None


def test_page_url_adds_page_and_walmart_facet():
    url = walmart.page_url("https://www.walmart.com/shop/deals/clearance", 2, True)
    assert url == "https://www.walmart.com/shop/deals/clearance?page=2&facet=retailer_type:Walmart"


def test_walmart_captcha_detection():
    assert walmart.looks_like_captcha("<title>Robot or human?</title>")
    assert not walmart.looks_like_captcha(LISTING)


# ---------------------------------------------------------------- amazon
SEARCH = """
<div data-component-type="s-search-result" data-asin="B0SPONSOR1" class="AdHolder"><h2>ad</h2></div>
<div data-component-type="s-search-result" data-asin="B0ORGANIC1"><div data-cy="title-recipe">
  <h2><span>Hamilton Beach</span></h2><a><h2 aria-label="2 Slice Toaster"><span>2 Slice Toaster</span></h2></a></div></div>
"""

PRODUCT = """
<span id="productTitle"> Hamilton Beach 2 Slice Toaster, Black </span>
<div id="availability"><span class="a-color-price">Only 1 left in stock - order soon.</span></div>
<div id="rightCol"><div id="desktop_buybox">
  <div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">$39.99</span></span></div>
  <i class="a-icon a-icon-prime aok-hidden"></i>
  <span>Ships from: Amazon.com</span> <span>Sold by: ToastKing</span>
</div></div>
<div id="detailBulletsWrapper_feature_div"><ul><li><span>Best Sellers Rank:</span>
  #4,512 in Kitchen &amp; Dining (See Top 100 in Kitchen &amp; Dining) #12 in Toasters</li></ul></div>
"""

def _offer(tag, cond, ships, sold):
    return (f'<div id="{tag}"><div id="aod-offer-heading">{cond}</div>'
            f'<div id="aod-offer-shipsFrom">Ships from {ships}</div><div id="aod-offer-soldBy">Sold by {sold}</div></div>')


# Same shape as a live offer list: the pinned Buy Box offer is not in the total count.
OFFERS = '<input id="aod-total-offer-count" value="4">' + "".join([
    _offer("aod-pinned-offer", "New", "Amazon.com", "Amazon.com"),
    _offer("aod-offer", "Used - Like New", "Amazon.com", "Amazon Resale"),
    _offer("aod-offer", "New", "Amazon.com", "ToastKing"),
    _offer("aod-offer", "New", "ToastKing", "ToastKing"),
    _offer("aod-offer", "New", "Amazon", "BrightHome"),
])


def test_amazon_search_skips_sponsored_and_joins_brand():
    assert amazon.parse_search(SEARCH) == [("B0ORGANIC1", "Hamilton Beach 2 Slice Toaster")]


def test_amazon_product():
    listing = amazon.parse_product(PRODUCT, "B0ORGANIC1")
    assert listing.buy_box_price == 39.99          # "Only 1 left" is not out of stock
    assert listing.is_prime                        # ships from Amazon, though the icon is hidden
    assert not listing.amazon_sells
    assert (listing.sales_rank, listing.rank_category) == (4512, "Kitchen & Dining")


def test_amazon_offers_count_new_fba_only():
    page = amazon.parse_offers(OFFERS)
    assert (page.total, page.on_page, page.fba_new, page.amazon_sells) == (5, 5, 3, True)


def test_amazon_unavailable_has_no_price():
    html = PRODUCT.replace("Only 1 left in stock - order soon.", "Currently unavailable.")
    listing = amazon.parse_product(html, "B0X")
    assert listing.buy_box_price is None and not listing.is_prime


def test_amazon_captcha_detection():
    assert amazon.looks_like_captcha("<form action='/errors/validateCaptcha'>")


# ---------------------------------------------------------------- proxies
def test_custom_proxy_rotation(monkeypatch):
    monkeypatch.setenv("OA_PROXY_LIST", "http://u1:p1@10.0.0.1:8000, http://u-{session}:p2@10.0.0.2:8000")
    pool = ProxyPool.from_env("custom")
    a, b, c = pool.next(), pool.next(), pool.next()
    assert a.for_http() == "http://u1:p1@10.0.0.1:8000"
    assert b.username.startswith("u-") and b.username != "u-{session}"
    assert c.server == a.server
    assert "p1" not in a.masked()


def test_smartproxy_new_session_every_request(monkeypatch):
    monkeypatch.setenv("SMARTPROXY_USER", "me")
    monkeypatch.setenv("SMARTPROXY_PASS", "secret")
    pool = ProxyPool.from_env("smartproxy")
    first, second = pool.next(), pool.next()
    assert first.username.startswith("user-me-session-")
    assert first.username != second.username


def test_missing_proxy_secret(monkeypatch):
    monkeypatch.delenv("SCRAPEOPS_API_KEY", raising=False)
    with pytest.raises(ProxyConfigError):
        ProxyPool.from_env("scrapeops")


# ---------------------------------------------------------------- datastore
def _lead(asin="B0ORGANIC1", profit=14.5):
    return Lead(asin, "012345678905", "Toaster", 15.0, 40.0, 4512, "Kitchen", True, 3, 2,
                profit, 36.25, False, "https://www.walmart.com/ip/111", "2026-11-04T12:00:00+00:00")


def test_store_upserts_by_asin(tmp_path):
    db = tmp_path / "leads.db"

    async def go():
        async with LeadStore(str(db)) as store:
            await store.save(_lead(profit=10.0))
            await store.save(_lead(profit=14.5))
            return await store.top()

    rows = asyncio.run(go())
    assert len(rows) == 1 and rows[0][4] == 14.5
    cols = [r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(profitable_leads)")]
    for required in ("ASIN", "UPC", "Title", "Walmart_Cost", "Amazon_Price", "Sales_Rank", "Total_Sellers",
                     "Net_Profit", "Margin_Percentage", "Walmart_URL", "Date_Found"):
        assert required in cols


# ---------------------------------------------------------------- pipeline loop
class FakeWalmart:
    def __init__(self, tiles, products):
        self.tiles, self.products = tiles, products

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def listing(self, url, page):
        return self.tiles if page == 1 else []

    async def product(self, tile):
        result = self.products[tile.item_id]
        if isinstance(result, Exception):
            raise result
        return result


class FakeAmazon(FakeWalmart):
    def __init__(self, listings):
        self.listings = listings

    async def resolve(self, upc):
        return self.listings.get(upc)


def test_pipeline_keeps_going_after_captcha_and_saves_only_good_leads(tmp_path, monkeypatch):
    tiles = [ListingTile("1", "Toaster", "u1", 15.0, "Walmart.com"),
             ListingTile("2", "Kettle", "u2", 10.0, ""),
             ListingTile("3", "Fan", "u3", 10.0, "Some Marketplace Seller"),
             ListingTile("4", "Lamp", "u4", 30.0, "Walmart.com")]
    products = {
        "1": (WalmartItem("1", "Hamilton Beach 2 Slice Toaster", 15.0, "u1", "111111111111", "Walmart.com"), ""),
        "2": CaptchaError("blocked"),
        "4": (WalmartItem("4", "Desk Lamp LED", 30.0, "u4", "444444444444", "Walmart.com"), ""),
    }
    listings = {
        "111111111111": AmazonListing("B0GOOD", "Hamilton Beach 2 Slice Toaster Black", 40.0, True, 4512, "Kitchen", 3, 2),
        "444444444444": AmazonListing("B0SLOW", "Desk Lamp LED", 80.0, True, 250_000, "Home", 2, 1),
    }
    monkeypatch.setattr("oa_scout.pipeline.WalmartCrawler", lambda s, p: FakeWalmart(tiles, products))
    monkeypatch.setattr("oa_scout.pipeline.AmazonResolver", lambda s, p: FakeAmazon(listings))

    settings = Settings(start_urls=["https://www.walmart.com/shop/deals/clearance"],
                        db_path=str(tmp_path / "leads.db"), thresholds=Thresholds())
    stats = asyncio.run(Pipeline(settings, ProxyPool([])).run())

    assert stats["examined"] == 4
    assert stats["captcha"] == 1
    assert stats["skip: third-party seller"] == 1
    assert stats["drop: sales rank"] == 1
    assert stats["saved"] == 1
    rows = sqlite3.connect(settings.db_path).execute("SELECT ASIN, Net_Profit FROM profitable_leads").fetchall()
    assert rows == [("B0GOOD", 14.5)]
