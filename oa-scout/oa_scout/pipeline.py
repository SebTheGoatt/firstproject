"""The processing loop: Walmart listings -> Walmart product -> Amazon match -> rules -> SQLite.

Every listing page and every product is wrapped in its own try/except: a timeout, captcha or
parse error is logged to stderr and the loop moves straight on to the next lead.
"""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import datetime, timezone

from .amazon import AmazonResolver
from .calculator import evaluate, title_similarity
from .config import Settings
from .db import LeadStore
from .models import CaptchaError, Lead, ListingTile
from .proxies import ProxyPool
from .walmart import WalmartCrawler, is_walmart_seller

log = logging.getLogger("oa_scout.pipeline")


class Pipeline:
    def __init__(self, settings: Settings, proxies: ProxyPool | None = None):
        self.s = settings
        self.proxies = proxies if proxies is not None else ProxyPool.from_env(settings.proxy_provider)
        self.stats: Counter[str] = Counter()
        self._seen_items: set[str] = set()
        self._seen_upcs: set[str] = set()

    async def run(self) -> Counter[str]:
        if not self.proxies.enabled:
            log.warning("no proxy configured (OA_PROXY_PROVIDER=none); expect bot checks quickly")
        async with LeadStore(self.s.db_path) as store, \
                WalmartCrawler(self.s, self.proxies) as walmart, \
                AmazonResolver(self.s, self.proxies) as amazon:
            for start_url in self.s.start_urls:
                for page in range(1, self.s.pages_per_url + 1):
                    if self.stats["examined"] >= self.s.max_items:
                        return self.stats
                    try:
                        tiles = await walmart.listing(start_url, page)
                    except CaptchaError as exc:
                        self._fail("listing captcha", f"{exc}")
                        continue
                    except Exception as exc:  # noqa: BLE001
                        self._fail("listing error", f"{start_url} page {page}: {type(exc).__name__}: {exc}")
                        continue
                    if not tiles:
                        break  # past the last page of this section
                    fresh = [t for t in tiles if self._take(t)]
                    await asyncio.gather(*(self._process(t, walmart, amazon, store) for t in fresh))
        return self.stats

    def _take(self, tile: ListingTile) -> bool:
        if tile.item_id in self._seen_items or self.stats["examined"] >= self.s.max_items:
            return False
        self._seen_items.add(tile.item_id)
        self.stats["examined"] += 1
        if tile.seller and not is_walmart_seller(tile.seller):
            self.stats["skip: third-party seller"] += 1
            return False
        return True

    def _fail(self, kind: str, detail: str) -> None:
        self.stats[kind] += 1
        log.error("%s: %s", kind, detail)

    async def _process(self, tile: ListingTile, walmart: WalmartCrawler,
                       amazon: AmazonResolver, store: LeadStore) -> None:
        try:
            item, why = await walmart.product(tile)
            if item is None:
                self.stats[f"skip: {why.split(' (')[0]}"] += 1
                return
            if item.upc in self._seen_upcs:
                self.stats["skip: duplicate UPC"] += 1
                return
            self._seen_upcs.add(item.upc)

            listing = await amazon.resolve(item.upc)
            if listing is None:
                self.stats["skip: not on Amazon"] += 1
                return
            similarity = title_similarity(item.title, listing.title)
            if listing.title and similarity < self.s.thresholds.min_title_similarity:
                self.stats["drop: Amazon match looks like a different product"] += 1
                log.info("mismatch %s vs %s (%.2f)", item.title[:60], listing.title[:60], similarity)
                return

            verdict = evaluate(item.price, listing.buy_box_price, listing.sales_rank,
                               listing.fba_sellers, self.s.thresholds)
            if not verdict.keep:
                self.stats[f"drop: {verdict.rule}"] += 1
                log.info("drop %s (%s): %s", listing.asin, item.title[:60], verdict.reason)
                return

            assert listing.buy_box_price is not None and listing.sales_rank is not None
            await store.save(Lead(
                asin=listing.asin, upc=item.upc, title=item.title, walmart_cost=item.price,
                amazon_price=listing.buy_box_price, sales_rank=listing.sales_rank,
                rank_category=listing.rank_category, is_prime=listing.is_prime,
                total_sellers=listing.total_sellers, fba_sellers=listing.fba_sellers,
                net_profit=verdict.net_profit, margin_pct=verdict.margin_pct,
                high_competition=verdict.high_competition, walmart_url=item.url,
                date_found=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                amazon_sells=listing.amazon_sells,
            ))
            self.stats["saved"] += 1
            if verdict.high_competition:
                self.stats["saved (high competition)"] += 1
            log.info("LEAD %s  $%.2f -> $%.2f  profit $%.2f (%.1f%%)  rank %s%s  %s",
                     listing.asin, item.price, listing.buy_box_price, verdict.net_profit,
                     verdict.margin_pct, f"{listing.sales_rank:,}",
                     ("  HIGH COMPETITION" if verdict.high_competition else "")
                     + ("  AMAZON SELLS" if listing.amazon_sells else ""), item.title[:60])
        except CaptchaError as exc:
            self._fail("captcha", f"{tile.url}: {exc}")
        except asyncio.TimeoutError:
            self._fail("timeout", tile.url)
        except Exception as exc:  # noqa: BLE001 - one bad lead never stops the run
            self._fail("error", f"{tile.url}: {type(exc).__name__}: {exc}")
