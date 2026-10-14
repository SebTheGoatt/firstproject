"""Prices, lawn sizes and Texas sales tax.

Mowing:   price = the $50 flat fee or (the customer's rate × square feet of
          lawn), whichever is higher. The flat fee is the minimum visit charge.
          Customers pick their rate, pay-what-you-can: 0.9¢, 1.0¢ or 1.1¢ per sq ft.
Bins/gutters: priced on site by the crew; tax is added the same way.
Tax:      the area's combined Texas rate (state 6.25% + local) on the service
          price, rounded to the cent. Donations are voluntary and untaxed.

All money math uses Decimal so totals never drift by a cent.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .models import SQFT_RATE_CHOICES, Service
from .zones import ServiceZone

# Pay-what-you-can: the customer picks any of these per-square-foot rates.
RATE_CHOICES: tuple[Decimal, ...] = tuple(Decimal(c) for c in SQFT_RATE_CHOICES)
DEFAULT_RATE = Decimal("0.010")
MIN_SQFT, MAX_SQFT = 200, 87_120  # up to 2 acres; bigger jobs are quoted in person

# Size picker shown at booking. `sqft` is the representative size we price on;
# the crew confirms the real size on site before anything is charged.
LAWN_SIZES: dict[str, dict] = {
    "small":  {"label": "Small",  "range": "up to 3,000 sq ft",    "sqft": 2_500,  "example": "Townhome or small yard"},
    "medium": {"label": "Medium", "range": "3,000–6,000 sq ft",    "sqft": 4_500,  "example": "Typical subdivision lot"},
    "large":  {"label": "Large",  "range": "6,000–10,000 sq ft",   "sqft": 8_000,  "example": "Corner or oversized lot"},
    "xl":     {"label": "X-Large", "range": "10,000–15,000 sq ft", "sqft": 12_500, "example": "Quarter-acre or more"},
}

CENT = Decimal("0.01")


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Quote:
    subtotal: Decimal | None      # None → priced on site
    tax_rate: Decimal
    tax: Decimal | None
    total: Decimal | None
    lawn_sqft: int | None
    basis: str                    # "flat" | "per_sqft" | "on_site" | "set_on_site"
    sqft_rate: Decimal | None = None   # mowing: the customer's chosen rate

    def as_dict(self) -> dict:
        f = lambda d: float(d) if d is not None else None  # noqa: E731
        return {"subtotal": f(self.subtotal), "tax_rate": float(self.tax_rate), "tax": f(self.tax),
                "total": f(self.total), "lawn_sqft": self.lawn_sqft, "basis": self.basis,
                "sqft_rate": f(self.sqft_rate)}


def resolve_rate(rate) -> Decimal:
    """The customer's chosen rate, or the middle one. Anything off the menu is refused."""
    if rate is None:
        return DEFAULT_RATE
    r = Decimal(str(rate))
    if r not in RATE_CHOICES:
        raise ValueError("Please choose one of our per-square-foot rates.")
    return next(c for c in RATE_CHOICES if c == r)


def resolve_sqft(lawn_size: str | None, lawn_sqft: int | None) -> int | None:
    if lawn_sqft is not None:
        return max(MIN_SQFT, min(int(lawn_sqft), MAX_SQFT))
    if lawn_size in LAWN_SIZES:
        return LAWN_SIZES[lawn_size]["sqft"]
    return None


def with_tax(subtotal: Decimal, rate: Decimal) -> tuple[Decimal, Decimal]:
    tax = money(subtotal * rate)
    return tax, subtotal + tax


def quote(zone: ServiceZone, service: Service, lawn_sqft: int | None = None,
          on_site_price: float | None = None, sqft_rate=None) -> Quote:
    """Price a visit. `on_site_price` is the crew's pre-tax price for quoted services;
    `sqft_rate` is the customer's chosen mowing rate (see RATE_CHOICES)."""
    rate = Decimal(str(zone.tax_rate))
    per_sqft = resolve_rate(sqft_rate) if service is Service.MOWING else None
    if service is Service.MOWING:
        flat = money(zone.mow_rate)
        by_size = money(per_sqft * lawn_sqft) if lawn_sqft else Decimal(0)
        subtotal, basis = (by_size, "per_sqft") if by_size > flat else (flat, "flat")
    elif on_site_price is not None:
        subtotal, basis = money(on_site_price), "set_on_site"
    else:
        return Quote(None, rate, None, None, None, "on_site")
    tax, total = with_tax(subtotal, rate)
    return Quote(subtotal, rate, tax, total, lawn_sqft if service is Service.MOWING else None, basis, per_sqft)
