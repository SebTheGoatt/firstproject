"""Mowing calculator ($35 + sq ft × Standard/Plus/Premium rate), add-ons, Texas sales tax, zones, Stripe lines."""

from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
import pytest

from app.models import Service
from app.nightly import run_nightly
from app.charity import describe, split_donation
from app.payments import StripeClient
from app.pricing import LawnSizeError, check_sqft, quote
from app.zones import SERVICE_ZONES, ServiceZone, find_zone, validate_zones, zone_by_key

from .test_api_flow import CREW, NOW, TOMORROW

SPRING = zone_by_key("SPRING_LUXURY_LOOP")   # $35 base service fee, like every area


# The acceptance examples: 5,000 sq ft → Standard $80, Plus $85, Premium $95 before tax.
@pytest.mark.parametrize("sqft, package, subtotal, tax, total, charity, net", [
    (5_000, "standard",  "80.00", "6.60", "86.60",  "1.60", "78.40"),
    (5_000, "supporter", "85.00", "7.01", "92.01",  "5.95", "79.05"),   # Plus
    (5_000, "hero",      "95.00", "7.84", "102.84", "11.40", "83.60"),  # Premium
    (3_333, "standard",  "65.00", "5.36", "70.36",  "1.30", "63.70"),   # $64.997 rounds to $65.00
    (4_321, "hero",      "86.85", "7.17", "94.02",  "10.42", "76.43"),  # $86.852 rounds to $86.85
])
def test_mowing_is_35_base_plus_sqft_times_chosen_rate(sqft, package, subtotal, tax, total, charity, net):
    q = quote(SPRING, Service.MOWING, sqft, package=package)
    assert (q.subtotal, q.tax, q.total, q.charity_amount, q.business_net) == \
        tuple(Decimal(x) for x in (subtotal, tax, total, charity, net))
    assert q.basis == "base_plus_sqft" and q.base_fee == Decimal("35.00")
    assert q.subtotal == q.base_fee + q.mow_price - q.base_fee   # the base fee is in once, not per sq ft


def test_tier_rates_and_names():
    rates = {k: quote(SPRING, Service.MOWING, 1_000, package=k) for k in ("standard", "supporter", "hero")}
    assert {k: (q.sqft_rate, q.as_dict()["package_label"]) for k, q in rates.items()} == {
        "standard": (Decimal("0.009"), "Standard"), "supporter": (Decimal("0.010"), "Plus"), "hero": (Decimal("0.012"), "Premium")}


def test_no_lawn_size_is_never_guessed():
    with pytest.raises(LawnSizeError):
        quote(SPRING, Service.MOWING, None, package="standard")


@pytest.mark.parametrize("value, ok", [
    (5_000, 5_000), ("5000", 5_000), (100, 100), (87_120, 87_120),
    (None, None), ("", None), (0, None), (-50, None), ("abc", None), (5000.5, None), (99, None), (87_121, None),
])
def test_lawn_size_validation(value, ok):
    if ok is None:
        with pytest.raises(LawnSizeError):
            check_sqft(value)
    else:
        assert check_sqft(value) == ok


def test_texas_sales_tax_is_on_the_whole_price_and_rounds_to_the_cent():
    q = quote(SPRING, Service.MOWING, 5_000, package="supporter")   # $85 × 8.25% = $7.0125 → $7.01
    assert (q.tax, q.tax_rate) == (Decimal("7.01"), Decimal("0.0825"))
    assert q.total == q.subtotal + q.tax                              # the charity share isn't extra
    g = quote(SPRING, Service.GUTTERS, on_site_price=120)
    assert (g.subtotal, g.tax, g.total, g.charity_amount) == (Decimal("120.00"), Decimal("9.90"), Decimal("129.90"), None)
    assert quote(SPRING, Service.BIN_CLEANING).total is None   # old bin-only bookings: priced on site


