"""Prices, lawn sizes, package giving and Texas sales tax.

Mowing:   price = $50 base trip fee + (the package's rate × square feet of lawn).
          The customer picks a package; each gives part of the price to charity:
            Standard   0.9¢ / sq ft,  2% of the price to charity
            Supporter  1.0¢ / sq ft,  7% of the price to charity
            Hero       1.1¢ / sq ft, 12% of the price to charity
          The giving comes out of what the business keeps; the customer pays the
          price + tax, nothing extra. It's split between the three causes in
          app/charity.py, like voluntary donations.
Bins/gutters: priced on site by the crew; tax is added the same way (no package).
Tax:      the area's combined Texas rate (state 6.25% + local) on the whole service
          price, rounded to the cent. Voluntary donations are separate and untaxed.

All money math uses Decimal so totals never drift by a cent.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .models import Service
from .zones import ServiceZone

# key → per-square-foot rate and the share of the price given to charity.
PACKAGES: dict[str, dict] = {
    "standard":  {"label": "Standard Tier",       "rate": Decimal("0.009"), "giving": Decimal("0.02")},
    "supporter": {"label": "Community Supporter", "rate": Decimal("0.010"), "giving": Decimal("0.07")},
    "hero":      {"label": "Impact Champion",     "rate": Decimal("0.011"), "giving": Decimal("0.12")},
}
DEFAULT_PACKAGE = "standard"
MIN_SQFT, MAX_SQFT = 200, 87_120  # up to 2 acres; bigger jobs are quoted in person

# Size picker shown at booking. `sqft` is the representative size we price on;
# the crew confirms the real size on site before anything is charged.
LAWN_SIZES: dict[str, dict] = {
    "small":  {"label": "Small",  "range": "up to 3,000 sq ft",    "sqft": 2_500,  "example": "Townhome or small yard"},
    "medium": {"label": "Medium", "range": "3,000–6,000 sq ft",    "sqft": 4_500,  "example": "Typical subdivision lot"},
    "large":  {"label": "Large",  "range": "6,000–10,000 sq ft",   "sqft": 8_000,  "example": "Corner or oversized lot"},
    "xl":     {"label": "X-Large", "range": "10,000–15,000 sq ft", "sqft": 12_500, "example": "Quarter-acre or more"},
}
DEFAULT_SIZE = "medium"  # no size given → priced as a typical lot; the crew confirms on site

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
                "business_net": f(self.business_net)}


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


def quote(zone: ServiceZone, service: Service, lawn_sqft: int | None = None,
          on_site_price: float | None = None, package: str | None = None) -> Quote:
    """Price a visit. `on_site_price` is the crew's pre-tax price for quoted services;
    `package` is the customer's mowing package (see PACKAGES)."""
    rate = Decimal(str(zone.tax_rate))
    if service is Service.MOWING:
        key = resolve_package(package)
        pkg = PACKAGES[key]
        sqft = lawn_sqft or LAWN_SIZES[DEFAULT_SIZE]["sqft"]
        base = money(zone.mow_rate)
        subtotal = money(base + pkg["rate"] * sqft)
        tax, total = with_tax(subtotal, rate)
        return Quote(subtotal, rate, tax, total, sqft, "base_plus_sqft", key, pkg["rate"], base,
                     pkg["giving"], money(subtotal * pkg["giving"]))
    if on_site_price is not None:
        subtotal = money(on_site_price)
        tax, total = with_tax(subtotal, rate)
        return Quote(subtotal, rate, tax, total, None, "set_on_site")
    return Quote(None, rate, None, None, None, "on_site")
