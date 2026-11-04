"""Settings for OA Scout: proxies, sourcing pages, pacing and the profit rules.

Secrets (proxy passwords, API keys) are read from environment variables only.
Never write them into this file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Proxy harness
# ---------------------------------------------------------------------------
# OA_PROXY_PROVIDER picks one of the presets below, or "custom", or "none".
#
#   scrapeops   SCRAPEOPS_API_KEY=...            (gateway rotates the IP on every request)
#   smartproxy  SMARTPROXY_USER=... SMARTPROXY_PASS=...
#               (a new random session id per request = a new residential IP per request)
#   custom      OA_PROXY_LIST="http://user:pass@host:port,http://user:pass@host2:port"
#               or OA_PROXY_FILE=/path/to/proxies.txt (one URL per line); rotated round-robin.
#               A "{session}" placeholder in a username is replaced with a random id per request.
#   none        direct connection (fine for a quick local test, you will get blocked fast)
PROXY_PRESETS: dict[str, dict[str, str]] = {
    "scrapeops": {
        "server": "http://residential-proxy.scrapeops.io:8181",
        "username": "scrapeops",
        "password_env": "SCRAPEOPS_API_KEY",
    },
    "smartproxy": {
        # Smartproxy is now branded Decodo; both hostnames point at the same gateway.
        "server": os.getenv("SMARTPROXY_GATEWAY", "http://gate.smartproxy.com:7000"),
        "username_env": "SMARTPROXY_USER",
        "password_env": "SMARTPROXY_PASS",
        # Sticky-session format: one random session id per request -> one fresh IP per request.
        "username_template": "user-{username}-session-{session}",
    },
}

# ---------------------------------------------------------------------------
# Walmart sourcing pages (online clearance, deals, rollbacks)
# ---------------------------------------------------------------------------
DEFAULT_START_URLS: tuple[str, ...] = (
    "https://www.walmart.com/shop/deals/clearance",
    "https://www.walmart.com/shop/deals/rollbacks",
    "https://www.walmart.com/shop/deals",
)

# Walmart's own "Sold by Walmart" filter. It trims third-party tiles before we even look at them;
# every item is still checked again on its product page.
WALMART_ONLY_FACET = "retailer_type:Walmart"

USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.6 Safari/605.1.15",
)


@dataclass(frozen=True)
class Thresholds:
    """The OA rules. Net Profit = Amazon * (1 - fee_rate) - Walmart - fixed_fee."""

    amazon_fee_rate: float = 0.15       # Amazon price * 0.85
    fixed_fee: float = 4.50             # estimated FBA fulfillment + inbound UPS shipping
    min_net_profit: float = 6.00        # drop when Net Profit <= this
    min_margin_pct: float = 20.0        # drop when Gross Margin % < this
    max_sales_rank: int = 80_000        # drop when category Sales Rank > this
    max_fba_sellers: int = 15           # flag as high risk when FBA sellers > this
    min_title_similarity: float = 0.25  # drop when the Amazon match looks like a different product


@dataclass
class Settings:
    start_urls: list[str] = field(default_factory=lambda: list(DEFAULT_START_URLS))
    pages_per_url: int = 3
    max_items: int = 300                # stop after this many Walmart items have been examined
    db_path: str = "oa_leads.db"
    walmart_concurrency: int = 2        # browser pages open at once
    amazon_concurrency: int = 4         # Amazon lookups in flight at once
    walmart_only_facet: bool = True
    headless: bool = True
    page_timeout_ms: int = 45_000
    http_timeout_s: float = 30.0
    retries: int = 2                    # extra attempts per page (each attempt gets a fresh IP)
    walmart_delay_s: tuple[float, float] = (1.5, 4.0)   # random pause before each browser page
    amazon_delay_s: tuple[float, float] = (1.0, 2.5)    # random pause before each Amazon request
    max_offer_pages: int = 3            # Amazon offer-list pages read per ASIN (10 offers a page)
    thresholds: Thresholds = field(default_factory=Thresholds)
    proxy_provider: str = field(default_factory=lambda: os.getenv("OA_PROXY_PROVIDER", "none"))
    # Optional: use a specific Chrome/Chromium build instead of Playwright's bundled one.
    chromium_path: str = field(default_factory=lambda: os.getenv("OA_CHROMIUM_PATH", ""))