@pytest.mark.parametrize("lat, lng, place", [
    (30.2147, -95.0949, "Plum Grove city center"),
    (30.2000, -95.1080, "Plum Grove, west side"),
    (30.1750, -95.0900, "Plum Grove, south side"),
])
def test_plum_grove_is_in_the_cleveland_sector(lat, lng, place):
    z = find_zone(lat, lng)
    assert z.key == "CLEVELAND_HUB" and z.mow_rate == 35.0, place


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
                                              "service": "mowing", "lawn_sqft": 5000, "package": "standard", "scheduled_date": TOMORROW.isoformat(), **extra})


def test_live_quote_endpoint(client):
    r = client.post("/api/quote", json={"address": "100 A Example Rd", "service": "mowing", "lawn_sqft": 5_000,
                                        "package": "supporter"}).json()
    assert (r["in_area"], r["subtotal"], r["tax"], r["total"], r["charity_amount"], r["business_net"]) == \
        (True, 85.0, 7.01, 92.01, 5.95, 79.05)
    assert (r["package_label"], r["sqft_rate"], r["base_fee"], r["mow_price"]) == ("Plus", 0.01, 35.0, 85.0)
    for bad in ({"package": "gold", "lawn_sqft": 5_000}, {"package": "standard", "lawn_sqft": 0},
                {"package": "standard", "lawn_sqft": -10}, {"package": "standard", "lawn_sqft": "abc"},
                {"package": "standard"}):
        assert client.post("/api/quote", json={"address": "100 A Example Rd", "service": "mowing", **bad}).status_code == 422, bad
    r = client.post("/api/quote", json={"address": "100 A Example Rd", "service": "gutters"}).json()
    assert r["total"] is None and r["basis"] == "on_site" and r["tax_rate"] == 0.0825
    r = client.post("/api/quote", json={"address": "100 Old Town Rd", "service": "mowing", "lawn_sqft": 5_000}).json()
    assert r["in_area"] is False


@pytest.mark.parametrize("missing, message", [
    ({"package": None}, "Choose a rate"), ({"lawn_sqft": None}, "Enter your lawn size"),
    ({"lawn_sqft": 0}, "greater than zero"), ({"lawn_sqft": 50}, "smallest lawn"),
    ({"lawn_sqft": 500_000}, "quoted in person"),
])
def test_booking_needs_a_chosen_rate_and_a_real_lawn_size(client, repo, missing, message):
    r = post_job(client, **{"lawn_sqft": 5_000, "package": "standard", **missing})
    assert r.status_code == 422 and message in r.json()["detail"] and not repo.jobs


def test_server_recalculates_and_ignores_any_client_total(client, repo):
    r = post_job(client, lawn_sqft=5_000, package="hero", total=1.00, subtotal=1.00, amount_due=1.00)
    b = r.json()
    assert (b["subtotal"], b["tax"], b["total"]) == (95.0, 7.84, 102.84)
    assert repo.jobs[b["id"]]["amount_due"] == 102.84


def test_booking_saves_the_breakdown_and_charity_share(client, repo):
    r = post_job(client, lawn_sqft=5_000, package="hero").json()
    assert (r["lawn_sqft"], r["package"], r["sqft_rate"], r["subtotal"], r["tax"], r["total"], r["charity_amount"]) == \
        (5_000, "hero", 0.012, 95.0, 7.84, 102.84, 11.4)
    job = repo.jobs[r["id"]]
    assert (job["amount_due"], job["subtotal"], job["tax_amount"], job["charity_rate"], job["charity_amount"]) == \
        (102.84, 95.0, 7.84, 0.12, 11.4)
    assert job["giving_split"] == split_donation(11.4)


