"""Command line: python -m oa_scout --pages 3 --max-items 200"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .config import Settings
from .db import LeadStore
from .pipeline import Pipeline
from .proxies import ProxyConfigError, ProxyPool


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="oa_scout", description="Walmart.com -> Amazon online arbitrage lead finder")
    p.add_argument("--url", action="append", dest="urls",
                   help="Walmart listing URL to crawl (repeatable). Default: clearance, rollbacks, deals")
    p.add_argument("--pages", type=int, default=3, help="pages per listing URL (default 3)")
    p.add_argument("--max-items", type=int, default=300, help="stop after examining this many items")
    p.add_argument("--db", default="oa_leads.db", help="SQLite file (default oa_leads.db)")
    p.add_argument("--walmart-concurrency", type=int, default=2)
    p.add_argument("--amazon-concurrency", type=int, default=4)
    p.add_argument("--proxy", choices=["none", "scrapeops", "smartproxy", "custom"],
                   help="proxy provider (default: OA_PROXY_PROVIDER env var, else none)")
    p.add_argument("--no-walmart-facet", action="store_true",
                   help="don't add Walmart's 'sold by Walmart' filter to listing URLs")
    p.add_argument("--headful", action="store_true", help="show the browser window")
    p.add_argument("--top", type=int, default=15, help="print the best N leads at the end")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("asyncio", "aiosqlite"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    settings = Settings(
        pages_per_url=args.pages, max_items=args.max_items, db_path=args.db,
        walmart_concurrency=args.walmart_concurrency, amazon_concurrency=args.amazon_concurrency,
        walmart_only_facet=not args.no_walmart_facet, headless=not args.headful,
    )
    if args.urls:
        settings.start_urls = args.urls
    if args.proxy:
        settings.proxy_provider = args.proxy

    try:
        proxies = ProxyPool.from_env(settings.proxy_provider)
    except ProxyConfigError as exc:
        print(f"Proxy setup: {exc}", file=sys.stderr)
        return 2

    try:
        stats = asyncio.run(Pipeline(settings, proxies).run())
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - startup problems (browser missing, DB locked)
        msg = str(exc).splitlines()[0]
        print(f"Could not start: {type(exc).__name__}: {msg}", file=sys.stderr)
        if "Executable doesn't exist" in str(exc):
            print("Run `python -m playwright install chromium`, or set OA_CHROMIUM_PATH.", file=sys.stderr)
        return 1

    print("\nRun summary", file=sys.stderr)
    for key, value in sorted(stats.items()):
        print(f"  {key:<55} {value}", file=sys.stderr)

    async def show_top() -> None:
        async with LeadStore(settings.db_path) as store:
            rows = await store.top(args.top)
        if not rows:
            print("No leads passed the rules this run.")
            return
        print(f"\n{'ASIN':<11} {'Cost':>8} {'Amazon':>8} {'Profit':>8} {'Margin':>7} {'Rank':>8} {'FBA':>4}  Title")
        for asin, title, cost, amz, profit, margin, rank, fba, crowded, amazon_sells in rows:
            flag = (" [crowded]" if crowded else "") + (" [Amazon sells]" if amazon_sells else "")
            print(f"{asin:<11} {cost:>8.2f} {amz:>8.2f} {profit:>8.2f} {margin:>6.1f}% {rank:>8,} "
                  f"{fba if fba is not None else '?':>4}  {title[:50]}{flag}")

    asyncio.run(show_top())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
