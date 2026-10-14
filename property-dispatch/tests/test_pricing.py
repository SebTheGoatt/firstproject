"""Square-footage pricing, Texas sales tax, Plum Grove, and the Stripe line items."""

from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
import pytest

from app.models import Service
from app.nightly import run_nightly
from app.payments import StripeClient
from app.pricing import LAWN_SIZES, quote, resolve_sqft
from app.zones import SERVICE_ZONES, ServiceZone, find_zone, validate_zones, zone_by_key

from .test_api_flow import CREW, NOW, TOMORROW

SPRING = zone_by_key("SPRING_LUXURY_LOOP")   # $55 flat fee


@pytest.mark.parametrize("sqft, subtotal, basis", [
    (2_500, "55.00", "flat"),        # 2,500 × 1.5¢ = $37.50 < $55 → flat fee
    (3_666, "55.00", "flat"),        # $54.99 < $55
    (3_667, "55.01", "per_sqft"),    # $55.005 → $55.01
    (4_500, "67.50", "per_sqft"),
    (8_000, "120.00", "per_sqft"),
])
def test_mowing_is_flat_fee_or_per_sqft_whichever_is_higher(sqft, subtotal, basis):
    q = quote(SPRING, Service.MOWING, sqft)
    assert (q.subtotal, q.basis) == (Decimal(subtotal), basis)


def test_texas_sales_tax_rounds_to_the_cent():
    q = quote(SPRING, Service.MOWING, 4_500)          # $67.50 × 8.25% = $5.56875
    assert (q.tax, q.total, q.tax_rate) == (Decimal("5.57"), Decimal("73.07"), Decimal("0.0825"))
    g = quote(SPRING, Service.GUTTERS, on_site_price=120)
    assert (g.subtotal, g.tax, g.total) == (Decimal("120.00"), Decimal("9.90"), Decimal("129.90"))
    assert quote(SPRING, Service.BIN_CLEANING).total is None   # priced on site


def test_lawn_size_picker_and_limits():
    assert resolve_sqft("medium", None) == LAWN_SIZES["medium"]["sqft"] == 4_500
    assert resolve_sqft("small", 6_100) == 6_100        # an exact number wins
    assert resolve_sqft(None, 50) == 200 and resolve_sqft(None, 500_000) == 87_120
    assert resolve_sqft(None, None) is None


@pytest.mark.parametrize("lat, lng, place", [
    (30.2147, -95.0949, "Plum Grove city center"),
    (30.2000, -95.1080, "Plum Grove, west side"),
    (30.1750, -95.0900, "Plum Grove, south side"),
])
def test_plum_grove_is_in_the_cleveland_sector(lat, lng, place):
    z = find_zone(lat, lng)
    assert z.key == "CLEVELAND_HUB" and z.mow_rate == 45.0, place


def test_new_caney_and_splendora_unchanged_by_plum_grove():
    for lat, lng in ((30.2330, -95.1610), (30.2270, -95.2359)):   # Splendora, The Canopies
        assert find_zone(lat, lng).key == "I69_HIGH_DENSITY_SPINE"


def test_every_zone_has_a_sane_tax_rate_and_no_overlaps():
    validate_zones(SERVICE_ZONES)
    assert all(z.tax_rate == 0.0825 for z in SERVICE_ZONES)
    a = ServiceZone("A", "a", (-95.2, 30.1, -95.1, 30.2), 50.0)
    b = ServiceZone("B", "b", (-95.6, 30.5, -95.5, 30.6), 40.0, extra_boxes=((-95.15, 30.15, -95.05, 30.25),))
    with pytest.raises(ValueError, match="overlap"):
        validate_zones((a, b))
    with pytest.raises(ValueError, match="tax_rate"):
        validate_zones((ServiceZone("C", "c", (-95.2, 30.1, -95.1, 30.2), 50.0, tax_rate=8.25),))