def test_crew_corrects_lawn_size_on_site(client, repo, settings):
    job = post_job(client, lawn_sqft=5_000, package="supporter").json()   # Plus: $85 + $7.01 = $92.01
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    assert (stop["lawn_sqft"], stop["package"], stop["subtotal"], stop["amount_due"], stop["charity_amount"]) == \
        (5_000, "supporter", 85.0, 92.01, 5.95)
    # Actually 6,000 sq ft, same rate: $35 + $60 = $95 + $7.84 tax = $102.84. Short cash is refused...
    bad = client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"lawn_sqft": 6_000, "cash_collected": 100})
    assert bad.status_code == 422 and "102.84" in bad.json()["detail"]
    assert repo.jobs[job["id"]]["amount_due"] == 92.01            # ...and nothing was changed
    ok = client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"lawn_sqft": 6_000, "cash_collected": 105}).json()
    assert ok["payment"]["total"] == 102.84 and ok["payment"]["donation"] == 2.16
    j = repo.jobs[job["id"]]
    assert (j["lawn_sqft"], j["subtotal"], j["tax_amount"], j["amount_due"], j["charity_amount"]) == \
        (6_000, 95.0, 7.84, 102.84, 6.65)
    assert j["giving_split"] == split_donation(6.65) and j["donation_split"] == split_donation(2.16)


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


# ---------- Add-ons: bin cleaning $15, gutters $15 (with a mow); holiday lighting is a free quote ----------
def test_add_ons_are_part_of_the_order_taxed_and_counted_for_charity():
    q = quote(SPRING, Service.MOWING, 5_000, package="supporter", add_ons=["gutters", "bin_cleaning"])
    assert (q.mow_price, q.add_on_total, q.subtotal) == (Decimal("85.00"), Decimal("30.00"), Decimal("115.00"))
    assert (q.tax, q.total, q.charity_amount) == (Decimal("9.49"), Decimal("124.49"), Decimal("8.05"))   # 7% of the whole order
    assert [a["key"] for a in q.add_ons] == ["bin_cleaning", "gutters"]                                 # catalog order
    with pytest.raises(ValueError):
        quote(SPRING, Service.MOWING, 5_000, add_ons=["pressure_washing"])


def test_add_ons_are_never_charged_twice():
    q = quote(SPRING, Service.MOWING, 5_000, package="standard", add_ons=["gutters", "gutters", "bin_cleaning", "bin_cleaning"])
    assert q.add_on_total == Decimal("30.00") and len(q.add_ons) == 2


def test_holiday_lighting_is_a_free_quote_request():
    q = quote(SPRING, Service.MOWING, 5_000, package="standard", add_ons=["holiday_lights"])
    assert q.add_on_total == 0 and q.subtotal == Decimal("80.00")       # nothing charged for the quote
    assert q.add_ons == ({"key": "holiday_lights", "label": "Holiday lighting quote", "price": None, "quote": True},)


def test_holiday_lights_are_seasonal():
    from datetime import date
    from app.pricing import in_season
    assert [in_season("holiday_lights", date(*d)) for d in ((2026, 10, 14), (2026, 10, 15), (2026, 12, 24),
                                                             (2027, 1, 15), (2027, 1, 16), (2027, 7, 4))] == \
        [False, True, True, True, False, False]
    assert in_season("gutters", date(2027, 7, 4))


def test_booking_with_add_ons(client, repo):
    r = post_job(client, lawn_sqft=5_000, package="supporter", add_ons=["holiday_lights", "gutters"])
    assert r.status_code == 201, r.text
    b = r.json()
    assert (b["subtotal"], b["add_on_total"], b["tax"], b["total"], b["charity_amount"]) == (100.0, 15.0, 8.25, 108.25, 7.0)
    assert [(a["label"], a["price"]) for a in b["add_ons"]] == [("Gutter cleaning", 15.0), ("Holiday lighting quote", None)]
    job = repo.jobs[b["id"]]
    assert job["service_minutes"] == 45 + 30 + 10            # mow + gutters + a quick look for the lighting quote
    assert job["add_on_total"] == 15.0 and len(job["add_ons"]) == 2


