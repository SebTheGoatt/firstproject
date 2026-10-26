"""Prices, lawn sizes, rate tiers and Texas sales tax.

Mowing (every booking made from the booking form): the YIELD ENGINE below.
          $75 base for up to 5,000 sq ft, +8% for each started 1,000 sq ft over that,
          x1.15 for lots of trees/beds or x1.25 for steep slopes (the customer's yard type),
          minus a route-density discount for other bookings already within half a mile
          (2-4 nearby: 5%, 5 or more: 10%), plus add-ons, plus the area's sales tax.
          2% of the subtotal goes to the cause the customer picks (YIELD_GIVING_RATE).
          The yard type and density are saved on the booking (as "info" entries in add_ons),
          so a re-measure on site re-prices with the same choices.

Older bookings and API callers that send a `package` keep the tier brackets below:
Mowing:   a flat price per visit from the lawn-size bracket and the tier the customer picks
          (PRICE_BRACKETS below). Each price already includes the $35 operational base; it is
          shown as its own line and the rest as "Precision Turf Maintenance Profile".
                         <= 3,500   3,501-7,500   7,501-15,000   > 15,000 sq ft
            Block Lock      $75        $105          $138           $192
            Operational     $83        $114          $151           $211
            Bi-Weekly       $94        $131          $184           $232
          No per-square-foot rate is shown to customers. Older bookings priced per sq ft keep
          their stored price. The tiers are prices only; the work is the same. Each tier also gives a
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
    "standard":  {"label": "Neighborhood Block Lock", "rate": Decimal("0.009"), "giving": Decimal("0.02"),
                  "description": "Our most affordable per-visit rate."},
    "supporter": {"label": "Operational Target",      "rate": Decimal("0.010"), "giving": Decimal("0.07"),
                  "description": "Our standard per-visit rate for most lawns."},
    "hero":      {"label": "Bi-Weekly Demand",        "rate": Decimal("0.012"), "giving": Decimal("0.12"),
                  "description": "For lawns that need a visit every two weeks in peak season. Still billed per visit."},
}
# Flat per-visit price (before tax, $35 base included) by lawn size: (largest sq ft in bracket, price per tier).
# The last bracket has no upper limit (MAX_SQFT still applies; bigger lots are quoted in person).
PRICE_BRACKETS: tuple[tuple[int | None, dict[str, Decimal]], ...] = (
    (3_500,  {"standard": Decimal("75.00"),  "supporter": Decimal("83.00"),  "hero": Decimal("94.00")}),
    (7_500,  {"standard": Decimal("105.00"), "supporter": Decimal("114.00"), "hero": Decimal("131.00")}),
    (15_000, {"standard": Decimal("138.00"), "supporter": Decimal("151.00"), "hero": Decimal("184.00")}),
    (None,   {"standard": Decimal("192.00"), "supporter": Decimal("211.00"), "hero": Decimal("232.00")}),
)
# Name of each size bracket, in the same order (shown on the booking summary and sent to Stripe).
BRACKET_PROFILES = ("Compact Lot Profile", "Standard Suburb Profile", "Large Lot Profile", "Estate Parcel Profile")
assert len(BRACKET_PROFILES) == len(PRICE_BRACKETS)


def bracket_label(lawn_sqft: int | None) -> str:
    """The lawn-size bracket in words ("3,501-7,500 sq ft"), for receipts and payment records."""
    if not lawn_sqft:
        return "Size set on site"
    low = 0
    for limit, _ in PRICE_BRACKETS:
        if limit is None:
            return f"Over {low:,} sq ft"
        if lawn_sqft <= limit:
            return f"Up to {limit:,} sq ft" if low == 0 else f"{low + 1:,}-{limit:,} sq ft"
        low = limit
    raise AssertionError("unreachable")


def bracket_profile(lawn_sqft: int | None) -> str:
    """The lawn-size bracket by name ("Standard Suburb Profile")."""
    if not lawn_sqft:
        return "Size set on site"
    return next(name for (limit, _), name in zip(PRICE_BRACKETS, BRACKET_PROFILES) if limit is None or lawn_sqft <= limit)


def bracket_price(lawn_sqft: int, package: str) -> Decimal:
    """The flat mowing price (before tax, base included) for this lawn size and tier."""
    for limit, prices in PRICE_BRACKETS:
        if limit is None or lawn_sqft <= limit:
            return prices[package]
    raise AssertionError("unreachable")


DEFAULT_PACKAGE = "standard"        # only for old bookings without a package; the booking form pre-selects FEATURED_PACKAGE
FEATURED_PACKAGE = "supporter"      # Operational Target: pre-selected and highlighted on the booking form
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
    # What to mow (pick one). No charge of their own: they set the lawn size the server prices, and they
    # lock the price (the crew mows the area booked; no on-site re-measuring). They show on the crew's stop.
    # Pay for a neighbor in need: a full-price mow, paid by this customer, done for a nominated neighbor on their own
    # area day (app/community.py). Taxed like any mow; no time on this stop. Must equal YIELD_BASE (tests check it).
    "sponsor_mow":    {"label": "Sponsor a neighbor's mow",  "price": Decimal("75.00"), "minutes": 0, "sponsor": True},
    "scope_yard":     {"label": "Yard only",                 "price": Decimal("0.00"), "minutes": 0, "scope": True},
    "scope_full":     {"label": "Full property",             "price": Decimal("0.00"), "minutes": 0, "scope": True},
}
SCOPES = tuple(k for k, a in ADD_ONS.items() if a.get("scope"))


def mow_minutes(lawn_sqft: int | None) -> int:
    """On-site time for the mow, scaled by lawn size: ~45 min for a 4,500 sq ft yard, ~90 min for 14,500.
    Feeds route ETAs and the crew dashboard's route time. Never less than the standard 45 minutes."""
    if not lawn_sqft:
        return 45
    return max(45, round(25 + lawn_sqft * 0.0045))


