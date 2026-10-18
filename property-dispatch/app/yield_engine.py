"""Yield pricing engine (owner's spec): size scaling, complexity, route-density discount, add-ons, tax.

    POST /api/v1/calculate-yield-price    price breakdown for a lot (saves nothing)
    GET  /estimate                        the calculator page (static/estimate.html + static/yield-engine.js)

This is the price booking and Stripe charge: the math is in app/pricing.py (yield engine), so the
estimate page and the booking form can never disagree. Density counts real upcoming bookings within
half a mile. Money is rounded half-up to the cent, like the rest of the app.
"""

import logging
from datetime import date
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from .booking import local_now
from .models import Service
from .pricing import YARD_TYPES, count_nearby, quote
from .zones import find_zone

log = logging.getLogger(__name__)

# Enterprise Pricing Constraints (the numbers live in app/pricing.py, which booking and Stripe use too)
TEXAS_SALES_TAX_RATE = 0.0825 # 8.25% localized tax bracket (outside our areas; inside, the area's own rate)


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


def yield_price(payload: PricingRequest, points: list[tuple[float, float]]) -> PricingResponse:
    """The same yield engine the booking form charges (app/pricing.py quote)."""
    zone = find_zone(payload.latitude, payload.longitude)
    tax_rate = zone.tax_rate if zone else TEXAS_SALES_TAX_RATE
    q = quote(SimpleNamespace(tax_rate=tax_rate), Service.MOWING, max(1, round(payload.lot_size_sqft)),
              yard_type=payload.complexity_rating if payload.complexity_rating in YARD_TYPES else "STANDARD",
              nearby=count_nearby(points, payload.latitude, payload.longitude),
              add_ons=[k for k, on in (("bin_cleaning", payload.has_bin_cleaning), ("gutters", payload.has_gutter_cleaning)) if on])
    return PricingResponse(
        base_mow_fee=float(q.mow_fee), density_discount=float(q.density_discount), addons_total=float(q.add_on_total),
        subtotal=float(q.subtotal), sales_tax=float(q.tax), final_checkout_total=float(q.total),
        route_density_score=q.density_stops, is_cluster_optimized=q.density_discount > 0)


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
