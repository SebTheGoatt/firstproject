"""Request/response models and domain types."""

import re
from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Service(str, Enum):
    MOWING = "mowing"
    BIN_CLEANING = "bin_cleaning"
    GUTTERS = "gutters"


# On-site minutes per service; feeds the ETA calculation.
SERVICE_MINUTES: dict[Service, int] = {
    Service.MOWING: 45,
    Service.BIN_CLEANING: 15,
    Service.GUTTERS: 60,
}

SERVICE_LABELS: dict[Service, str] = {
    Service.MOWING: "Mowing",
    Service.BIN_CLEANING: "Bin Cleaning",
    Service.GUTTERS: "Gutters",
}

# Add-ons to a mowing visit (prices and minutes in app/pricing.py).
AddOn = Literal["bin_cleaning", "gutters", "holiday_lights", "scope_yard", "scope_full"]


def order_label(service: str, add_ons: list | None = None) -> str:
    """'Mowing + Gutter cleaning + Holiday lighting quote' for a booking with add-ons."""
    parts = [SERVICE_LABELS[Service(service)]] + [a["label"] for a in (add_ons or [])]
    return " + ".join(parts)


def normalize_us_phone(raw: str) -> str:
    """Return an E.164 US number (+1XXXXXXXXXX) or raise ValueError."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] in "01":
        raise ValueError("Enter a valid 10-digit US phone number")
    return f"+1{digits}"


# Mowing packages (rates and charity giving are in app/pricing.py).
Package = Literal["standard", "supporter", "hero"]


class JobRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str
    address: str = Field(min_length=5, max_length=300)
    service: Service = Service.MOWING   # every booking is a mow; bins, gutters, lights are add_ons
    scheduled_date: date
    payment_method: Literal["cash", "card"] = "cash"
    # Coordinates from the Google address dropdown, when the customer used it.
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    # Mowing: the customer's lawn size in square feet and their chosen rate tier. Both are
    # required and checked on the server (app/pricing.py); the price is always recalculated here.
    lawn_sqft: int | None = None
    package: Package | None = None   # standard | supporter (Plus) | hero (Premium)
    lang: Literal["en", "es"] = "en"  # the customer's language, for their texts
    add_ons: list[AddOn] = Field(default_factory=list, max_length=4)

    @field_validator("name", "address")
    @classmethod
    def strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Required")
        return v

    @field_validator("address")
    @classmethod
    def needs_house_number(cls, v: str) -> str:
        if not re.match(r"^\s*\d+", v):
            raise ValueError("Please include your house number, e.g. 4726 Whispering Rock Ln, Spring, TX 77388")
        return v

    @field_validator("phone")
    @classmethod
    def phone_e164(cls, v: str) -> str:
        return normalize_us_phone(v)


class JobCreated(BaseModel):
    id: str
    scheduled_date: date
    service: Service
    formatted_address: str
    lat: float
    lng: float
    zone_name: str
    quoted_price: float | None  # mowing only; other services are quoted on site
    payment_method: Literal["cash", "card"] = "cash"
    pay_url: str | None = None  # card customers: their private payment page
    access_code: str | None = None  # e.g. "K7MX-3QPA": opens the customer's visit page
    visit_url: str | None = None
    # Price breakdown (None = priced on site). total = subtotal + tax.
    lawn_sqft: int | None = None
    package: str | None = None
    add_ons: list[dict] = Field(default_factory=list)
    add_on_total: float = 0.0
    sqft_rate: float | None = None
    charity_rate: float | None = None     # share of the price the business gives to charity
    charity_amount: float | None = None
    subtotal: float | None = None
    tax_rate: float | None = None
    tax: float | None = None
    total: float | None = None


class GeoPoint(BaseModel):
    lat: float
    lng: float
    formatted_address: str
    precision: str = "address"  # "address" = the house itself; "street" = somewhere on the street


class Job(BaseModel):
    """A job as the routing engine sees it."""

    id: str
    customer_name: str
    phone: str
    address: str
    lat: float
    lng: float
    service: Service
    service_minutes: int
    status: str


class StopView(BaseModel):
    """One stop on the crew dashboard."""

    stop_id: str
    job_id: str
    sequence: int
    customer_name: str
    phone: str
    address: str
    lat: float
    lng: float
    service: Service
    service_label: str
    service_minutes: int | None = None   # planned time on site (for the dashboard's route-time estimate)
    scope: Literal["scope_yard", "scope_full"] | None = None   # what the customer booked; None = older booking
    eta: datetime | None
    leg_distance_m: int
    leg_duration_s: int
    completed_at: datetime | None
    completed_by_name: str | None = None
    notified_at: datetime | None = None   # when the customer was told the crew is on the way
    google_maps_url: str
    apple_maps_url: str
    payment_method: Literal["cash", "card"] = "cash"
    payment_status: Literal["unpaid", "paid"] = "unpaid"
    amount_due: float | None = None
    amount_paid: float | None = None
    donation: float = 0.0
    subtotal: float | None = None
    tax_rate: float | None = None
    tax_amount: float | None = None
    lawn_sqft: int | None = None
    package: str | None = None       # mowing: the customer's package
    add_ons: list[dict] = Field(default_factory=list)   # [{"key", "label", "price"}]: bring the gear
    add_on_total: float = 0.0
    sqft_rate: float | None = None
    charity_rate: float | None = None
    charity_amount: float | None = None
    flat_fee: float | None = None   # mowing minimum for this stop's area (for the crew's live price)


class RouteView(BaseModel):
    route_date: date
    timezone: str
    total_distance_m: int
    total_duration_s: int
    matrix_source: str
    optimized_at: datetime | None
    stops: list[StopView]
    full_route_google_urls: list[str]


# ---------- Crew profiles ----------------------------------------------
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class CrewProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=60)
    role_title: str | None = Field(default=None, max_length=60)
    bio: str | None = Field(default=None, max_length=1200)
    years_experience: int | None = Field(default=None, ge=0, le=80)
    specialties: list[str] | None = Field(default=None, max_length=8)
    service_branch: str | None = Field(default=None, max_length=60)
    accent_color: str | None = None

    @field_validator("display_name", "role_title", "bio", "service_branch")
    @classmethod
    def strip_text(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v

    @field_validator("specialties")
    @classmethod
    def clean_specialties(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        out = [s.strip()[:40] for s in v if s and s.strip()]
        return list(dict.fromkeys(out))  # de-duplicate, keep order

    @field_validator("accent_color")
    @classmethod
    def hex_color(cls, v: str | None) -> str | None:
        if v is not None and not HEX_COLOR.match(v):
            raise ValueError("Pick a color like #2f7d4f")
        return v


class CompleteStopRequest(BaseModel):
    price: float | None = Field(default=None, gt=0, le=5000)          # quoted services: price before tax
    amount_due: float | None = Field(default=None, gt=0, le=5000)     # older crew app: same as `price`
    lawn_sqft: int | None = Field(default=None, ge=100, le=200_000)    # mowing: corrected lawn size
    cash_collected: float | None = Field(default=None, ge=0, le=10000)  # total cash handed to the crew


class OptimizeRouteRequest(BaseModel):
    """Crew dashboard: re-plan the open stops from where the crew is now. GPS is optional."""
    day: date | None = None                                      # default: today (business time zone)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


class StopNote(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class AddressCheck(BaseModel):
    address: str = Field(min_length=5, max_length=300)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


class QuoteRequest(BaseModel):
    address: str = Field(min_length=5, max_length=300)
    service: Service = Service.MOWING
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    lawn_sqft: int | None = None
    package: Package | None = None
    add_ons: list[AddOn] = Field(default_factory=list, max_length=4)
    scheduled_date: date | None = None   # seasonal add-ons depend on the day
