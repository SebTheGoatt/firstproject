"""Mowing packages ($50 + rate × sq ft, with charity giving), Texas sales tax, Plum Grove, and Stripe line items."""

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

SPRING = zone_by_key("SPRING_LUXURY_LOOP")   # $50 base trip fee, like every area


@pytest.mark.parametrize("sqft, package, subtotal, tax, total, charity, net", [
    # The owner's example: 3,500 sq ft, Supporter → $50 + $35 = $85; 7% = $5.95 to charity
    (3_500, "supporter", "85.00", "7.01", "92.01", "5.95", "79.05"),
    (3_500, "standard", "81.50", "6.72", "88.22", "1.63", "79.87"),
    (3_500, "hero", "88.50", "7.30", "95.80", "10.62", "77.88"),
    (8_000, "standard", "122.00", "10.07", "132.07", "2.44", "119.56"),
    (8_000, "supporter", "130.00", "10.73", "140.73", "9.10", "120.90"),
    (8_000, "hero", "138.00", "11.39", "149.39", "16.56", "121.44"),
])
def test_mowing_is_base_fee_plus_package_rate(sqft, package, subtotal, tax, total, charity, net):
    q = quote(SPRING, Service.MOWING, sqft, package=package)
    assert (q.subtotal, q.tax, q.total, q.charity_amount, q.business_net) == \
        tuple(Decimal(x) for x in (subtotal, tax, total, charity, net))
    assert q.basis == "base_plus_sqft" and q.base_fee == Decimal("50.00")


def test_unknown_or_missing_package_is_standard_and_missing_size_is_a_typical_lot():
    assert quote(SPRING, Service.MOWING, 8_000, package="platinum").package == "standard"
    q = quote(SPRING, Service.MOWING)                  # no size, no package
    assert (q.package, q.lawn_sqft, q.subtotal) == ("standard", 4_500, Decimal("90.50"))


def test_texas_sales_tax_is_on_the_whole_price_and_rounds_to_the_cent():
    q = quote(SPRING, Service.MOWING, 3_500, package="supporter")   # $85 × 8.25% = $7.0125 → $7.01
    assert (q.tax, q.tax_rate) == (Decimal("7.01"), Decimal("0.0825"))
    assert q.total == q.subtotal + q.tax                              # the charity share isn't extra
    g = quote(SPRING, Service.GUTTERS, on_site_price=120)
    assert (g.subtotal, g.tax, g.total, g.charity_amount) == (Decimal("120.00"), Decimal("9.90"), Decimal("129.90"), None)
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
    r = client.post("/api/quote", json={"address": "100 A Example Rd", "service": "mowing", "lawn_sqft": 3_500,
                                        "package": "supporter"}).json()
    assert (r["in_area"], r["subtotal"], r["tax"], r["total"], r["charity_amount"], r["business_net"]) == \
        (True, 85.0, 7.01, 92.01, 5.95, 79.05)
    assert (r["package_label"], r["sqft_rate"], r["charity_rate"], r["base_fee"]) == ("Community Supporter", 0.01, 0.07, 50.0)
    bad = client.post("/api/quote", json={"address": "100 A Example Rd", "service": "mowing", "package": "gold"})
    assert bad.status_code == 422
    r = client.post("/api/quote", json={"address": "100 A Example Rd", "service": "gutters"}).json()
    assert r["total"] is None and r["basis"] == "on_site" and r["tax_rate"] == 0.0825
    r = client.post("/api/quote", json={"address": "100 Old Town Rd", "service": "mowing"}).json()
    assert r["in_area"] is False


