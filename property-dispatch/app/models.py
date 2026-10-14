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


def normalize_us_phone(raw: str) -> str:
    """Return an E.164 US number (+1XXXXXXXXXX) or raise ValueError."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] in "01":
        raise ValueError("Enter a valid 10-digit US phone number")
    return f"+1{digits}"


class JobRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str
    address: str = Field(min_length=5, max_length=300)
    service: Service
    scheduled_date: date
    payment_method: Literal["cash", "card"] = "cash"
    # Coordinates from the Google address dropdown, when the customer used it.
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)

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
    eta: datetime | None
    leg_distance_m: int
    leg_duration_s: int
    completed_at: datetime | None
    completed_by_name: str | None = None
    google_maps_url: str
    apple_maps_url: str
    payment_method: Literal["cash", "card"] = "cash"
    payment_status: Literal["unpaid", "paid"] = "unpaid"
    amount_due: float | None = None
    amount_paid: float | None = None
    donation: float = 0.0


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
    amount_due: float | None = Field(default=None, gt=0, le=5000)       # final price for quoted services
    cash_collected: float | None = Field(default=None, ge=0, le=10000)  # total cash handed to the crew


class AddressCheck(BaseModel):
    address: str = Field(min_length=5, max_length=300)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