def test_add_ons_out_of_season_or_without_a_mow_are_refused(client):
    from datetime import date, datetime
    from zoneinfo import ZoneInfo
    summer = datetime(2027, 7, 1, 10, tzinfo=ZoneInfo("America/Chicago"))
    with patch("app.main.local_now", return_value=summer):
        r = client.post("/api/jobs", json={"name": "Pat Doe", "phone": "2815550100", "address": "100 A Example Rd",
                                           "lawn_sqft": 5_000, "package": "standard",
                                           "scheduled_date": date(2027, 7, 2).isoformat(), "add_ons": ["holiday_lights"]})
    assert r.status_code == 422 and "Oct 15 – Jan 15" in r.json()["detail"]
    q = client.post("/api/quote", json={"address": "100 A Example Rd", "lawn_sqft": 5_000, "package": "standard",
                                        "add_ons": ["holiday_lights"], "scheduled_date": "2027-07-02"}).json()
    assert q["add_ons"] == [] and q["subtotal"] == 80.0            # quote drops out-of-season add-ons


def test_crew_sees_add_ons_and_size_corrections_keep_them(client, repo, settings):
    post_job(client, lawn_sqft=5_000, package="supporter", add_ons=["bin_cleaning"])   # $85 + $15 = $100
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    assert stop["service_label"] == "Mowing + Bin cleaning" and stop["add_on_total"] == 15.0
    ok = client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW,
                     json={"lawn_sqft": 6_000, "cash_collected": 120}).json()
    assert ok["payment"]["total"] == 119.08                        # ($95 mow + $15 bins) + 8.25% tax
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    assert (stop["subtotal"], stop["charity_amount"]) == (110.0, 7.7)


@pytest.mark.parametrize("lat, lng, section", [
    (30.1614, -95.0514, "Santa Fe"),
    (30.1788, -95.0697, "Grand San Jacinto"),
    (30.1876, -95.0731, "Montebello"),
    (30.1870, -95.0453, "Colony Ridge"),
    (30.2011, -95.0670, "Camino Real"),
    (30.2563, -95.0635, "Bella Vista"),
    (30.1794, -95.0732, "1450 Grand San Jacinto Dr (Census geocoder)"),
])
def test_colony_ridge_sections_are_served(lat, lng, section):
    z = find_zone(lat, lng)
    assert z.key == "COLONY_RIDGE" and z.mow_rate == 35.0, section


def test_plum_grove_and_cleveland_unchanged_by_colony_ridge():
    assert find_zone(30.2147, -95.0949).key == "CLEVELAND_HUB"     # Plum Grove
    assert find_zone(30.2323, -95.0871).key == "CLEVELAND_HUB"     # Rancho San Vicente (inside Plum Grove)
    assert find_zone(30.3415, -95.0900).key == "CLEVELAND_HUB"     # downtown Cleveland


def test_stripe_charges_exactly_the_booked_total_and_never_the_free_quote(client, repo, settings):
    b = post_job(client, lawn_sqft=5_000, package="supporter", add_ons=["gutters", "holiday_lights"]).json()
    assert b["total"] == 108.25                       # $85 mow + $15 gutters + $8.25 tax; the lighting quote is free
    sent = {}

    def handler(req):
        sent.update({k: v[0] for k, v in parse_qs(req.content.decode()).items()})
        return httpx.Response(200, json={"id": "cs_1", "url": "https://checkout.stripe.test/1"})

    settings.stripe_secret_key = "sk_test"
    StripeClient(settings, httpx.Client(transport=httpx.MockTransport(handler))).create_checkout(
        job_id=b["id"], service_label="Mowing", service_date=b["scheduled_date"], amount_due=b["total"], donation=0,
        success_url="https://x/ok", cancel_url="https://x/no", subtotal=b["subtotal"], tax=b["tax"],
        tax_rate=b["tax_rate"], add_ons=b["add_ons"], package_label="Plus", charity_rate=0.07, charity_amount=b["charity_amount"])
    lines = [int(v) for k, v in sent.items() if k.endswith("[unit_amount]")]
    names = [v for k, v in sent.items() if k.endswith("[product_data][name]")]
    assert sum(lines) == 10825 and lines == [8500, 1500, 825]
    assert not any("Holiday" in n for n in names)
