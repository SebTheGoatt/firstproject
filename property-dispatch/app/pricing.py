"""Prices, lawn sizes, rate tiers and Texas sales tax.

Mowing:   subtotal = $35 base service fee (once per visit) + square feet × the
          rate the customer picks. The customer must pick one; nothing is preselected.
            Standard  $0.009 / sq ft
            Plus      $0.010 / sq ft
            Premium   $0.012 / sq ft
          The tiers are prices only; the work is the same. Each tier also gives a
          share of the price to charity (2% / 7% / 12%), split between the causes
          in app/charity.py. That comes out of what the business keeps; the
          customer pays the price + tax, nothing extra.
          Lawn size is required and must be a whole number of square feet between
          MIN_SQFT and MAX_SQFT. Nothing is substituted when it's missing.
Add-ons:  bin cleaning $15, gutter cleaning $15, with a mowing visit. Holiday
          lighting (Oct 15 – Jan 15) is a free quote request: it's noted on the
          booking for the crew and never charged online.
Old bin/gutter-only bookings: priced on site by the crew; tax is added the same way.
Tax:      the service area's configured Texas rate (zones.py) on the whole service
          price, rounded to the cent. Voluntary donations are separate and untaxed.

All money math uses Decimal so totals never drift by a cent.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .models import Service
from .zones import ServiceZone

# key → per-square-foot rate and the share of the price given to charity.
PACKAGES: dict[str, dict] = {
    # Keys are stored on bookings, so they stay stable when the shown names change.
    "standard":  {"label": "Standard", "rate": Decimal("0.009"), "giving": Decimal("0.02"),
                  "description": "Essential lawn maintenance at our most affordable rate."},
    "supporter": {"label": "Plus",     "rate": Decimal("0.010"), "giving": Decimal("0.07"),
                  "description": "A balanced option for dependable lawn care."},
    "hero":      {"label": "Premium",  "rate": Decimal("0.012"), "giving": Decimal("0.12"),
                  "description": "Our highest service rate for customers who prefer the premium option."},
}
DEFAULT_PACKAGE = "standard"
MIN_SQFT, MAX_SQFT = 100, 87_120  # up to 2 acres; bigger properties are quoted in person

# Size picker shown at booking. `sqft` is the representative size we price on;
# the crew confirms the real size on site before anything is charged.
LAWN_SIZES: dict[str, dict] = {
    "small":  {"label": "Small",  "range": "up to 3,000 sq ft",    "sqft": 2_500,  "example": "Townhome or small yard"},
    "medium": {"label": "Medium", "range": "3,000–6,000 sq ft",    "sqft": 4_500,  "example": "Typical subdivision lot"},
    "large":  {"label": "Large",  "range": "6,000–10,000 sq ft",   "sqft": 8_000,  "example": "Corner or oversized lot"},
    "xl":     {"label": "X-Large", "range": "10,000–15,000 sq ft", "sqft": 12_500, "example": "Quarter-acre or more"},
}
DEFAULT_SIZE = "medium"  # no size given → priced as a typical lot; the crew confirms on site

# Add-ons to a mowing visit: fixed price (before tax) and extra minutes on site.
# `season` = (start (month, day), end (month, day)) of service dates it's offered, wrapping the new year.
ADD_ONS: dict[str, dict] = {
    "bin_cleaning":   {"label": "Bin cleaning",              "price": Decimal("15.00"), "minutes": 15},
    "gutters":        {"label": "Gutter cleaning",           "price": Decimal("15.00"), "minutes": 30},
    # Quote only: no price, nothing charged. The crew sees the request on the stop.
    "holiday_lights": {"label": "Holiday lighting quote",    "price": None, "quote": True, "minutes": 10,
                       "season": ((10, 15), (1, 15))},
}


def in_season(key: str, day) -> bool:
    season = ADD_ONS[key].get("season")
    if not season or day is None:
        return season is None
    (sm, sd), (em, ed) = season
    md = (day.month, day.day)
    return md >= (sm, sd) or md <= (em, ed) if (sm, sd) > (em, ed) else (sm, sd) <= md <= (em, ed)


def season_text(key: str) -> str | None:
    season = ADD_ONS[key].get("season")
    if not season:
        return None
    (sm, sd), (em, ed) = season
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    return f"{months[sm - 1]} {sd} – {months[em - 1]} {ed}"

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
    basis: str                    # "base_plus_sqft" | "on_site" | "set_on_site"
    package: str | None = None    # mowing: standard | supporter | hero
    sqft_rate: Decimal | None = None
    base_fee: Decimal | None = None
    charity_rate: Decimal | None = None
    charity_amount: Decimal | None = None   # part of the subtotal the business gives away
    add_ons: tuple = ()                     # ({"key", "label", "price"}, ...)
    add_on_total: Decimal = Decimal(0)

    @property
    def mow_price(self) -> Decimal | None:
        return None if self.subtotal is None else self.subtotal - self.add_on_total

    @property
    def business_net(self) -> Decimal | None:
        """What the business keeps from the service price (tax goes to the state)."""
        if self.subtotal is None:
            return None
        return self.subtotal - (self.charity_amount or 0)

    def as_dict(self) -> dict:
        f = lambda d: float(d) if d is not None else None  # noqa: E731
        return {"subtotal": f(self.subtotal), "tax_rate": float(self.tax_rate), "tax": f(self.tax),
                "total": f(self.total), "lawn_sqft": self.lawn_sqft, "basis": self.basis,
                "package": self.package, "package_label": PACKAGES[self.package]["label"] if self.package else None,
                "sqft_rate": f(self.sqft_rate), "base_fee": f(self.base_fee),
                "charity_rate": f(self.charity_rate), "charity_amount": f(self.charity_amount),
                "business_net": f(self.business_net), "mow_price": f(self.mow_price),
                "add_ons": [{**a, "price": f(a["price"])} for a in self.add_ons],
                "add_on_total": float(self.add_on_total)}


def resolve_package(package: str | None) -> str:
    """The customer's package; anything unknown falls back to Standard (as the pricing sheet does)."""
    return package if package in PACKAGES else DEFAULT_PACKAGE