# ---------- API ----------
def post_job(client, **extra):
    with patch("app.main.local_now", return_value=NOW):
        return client.post("/api/jobs", json={"name": "Pat Doe", "phone": "2815550100", "address": "100 A Example Rd",
                                              "service": "mowing", "scheduled_date": TOMORROW.isoformat(), **extra})


def test_live_quote_endpoint(client):
    r = client.post("/api/quote", json={"address": "100 A Example Rd", "service": "mowing", "lawn_size": "large"}).json()
    assert (r["in_area"], r["subtotal"], r["tax"], r["total"], r["lawn_sqft"], r["basis"]) == \
        (True, 120.0, 9.9, 129.9, 8_000, "per_sqft")
    r = client.post("/api/quote", json={"address": "100 A Example Rd", "service": "gutters"}).json()
    assert r["total"] is None and r["basis"] == "on_site" and r["tax_rate"] == 0.0825
    r = client.post("/api/quote", json={"address": "100 Old Town Rd", "service": "mowing"}).json()
    assert r["in_area"] is False


def test_booking_saves_the_breakdown(client, repo):
    r = post_job(client, lawn_size="medium").json()
    assert (r["lawn_sqft"], r["subtotal"], r["tax"], r["total"]) == (4_500, 67.5, 5.57, 73.07)
    job = repo.jobs[r["id"]]
    assert (job["amount_due"], job["subtotal"], job["tax_amount"], job["tax_rate"]) == (73.07, 67.5, 5.57, 0.0825)
    r = post_job(client, lawn_sqft=2_000, phone="2815550101").json()
    assert (r["subtotal"], r["total"]) == (55.0, 59.54)          # small lawn → flat-fee minimum


def test_crew_corrects_lawn_size_on_site(client, repo, settings):
    job = post_job(client, lawn_size="medium").json()            # booked as 4,500 sq ft → $73.07
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    assert (stop["lawn_sqft"], stop["subtotal"], stop["amount_due"]) == (4_500, 67.5, 73.07)
    # Actually 8,000 sq ft: $120 + $9.90 tax = $129.90. Cash below the new total is refused...
    bad = client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"lawn_sqft": 8_000, "cash_collected": 100})
    assert bad.status_code == 422 and "129.90" in bad.json()["detail"]
    assert repo.jobs[job["id"]]["amount_due"] == 73.07            # ...and nothing was changed
    ok = client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"lawn_sqft": 8_000, "cash_collected": 130}).json()
    assert ok["payment"]["total"] == 129.9 and ok["payment"]["donation"] == 0.1
    j = repo.jobs[job["id"]]
    assert (j["lawn_sqft"], j["subtotal"], j["tax_amount"], j["amount_due"]) == (8_000, 120.0, 9.9, 129.9)


def test_stripe_checkout_lines_split_price_tax_and_untaxed_donation(settings):
    sent = {}

    def handler(req):
        sent.update({k: v[0] for k, v in parse_qs(req.content.decode()).items()})
        return httpx.Response(200, json={"id": "cs_1", "url": "https://checkout.stripe.test/1"})

    settings.stripe_secret_key = "sk_test"
    StripeClient(settings, httpx.Client(transport=httpx.MockTransport(handler))).create_checkout(
        job_id="j1", service_label="Mowing", service_date="2026-10-15", amount_due=73.07, donation=10.0,
        success_url="https://x/ok", cancel_url="https://x/no", subtotal=67.5, tax=5.57, tax_rate=0.0825)
    lines = sorted((k, v) for k, v in sent.items() if k.endswith("[unit_amount]") or k.endswith("[name]"))
    assert sent["line_items[0][price_data][unit_amount]"] == "6750"
    assert sent["line_items[1][price_data][unit_amount]"] == "557"
    assert "8.25%" in sent["line_items[1][price_data][product_data][name]"]
    assert sent["line_items[2][price_data][unit_amount]"] == "1000"
    assert "not taxed" in sent["line_items[2][price_data][product_data][name]"]
    assert "payment_method_types[0]" not in sent    # Stripe shows cards, Apple Pay, Google Pay… as enabled
    assert lines