def scope_of(add_ons) -> str | None:
    """The booking's 'what to mow' choice, from add-on keys or stored add-on dicts."""
    keys = [a["key"] if isinstance(a, dict) else a for a in (add_ons or [])]
    return next((k for k in keys if k in SCOPES), None)


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
    basis: str                    # "bracket" | "on_site" | "set_on_site" (older bookings: "base_plus_sqft")
    package: str | None = None    # mowing: standard | supporter | hero
    sqft_rate: Decimal | None = None
    base_fee: Decimal | None = None
    charity_rate: Decimal | None = None
    charity_amount: Decimal | None = None   # part of the subtotal the business gives away
    add_ons: tuple = ()                     # ({"key", "label", "price"}, ...)
    add_on_total: Decimal = Decimal(0)
    # Yield engine only:
    yard_type: str | None = None            # STANDARD | COMPLEX_OBSTACLES | STEEP_SLOPES
    mow_fee: Decimal | None = None          # base x size x yard type, before the density discount
    density_stops: int = 0                  # bookings already within half a mile
    density_discount: Decimal = Decimal(0)

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
                "lot_profile": bracket_profile(self.lawn_sqft) if self.lawn_sqft else None,
                "sqft_rate": f(self.sqft_rate), "base_fee": f(self.base_fee),
                "charity_rate": f(self.charity_rate), "charity_amount": f(self.charity_amount),
                "business_net": f(self.business_net), "mow_price": f(self.mow_price),
                "add_ons": [{**a, "price": f(a["price"])} for a in self.add_ons],
                "add_on_total": float(self.add_on_total),
                "yard_type": self.yard_type, "yard_type_label": YARD_TYPES[self.yard_type]["label"] if self.yard_type else None,
                "mow_fee": f(self.mow_fee), "density_stops": self.density_stops,
                "density_discount": float(self.density_discount), "price_locked": scope_of(self.add_ons) is not None}


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
    if len(chosen & set(SCOPES)) > 1:
        raise ValueError("Choose one: yard only or full property.")
    return tuple({"key": k, "label": a["label"], "price": a["price"], **({"quote": True} if a.get("quote") else {}),
                  **({"scope": True} if a.get("scope") else {})}
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


# ---------- Yield engine (the price for every booking-form booking) ----------
YIELD_BASE = Decimal("75.00")          # covers up to YIELD_INCLUDED_SQFT
YIELD_INCLUDED_SQFT = 5_000
YIELD_STEP = Decimal("0.08")           # +8% per started 1,000 sq ft over that
YIELD_GIVING_RATE = Decimal("0.02")    # share of the subtotal for the customer's cause
DENSITY_RADIUS_M = 805                 # half a mile
YARD_TYPES = {
    "STANDARD":          {"label": "Standard yard",         "mult": Decimal("1.00")},
    "COMPLEX_OBSTACLES": {"label": "Lots of trees or beds", "mult": Decimal("1.15")},
    "STEEP_SLOPES":      {"label": "Steep slopes",          "mult": Decimal("1.25")},
}


def yield_mow_fee(lawn_sqft: int, yard_type: str) -> Decimal:
    over = max(0, int(lawn_sqft) - YIELD_INCLUDED_SQFT)
    size = 1 + -(-over // 1000) * YIELD_STEP
    return money(YIELD_BASE * size * YARD_TYPES[yard_type]["mult"])


def density_pct(nearby: int) -> Decimal:
    return Decimal("0.10") if nearby >= 5 else Decimal("0.05") if nearby >= 2 else Decimal(0)


def count_nearby(points, lat: float, lng: float) -> int:
    """Bookings already on the books within half a mile of this address."""
    from .routing.matrix import haversine_m
    return sum(1 for p in points if haversine_m(p, (lat, lng)) <= DENSITY_RADIUS_M)


def is_info(a) -> bool:
    """Saved pricing notes (yard type, density discount) ride in add_ons but aren't add-ons."""
    return isinstance(a, dict) and bool(a.get("info"))


def real_add_ons(add_ons) -> list:
    return [a for a in (add_ons or []) if not is_info(a)]


def yield_choice(add_ons) -> tuple[str, int] | None:
    """(yard type, nearby stops) saved on a yield-priced booking, or None for older bookings."""
    notes = {a["key"]: a for a in (add_ons or []) if is_info(a)}
    if "yard_type" not in notes:
        return None
    return notes["yard_type"]["value"], int(notes.get("route_density", {}).get("stops", 0))


def yield_notes(yard_type: str, nearby: int, discount: Decimal) -> tuple:
    notes = [{"key": "yard_type", "label": f"Yard type: {YARD_TYPES[yard_type]['label']}", "price": None,
              "info": True, "value": yard_type}]
    notes.append({"key": "route_density", "label": f"Neighbor discount ({nearby} booked nearby)" if discount
                  else "No neighbors booked nearby yet", "price": None, "info": True,
                  "stops": nearby, "amount": float(-discount)})
    return tuple(notes)


def quote(zone: ServiceZone, service: Service, lawn_sqft: int | None = None,
          on_site_price: float | None = None, package: str | None = None, add_ons=(),
          yard_type: str | None = None, nearby: int = 0) -> Quote:
    """Price a visit. `on_site_price` is the crew's pre-tax price for quoted services;
    `yard_type` prices mowing with the yield engine (with `nearby` bookings for the density discount);
    otherwise `package` prices it with the older tier brackets. `add_ons` are ADD_ONS keys."""
    rate = Decimal(str(zone.tax_rate))
    if service is Service.MOWING and yard_type is not None:
        if yard_type not in YARD_TYPES:
            raise ValueError("Choose your yard type: standard, lots of trees or beds, or steep slopes.")
        if not lawn_sqft:
            raise LawnSizeError("Enter your lawn size in square feet.")
        sqft = int(lawn_sqft)
        fee = yield_mow_fee(sqft, yard_type)
        discount = money(fee * density_pct(nearby))
        extras = priced_add_ons([k for k in add_ons if not is_info(k)])
        extra_total = sum((a["price"] for a in extras if a["price"] is not None), Decimal(0))
        subtotal = fee - discount + extra_total
        tax, total = with_tax(subtotal, rate)
        return Quote(subtotal, rate, tax, total, sqft, "yield", None, None, YIELD_BASE,
                     YIELD_GIVING_RATE, money(subtotal * YIELD_GIVING_RATE), extras + yield_notes(yard_type, nearby, discount),
                     extra_total, yard_type, fee, nearby, discount)
    if service is Service.MOWING:
        key = resolve_package(package)
        pkg = PACKAGES[key]
        if not lawn_sqft:
            raise LawnSizeError("Enter your lawn size in square feet.")
        sqft = int(lawn_sqft)
        base = money(zone.mow_rate)          # charged once per visit
        extras = priced_add_ons(add_ons)
        extra_total = sum((a["price"] for a in extras if a["price"] is not None), Decimal(0))   # quotes are free
        subtotal = bracket_price(sqft, key) + extra_total
        tax, total = with_tax(subtotal, rate)
        return Quote(subtotal, rate, tax, total, sqft, "bracket", key, None, base,
                     pkg["giving"], money(subtotal * pkg["giving"]), extras, extra_total)
    if on_site_price is not None:
        subtotal = money(on_site_price)
        tax, total = with_tax(subtotal, rate)
        return Quote(subtotal, rate, tax, total, None, "set_on_site")
    return Quote(None, rate, None, None, None, "on_site")
