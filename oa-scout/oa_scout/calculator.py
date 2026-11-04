"""OA risk and profit engine. Pure functions, no network, easy to test.

Same shape as the retail-arb analyzer it was modeled on (prices in, verdict out), with the
formulas and filters from the spec:

    Net Profit     = (Amazon Price * 0.85) - Walmart Price - $4.50
    Gross Margin % = (Net Profit / Amazon Price) * 100
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Thresholds


@dataclass(frozen=True)
class Verdict:
    keep: bool
    net_profit: float
    margin_pct: float
    high_competition: bool
    reason: str                 # why it was dropped, or "ok" / "ok: high competition"
    rule: str = "ok"            # short rule name for counting: profit, margin, rank, ...


def net_profit(amazon_price: float, walmart_price: float, t: Thresholds = Thresholds()) -> float:
    return round(amazon_price * (1 - t.amazon_fee_rate) - walmart_price - t.fixed_fee, 2)


def gross_margin_pct(profit: float, amazon_price: float) -> float:
    if amazon_price <= 0:
        return 0.0
    return round(profit / amazon_price * 100, 2)


def evaluate(walmart_price: float, amazon_price: float | None, sales_rank: int | None,
             fba_sellers: int | None, t: Thresholds = Thresholds()) -> Verdict:
    if amazon_price is None or amazon_price <= 0:
        return Verdict(False, 0.0, 0.0, False, "no buy box price", "no buy box")
    if walmart_price <= 0:
        return Verdict(False, 0.0, 0.0, False, "no walmart price", "no walmart price")

    profit = net_profit(amazon_price, walmart_price, t)
    margin = gross_margin_pct(profit, amazon_price)
    crowded = fba_sellers is not None and fba_sellers > t.max_fba_sellers

    if profit <= t.min_net_profit:
        return Verdict(False, profit, margin, crowded, f"net profit ${profit:.2f} <= ${t.min_net_profit:.2f}", "net profit")
    if margin < t.min_margin_pct:
        return Verdict(False, profit, margin, crowded, f"margin {margin:.1f}% < {t.min_margin_pct:.0f}%", "margin")
    if sales_rank is None:
        return Verdict(False, profit, margin, crowded, "no sales rank (can't confirm it sells)", "no sales rank")
    if sales_rank > t.max_sales_rank:
        return Verdict(False, profit, margin, crowded, f"sales rank {sales_rank:,} > {t.max_sales_rank:,}", "sales rank")
    return Verdict(True, profit, margin, crowded, "ok: high competition" if crowded else "ok")


_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "and", "for", "with", "of", "a", "an", "in", "to", "by", "pack", "count", "ct", "oz", "new"}


def title_similarity(a: str, b: str) -> float:
    """Word-overlap score 0..1. A UPC search on Amazon can surface a different product
    (or a multipack); a very low score means the match should not be trusted."""
    wa = {w for w in _WORD.findall(a.lower()) if w not in _STOP}
    wb = {w for w in _WORD.findall(b.lower()) if w not in _STOP}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))
