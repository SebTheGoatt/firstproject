"""Plain data records passed between the modules."""
from __future__ import annotations

from dataclasses import dataclass


class CaptchaError(RuntimeError):
    """The site answered with a bot check instead of the page."""


@dataclass
class ListingTile:
    """One product tile from a Walmart clearance / deals / rollback page."""
    item_id: str
    title: str
    url: str
    price: float | None = None
    seller: str = ""            # empty when the tile does not say


@dataclass
class WalmartItem:
    item_id: str
    title: str
    price: float
    url: str
    upc: str
    seller: str


@dataclass
class AmazonListing:
    asin: str
    title: str
    buy_box_price: float | None
    is_prime: bool
    sales_rank: int | None
    rank_category: str
    total_sellers: int | None
    fba_sellers: int | None
    amazon_sells: bool = False   # Amazon.com itself is a seller: very hard to win the Buy Box


@dataclass
class Lead:
    asin: str
    upc: str
    title: str
    walmart_cost: float
    amazon_price: float
    sales_rank: int
    rank_category: str
    is_prime: bool
    total_sellers: int | None
    fba_sellers: int | None
    net_profit: float
    margin_pct: float
    high_competition: bool
    walmart_url: str
    date_found: str
    amazon_sells: bool = False
