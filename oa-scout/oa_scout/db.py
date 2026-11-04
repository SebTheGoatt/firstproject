"""Local SQLite datastore (aiosqlite)."""
from __future__ import annotations

import asyncio

import aiosqlite

from .models import Lead

SCHEMA = """
CREATE TABLE IF NOT EXISTS profitable_leads (
    ASIN              TEXT PRIMARY KEY,
    UPC               TEXT NOT NULL,
    Title             TEXT NOT NULL,
    Walmart_Cost      REAL NOT NULL,
    Amazon_Price      REAL NOT NULL,
    Sales_Rank        INTEGER NOT NULL,
    Total_Sellers     INTEGER,
    Net_Profit        REAL NOT NULL,
    Margin_Percentage REAL NOT NULL,
    Walmart_URL       TEXT NOT NULL,
    Date_Found        TEXT NOT NULL,
    -- extras beyond the required columns
    Rank_Category     TEXT,
    Is_Prime          INTEGER NOT NULL DEFAULT 0,
    FBA_Sellers       INTEGER,
    High_Competition  INTEGER NOT NULL DEFAULT 0,
    Amazon_Sells      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_leads_profit ON profitable_leads (Net_Profit DESC);
"""

UPSERT = """
INSERT INTO profitable_leads (
    ASIN, UPC, Title, Walmart_Cost, Amazon_Price, Sales_Rank, Total_Sellers, Net_Profit,
    Margin_Percentage, Walmart_URL, Date_Found, Rank_Category, Is_Prime, FBA_Sellers, High_Competition,
    Amazon_Sells
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(ASIN) DO UPDATE SET
    UPC = excluded.UPC, Title = excluded.Title, Walmart_Cost = excluded.Walmart_Cost,
    Amazon_Price = excluded.Amazon_Price, Sales_Rank = excluded.Sales_Rank,
    Total_Sellers = excluded.Total_Sellers, Net_Profit = excluded.Net_Profit,
    Margin_Percentage = excluded.Margin_Percentage, Walmart_URL = excluded.Walmart_URL,
    Date_Found = excluded.Date_Found, Rank_Category = excluded.Rank_Category,
    Is_Prime = excluded.Is_Prime, FBA_Sellers = excluded.FBA_Sellers,
    High_Competition = excluded.High_Competition, Amazon_Sells = excluded.Amazon_Sells
"""


class LeadStore:
    def __init__(self, path: str):
        self.path = path
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "LeadStore":
        self._db = await aiosqlite.connect(self.path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def save(self, lead: Lead) -> None:
        assert self._db is not None, "use LeadStore as an async context manager"
        row = (
            lead.asin, lead.upc, lead.title, lead.walmart_cost, lead.amazon_price, lead.sales_rank,
            lead.total_sellers, lead.net_profit, lead.margin_pct, lead.walmart_url, lead.date_found,
            lead.rank_category, int(lead.is_prime), lead.fba_sellers, int(lead.high_competition),
            int(lead.amazon_sells),
        )
        async with self._lock:
            await self._db.execute(UPSERT, row)
            await self._db.commit()

    async def top(self, limit: int = 20) -> list[tuple]:
        assert self._db is not None
        cur = await self._db.execute(
            "SELECT ASIN, Title, Walmart_Cost, Amazon_Price, Net_Profit, Margin_Percentage, Sales_Rank, "
            "FBA_Sellers, High_Competition, Amazon_Sells FROM profitable_leads ORDER BY Net_Profit DESC LIMIT ?", (limit,))
        rows = await cur.fetchall()
        await cur.close()
        return list(rows)
