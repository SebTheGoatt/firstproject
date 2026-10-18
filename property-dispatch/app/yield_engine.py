"""Yield pricing engine (owner's spec): size scaling, complexity, route-density discount, add-ons, tax.

    POST /api/v1/calculate-yield-price    price breakdown for a lot (saves nothing)
    GET  /estimate                        the calculator page (static/estimate.html + static/yield-engine.js)

Density: upcoming bookings within half a mile of the address, counted from the real booking list
(the TODO in the original spec). 5+ nearby: 10% off; 2-4: 5% off; otherwise no discount.
Money is rounded half-up to the cent at each step, like the rest of the app.
"""

import logging
import math
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from .booking import local_now
from .routing.matrix import haversine_m

log = logging.getLogger(__name__)

# Enterprise Pricing Constraints
BASE_DEPLOYMENT_FEE = 75.00   # Asset deployment floor price
TARGET_MARGIN = 0.32          # 32% structural operating margin
TEXAS_SALES_TAX_RATE = 0.0825 # 8.25% localized tax bracket
DENSITY_RADIUS_M = 805        # half a mile
COMPLEXITY_MULTIPLIERS = {
    "STANDARD": 1.0,
    "COMPLEX_OBSTACLES": 1.15,  # 15% mark up for heavy trees/beds
    "STEEP_SLOPES": 1.25,       # 25% mark up for safety/time risk
}


class PricingRequest(BaseModel):
    street_address: str
    latitude: float
    longitude: float
    lot_size_sqft: float
    complexity_rating: str  # 'STANDARD', 'COMPLEX_OBSTACLES', 'STEEP_SLOPES'
    has_bin_cleaning: bool
    has_gutter_cleaning: bool


class PricingResponse(BaseModel):
    base_mow_fee: float
    density_discount: float
    addons_total: float
    subtotal: float
    sales_tax: float
    final_checkout_total: float
    route_density_score: int
    is_cluster_optimized: bool


def cents(x) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def calculate_route_density(points: list[tuple[float, float]], lat: float, lon: float) -> tuple[int, float]:
    """Active stops already booked within a 0.5-mile geofence of this address."""
    nearby = sum(1 for p in points if haversine_m(p, (lat, lon)) <= DENSITY_RADIUS_M)
    if nearby >= 5:
        density_discount_pct = 0.10  # 10% Cluster optimization discount
    elif nearby >= 2:
        density_discount_pct = 0.05  # 5% Route compression bonus
    else:
        density_discount_pct = 0.00  # Standalone premium zone
    return nearby, density_discount_pct


def yield_price(payload: PricingRequest, points: list[tuple[float, float]]) -> PricingResponse:
    # 1. Size-Based Scaling Economics: base covers up to 5,000 sqft, +8% per additional 1k sqft.
    standard_threshold = 5000.0
    size_multiplier = 1.0
    if payload.lot_size_sqft > standard_threshold:
        excess_size = payload.lot_size_sqft - standard_threshold
        size_multiplier += math.ceil(excess_size / 1000.0) * 0.08

    # 2. Complexity Adjustments
    complexity_mult = COMPLEXITY_MULTIPLIERS.get(payload.complexity_rating, 1.0)
    calculated_mow_fee = cents(BASE_DEPLOYMENT_FEE * size_multiplier * complexity_mult)

    # 3. Route density
    stops_count, discount_pct = calculate_route_density(points, payload.latitude, payload.longitude)
    density_discount = cents(calculated_mow_fee * discount_pct)

    # 4. Add-ons
    addons_total = 0.0
    if payload.has_bin_cleaning:
        addons_total += 15.00
    if payload.has_gutter_cleaning:
        addons_total += 15.00

    # 5. Ledger
    subtotal = cents(calculated_mow_fee - density_discount + addons_total)
    sales_tax = cents(subtotal * TEXAS_SALES_TAX_RATE)
    return PricingResponse(
        base_mow_fee=calculated_mow_fee, density_discount=density_discount, addons_total=addons_total,
        subtotal=subtotal, sales_tax=sales_tax, final_checkout_total=cents(subtotal + sales_tax),
        route_density_score=stops_count, is_cluster_optimized=discount_pct > 0)


def register_yield_engine(app: FastAPI, settings, page) -> None:
    @app.post("/api/v1/calculate-yield-price", response_model=PricingResponse)
    def calculate_yield_price(payload: PricingRequest, request: Request):
        try:
            today: date = local_now(settings).date()
            return yield_price(payload, request.app.state.repo.active_job_points(today))
        except Exception:
            log.exception("Yield engine failed")
            raise HTTPException(status_code=500, detail="Infrastructure Engine Fault")

    @app.get("/estimate", include_in_schema=False)
    def estimate_page():
        resp = page("estimate.html")
        resp.headers["X-Robots-Tag"] = "noindex"   # not linked or indexed until the owner switches booking to it
        return resp