def test_booking_saves_the_breakdown_and_charity_share(client, repo):
    r = post_job(client, lawn_size="large", package="hero").json()
    assert (r["lawn_sqft"], r["package"], r["subtotal"], r["tax"], r["total"], r["charity_amount"]) == \
        (8_000, "hero", 138.0, 11.39, 149.39, 16.56)
    job = repo.jobs[r["id"]]
    assert (job["amount_due"], job["subtotal"], job["tax_amount"], job["charity_rate"], job["charity_amount"]) == \
        (149.39, 138.0, 11.39, 0.12, 16.56)
    assert job["giving_split"] == split_donation(16.56) == {"vfw": 5.47, "nicu": 5.46, "at_risk_youth": 5.63}
    r = post_job(client, phone="2815550101").json()               # no size or package → Standard, typical lot
    assert (r["package"], r["lawn_sqft"], r["subtotal"], r["total"]) == ("standard", 4_500, 90.5, 97.97)


def test_crew_corrects_lawn_size_on_site(client, repo, settings):
    job = post_job(client, lawn_sqft=3_500, package="supporter").json()   # $92.01
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    assert (stop["lawn_sqft"], stop["package"], stop["subtotal"], stop["amount_due"], stop["charity_amount"]) == \
        (3_500, "supporter", 85.0, 92.01, 5.95)
    # Actually 5,000 sq ft, same package: $50 + $50 = $100 + $8.25 tax = $108.25. Short cash is refused...
    bad = client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"lawn_sqft": 5_000, "cash_collected": 100})
    assert bad.status_code == 422 and "108.25" in bad.json()["detail"]
    assert repo.jobs[job["id"]]["amount_due"] == 92.01            # ...and nothing was changed
    ok = client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"lawn_sqft": 5_000, "cash_collected": 110}).json()
    assert ok["payment"]["total"] == 108.25 and ok["payment"]["donation"] == 1.75
    j = repo.jobs[job["id"]]
    assert (j["lawn_sqft"], j["subtotal"], j["tax_amount"], j["amount_due"], j["charity_amount"]) == \
        (5_000, 100.0, 8.25, 108.25, 7.0)
    assert j["giving_split"] == split_donation(7.0) and j["donation_split"] == split_donation(1.75)


def test_stripe_checkout_lines_split_price_tax_and_untaxed_donations_per_charity(settings):
    sent = {}

    def handler(req):
        sent.update({k: v[0] for k, v in parse_qs(req.content.decode()).items()})
        return httpx.Response(200, json={"id": "cs_1", "url": "https://checkout.stripe.test/1"})

    settings.stripe_secret_key = "sk_test"
    StripeClient(settings, httpx.Client(transport=httpx.MockTransport(handler))).create_checkout(
        job_id="j1", service_label="Mowing", service_date="2026-10-15", amount_due=73.07, donation=10.0,
        success_url="https://x/ok", cancel_url="https://x/no", subtotal=67.5, tax=5.57, tax_rate=0.0825,
        charities=describe(settings), package_label="Community Supporter", charity_rate=0.07, charity_amount=4.73)
    lines = sorted((k, v) for k, v in sent.items() if k.endswith("[unit_amount]") or k.endswith("[name]"))
    assert sent["line_items[0][price_data][unit_amount]"] == "6750"
    assert "Community Supporter" in sent["line_items[0][price_data][product_data][name]"]
    assert "generates $4.73 (7%) for VFW, NICU & youth programs" in sent["line_items[0][price_data][product_data][name]"]
    assert sent["line_items[1][price_data][unit_amount]"] == "557"
    assert "8.25%" in sent["line_items[1][price_data][product_data][name]"]
    # $10 donation: 33% / 33% / 34%, one untaxed line per cause
    assert [sent[f"line_items[{i}][price_data][unit_amount]"] for i in (2, 3, 4)] == ["330", "330", "340"]
    names = [sent[f"line_items[{i}][price_data][product_data][name]"] for i in (2, 3, 4)]
    assert "VFW" in names[0] and "NICU" in names[1] and "youth" in names[2]
    assert all("not taxed" in n for n in names) and "line_items[5][quantity]" not in sent
    assert "payment_method_types[0]" not in sent    # Stripe shows cards, Apple Pay, Google Pay… as enabled
    assert lines
