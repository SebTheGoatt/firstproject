"""Square-footage pricing (pay-what-you-can rate), Texas sales tax, Plum Grove, and the Stripe line items."""

from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
import pytest

from app.models import Service
from app.nightly import run_nightly
from app.charity import describe, split_donation
from app.payments import StripeClient
from app.pricing import LAWN_SIZES, quote, resolve_sqft
from app.zones import SERVICE_ZONES, ServiceZone, find_zone, validate_zones, zone_by_key

from .test_api_flow import CREW, NOW, TOMORROW

SPRING = zone_by_key("SPRING_LUXURY_LOOP")   # $50 flat fee, like every area


@pytest.mark.parametrize("sqft, rate, subtotal, basis", [
    (2_500, None, "50.00", "flat"),         # 2,500 × 1.0¢ = $25 < $50 → flat fee
    (5_000, "0.010", "50.00", "flat"),      # exactly $50
    (5_001, "0.010", "50.01", "per_sqft"),
    (5_556, "0.009", "50.00", "flat"),      # $50.004 → $50.00
    (4_546, "0.011", "50.01", "per_sqft"),  # $50.006 → $50.01
    (8_000, "0.009", "72.00", "per_sqft"),
    (8_000, "0.010", "80.00", "per_sqft"),
    (8_000, "0.011", "88.00", "per_sqft"),
])
def test_mowing_is_flat_fee_or_chosen_rate_whichever_is_higher(sqft, rate, subtotal, basis):
    q = quote(SPRING, Service.MOWING, sqft, sqft_rate=rate)
    assert (q.subtotal, q.basis) == (Decimal(subtotal), basis)
    assert q.sqft_rate == Decimal(rate or "0.010")


def test_only_the_offered_rates_are_accepted():
    with pytest.raises(ValueError):
        quote(SPRING, Service.MOWING, 8_000, sqft_rate="0.005")


def test_texas_sales_tax_rounds_to_the_cent():
    q = quote(SPRING, Service.MOWING, 3_000)          # $50 × 8.25% = $4.125 → $4.13
    assert (q.tax, q.total, q.tax_rate) == (Decimal("4.13"), Decimal("54.13"), Decimal("0.0825"))
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
    assert z.key == "CLEVELAND_HUB" and z.mow_rate == 50.0, place


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
    assert (r["in_area"], r["subtotal"], r["tax"], r["total"], r["lawn_sqft"], r["basis"], r["sqft_rate"]) == \
        (True, 80.0, 6.6, 86.6, 8_000, "per_sqft", 0.01)
    r = client.post("/api/quote", json={"address": "100 A Example Rd", "service": "mowing", "lawn_size": "large",
                                        "sqft_rate": 0.011}).json()
    assert (r["subtotal"], r["tax"], r["total"]) == (88.0, 7.26, 95.26)
    bad = client.post("/api/quote", json={"address": "100 A Example Rd", "service": "mowing", "sqft_rate": 0.015})
    assert bad.status_code == 422
    r = client.post("/api/quote", json={"address": "100 A Example Rd", "service": "gutters"}).json()
    assert r["total"] is None and r["basis"] == "on_site" and r["tax_rate"] == 0.0825
    r = client.post("/api/quote", json={"address": "100 Old Town Rd", "service": "mowing"}).json()
    assert r["in_area"] is False


def test_booking_saves_the_breakdown(client, repo):
    r = post_job(client, lawn_size="large", sqft_rate=0.009).json()
    assert (r["lawn_sqft"], r["sqft_rate"], r["subtotal"], r["tax"], r["total"]) == (8_000, 0.009, 72.0, 5.94, 77.94)
    job = repo.jobs[r["id"]]
    assert (job["amount_due"], job["subtotal"], job["tax_amount"], job["tax_rate"], job["sqft_rate"]) == \
        (77.94, 72.0, 5.94, 0.0825, 0.009)
    r = post_job(client, lawn_sqft=2_000, phone="2815550101").json()
    assert (r["subtotal"], r["total"]) == (50.0, 54.13)          # small lawn → $50 minimum


def test_crew_corrects_lawn_size_on_site(client, repo, settings):
    job = post_job(client, lawn_size="large", sqft_rate=0.011).json()   # 8,000 sq ft at 1.1¢ → $95.26
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    assert (stop["lawn_sqft"], stop["sqft_rate"], stop["subtotal"], stop["amount_due"]) == (8_000, 0.011, 88.0, 95.26)
    # Actually 10,000 sq ft, at the rate they chose: $110 + $9.08 tax = $119.08. Short cash is refused...
    bad = client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"lawn_sqft": 10_000, "cash_collected": 100})
    assert bad.status_code == 422 and "119.08" in bad.json()["detail"]
    assert repo.jobs[job["id"]]["amount_due"] == 95.26            # ...and nothing was changed
    ok = client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"lawn_sqft": 10_000, "cash_collected": 120}).json()
    assert ok["payment"]["total"] == 119.08 and ok["payment"]["donation"] == 0.92
    j = repo.jobs[job["id"]]
    assert (j["lawn_sqft"], j["subtotal"], j["tax_amount"], j["amount_due"]) == (10_000, 110.0, 9.08, 119.08)
    assert j["donation_split"] == split_donation(0.92) and round(sum(j["donation_split"].values()), 2) == 0.92


def test_stripe_checkout_lines_split_price_tax_and_untaxed_donations_per_charity(settings):
    sent = {}

    def handler(req):
        sent.update({k: v[0] for k, v in parse_qs(req.content.decode()).items()})
        return httpx.Response(200, json={"id": "cs_1", "url": "https://checkout.stripe.test/1"})

    settings.stripe_secret_key = "sk_test"
    StripeClient(settings, httpx.Client(transport=httpx.MockTransport(handler))).create_checkout(
        job_id="j1", service_label="Mowing", service_date="2026-10-15", amount_due=73.07, donation=10.0,
        success_url="https://x/ok", cancel_url="https://x/no", subtotal=67.5, tax=5.57, tax_rate=0.0825,
        charities=describe(settings))
    lines = sorted((k, v) for k, v in sent.items() if k.endswith("[unit_amount]") or k.endswith("[name]"))
    assert sent["line_items[0][price_data][unit_amount]"] == "6750"
    assert sent["line_items[1][price_data][unit_amount]"] == "557"
    assert "8.25%" in sent["line_items[1][price_data][product_data][name]"]
    # $10 donation: 33% / 33% / 34%, one untaxed line per cause
    assert [sent[f"line_items[{i}][price_data][unit_amount]"] for i in (2, 3, 4)] == ["330", "330", "340"]
    names = [sent[f"line_items[{i}][price_data][product_data][name]"] for i in (2, 3, 4)]
    assert "VFW" in names[0] and "NICU" in names[1] and "youth" in names[2]
    assert all("not taxed" in n for n in names) and "line_items[5][quantity]" not in sent
    assert "payment_method_types[0]" not in sent    # Stripe shows cards, Apple Pay, Google Pay… as enabled
    assert lines
