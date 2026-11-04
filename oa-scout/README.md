# OA Scout: Walmart.com → Amazon online arbitrage leads

This is a stand-alone tool, separate from the Post One Lawn Co. app in `property-dispatch/`. It:

1. crawls Walmart.com's clearance, rollback and deal pages,
2. keeps only items **sold and shipped by Walmart.com**,
3. looks up each UPC on Amazon,
4. applies the profit and risk rules, and
5. saves the leads that pass to SQLite.

## Setup

```bash
cd oa-scout
python3 -m venv .venv && source .venv/bin/activate
pip install playwright playwright-stealth aiohttp aiosqlite beautifulsoup4
python -m playwright install chromium
```

(Same list as `requirements.txt`. Python 3.10 or newer.)

## Proxies

Set these in your shell or a `.env` file you never commit:

```bash
# ScrapeOps residential: the gateway rotates the IP on every request
export OA_PROXY_PROVIDER=scrapeops SCRAPEOPS_API_KEY=...

# Smartproxy / Decodo residential: a new session id (= new IP) on every request
export OA_PROXY_PROVIDER=smartproxy SMARTPROXY_USER=... SMARTPROXY_PASS=...

# Your own list, rotated round-robin ("{session}" in a username becomes a random id per request)
export OA_PROXY_PROVIDER=custom OA_PROXY_LIST="http://user:pass@host:port,http://user2:pass@host2:port"
```

Every browser page gets a fresh context with its own proxy, user agent and window size. Every Amazon request goes out
through the next proxy in the pool.

## Run

```bash
python -m oa_scout --pages 3 --max-items 200            # clearance, rollbacks and deals
python -m oa_scout --url "https://www.walmart.com/shop/deals/clearance" --pages 5 -v
python -m oa_scout --headful                             # watch the browser
```

Logs and errors go to stderr. The summary at the end counts every skip and drop by reason, and the best leads print to
stdout. Results go to `oa_leads.db` (table `profitable_leads`):

```bash
sqlite3 oa_leads.db "SELECT ASIN, Title, Net_Profit, Margin_Percentage, Sales_Rank, FBA_Sellers, High_Competition, Amazon_Sells FROM profitable_leads ORDER BY Net_Profit DESC;"
```

## The rules (`oa_scout/calculator.py`, numbers in `oa_scout/config.py` → `Thresholds`)

- Net Profit = (Amazon price × 0.85) − Walmart price − $4.50
- Gross Margin % = Net Profit ÷ Amazon price × 100
- **Drop** when Net Profit ≤ $6.00, margin < 20%, Sales Rank > 80,000, or there is no rank or no Buy Box.
- **Flag** (kept, `High_Competition = 1`) when more than 15 sellers are offering the item **new and fulfilled by
  Amazon**. Used and renewed offers don't compete with a new item, so they aren't counted.
- **Flag** `Amazon_Sells = 1` when Amazon.com itself is a seller. A reseller rarely wins the Buy Box against Amazon.
- **Drop** the Amazon match when its title shares almost no words with the Walmart title. A UPC search sometimes
  returns a different product or a multipack.

## Code layout

| File | What it does |
|---|---|
| `oa_scout/walmart.py` | Playwright + stealth crawler. Reads `__NEXT_DATA__` first, then JSON-LD, then the page HTML. Checks that Walmart.com is the seller. |
| `oa_scout/amazon.py` | aiohttp resolver: UPC search → ASIN, Buy Box price, Prime, category rank, seller counts (all-offers list) |
| `oa_scout/calculator.py` | Profit formulas and rules (pure functions) |
| `oa_scout/db.py` | `aiosqlite` store, upsert by ASIN |
| `oa_scout/pipeline.py` | The loop. Each page and each product has its own try/except, so a timeout or captcha skips that one lead and the run continues. |
| `oa_scout/proxies.py` | Proxy presets and rotation |

Tests: `pip install pytest && python -m pytest -q`. They run offline and include a fake run where one item hits a
captcha and the rest still go through.

## Before you buy anything

- **The $4.50 is an estimate.** Real FBA fees depend on size and weight, and Amazon's referral fee isn't 15% in every
  category. Check each lead in Amazon's Revenue Calculator (or SP-API fee estimates) before you buy.
- **Check if you're allowed to sell it.** Many brands and categories are gated. Amazon usually doesn't accept retail
  receipts (like Walmart's) as invoices to get ungated.
- **Scraping Amazon breaks its terms of use**, and Walmart's too. Use your own seller account's tools for the Amazon
  side if you can: Amazon's SP-API (Catalog Items search by UPC, Product Pricing, Product Fees) or a data service like
  Keepa gives the same fields without proxies or captchas. `AmazonResolver.resolve(upc)` is the only function that
  would need to change.
- Keep the pace polite (the default delays and concurrency are deliberately low).