def package_for_rate(sqft_rate) -> str | None:
    """Bookings made with a bare rate (before packages) map to the package with that rate."""
    if sqft_rate is None:
        return None
    r = Decimal(str(sqft_rate))
    return next((k for k, p in PACKAGES.items() if p["rate"] == r), None)


def resolve_sqft(lawn_size: str | None, lawn_sqft: int | None) -> int | None:
    if lawn_sqft is not None:
        return max(MIN_SQFT, min(int(lawn_sqft), MAX_SQFT))
    if lawn_size in LAWN_SIZES:
        return LAWN_SIZES[lawn_size]["sqft"]
    return None


def with_tax(subtotal: Decimal, rate: Decimal) -> tuple[Decimal, Decimal]:
    tax = money(subtotal * rate)
    return tax, subtotal + tax


def priced_add_ons(keys) -> tuple:
    """The chosen add-ons in catalog order, each once, with label and price."""
    chosen = set(keys or ())
    unknown = chosen - ADD_ONS.keys()
    if unknown:
        raise ValueError(f"Unknown add-on: {', '.join(sorted(unknown))}")
    return tuple({"key": k, "label": a["label"], "price": a["price"], **({"quote": True} if a.get("quote") else {})}
                 for k, a in ADD_ONS.items() if k in chosen)


class LawnSizeError(ValueError):
    pass


def check_sqft(lawn_sqft) -> int:
    """A customer's lawn size: a whole number of square feet within our limits. Never guessed."""
    if lawn_sqft is None or lawn_sqft == "":
        raise LawnSizeError("Enter your lawn size in square feet.")
    try:
        n = int(lawn_sqft)
    except (TypeError, ValueError):
        raise LawnSizeError("Lawn size must be a whole number of square feet.")
    if isinstance(lawn_sqft, float) and lawn_sqft != n:
        raise LawnSizeError("Lawn size must be a whole number of square feet.")
    if n <= 0:
        raise LawnSizeError("Lawn size must be greater than zero.")
    if n < MIN_SQFT:
        raise LawnSizeError(f"The smallest lawn we can book online is {MIN_SQFT:,} sq ft.")
    if n > MAX_SQFT:
        raise LawnSizeError(f"Lawns over {MAX_SQFT:,} sq ft (2 acres) are quoted in person. "
                            "Book with your best estimate and the crew will confirm, or reach out to us.")
    return n


def quote(zone: ServiceZone, service: Service, lawn_sqft: int | None = None,
          on_site_price: float | None = None, package: str | None = None, add_ons=()) -> Quote:
    """Price a visit. `on_site_price` is the crew's pre-tax price for quoted services;
    `package` is the customer's mowing package (see PACKAGES); `add_ons` are ADD_ONS keys."""
    rate = Decimal(str(zone.tax_rate))
    if service is Service.MOWING:
        key = resolve_package(package)
        pkg = PACKAGES[key]
        if not lawn_sqft:
            raise LawnSizeError("Enter your lawn size in square feet.")
        sqft = int(lawn_sqft)
        base = money(zone.mow_rate)          # charged once per visit
        extras = priced_add_ons(add_ons)
        extra_total = sum((a["price"] for a in extras if a["price"] is not None), Decimal(0))   # quotes are free
        subtotal = money(base + pkg["rate"] * sqft) + extra_total
        tax, total = with_tax(subtotal, rate)
        return Quote(subtotal, rate, tax, total, sqft, "base_plus_sqft", key, pkg["rate"], base,
                     pkg["giving"], money(subtotal * pkg["giving"]), extras, extra_total)
    if on_site_price is not None:
        subtotal = money(on_site_price)
        tax, total = with_tax(subtotal, rate)
        return Quote(subtotal, rate, tax, total, None, "set_on_site")
    return Quote(None, rate, None, None, None, "on_site")
