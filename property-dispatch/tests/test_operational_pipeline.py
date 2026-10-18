"""End-to-end operational pipeline: one booking followed from the address box to the Google review ask.

Milestone 1  address → lot size → yield engine price (the booking form's price) → 8.25% Texas tax, to the cent
Milestone 2  Stripe: the exact cents and the audit tags travel on the Checkout Session and its PaymentIntent
Milestone 3  ten stops across Spring, Klein, New Caney and Cleveland: 5 PM cutoff → nightly route that is
             provably the shortest loop, and the crew dashboard data (scope lock, time on site by lawn size)
Milestone 4  crew marks the job done → review ask ~20 min later (background loop) + local area page with JSON-LD

Everything runs in memory: no Stripe, Twilio, OSRM or geocoder calls leave the machine.
Street names are real Spring-area streets; house numbers are placeholders (this repo is public).
"""

import asyncio
import itertools
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import create_app, review_loop
from app.models import GeoPoint
from app.payments import StripeClient
from app.local_pages import dollars, price_range
from app.pricing import mow_minutes, yield_mow_fee
from app.reviews import send_due_review_requests
from app.routing.matrix import haversine_matrix
from app.zones import find_zone, zone_by_key

from .conftest import FakeSMS
from .test_api_flow import CREW, NOW, TOMORROW
from .test_payments import WHSEC, signed

REVIEW_URL = "https://g.page/r/semper-green-example/review"
BRIDGEMONT = "100 Bridgemont Ln, Spring, TX"

# Ten stops in four sectors, booked in a deliberately scrambled order (the optimizer has to fix it).
STOPS = [
    # address,                                   lat,      lng,      sector
    (BRIDGEMONT,                                 30.1160, -95.3950, "SPRING_LUXURY_LOOP"),
    ("200 Example Pines Dr, Cleveland, TX",      30.3400, -95.0600, "CLEVELAND_HUB"),
    ("300 Example Oak Ct, Klein, TX",            30.0400, -95.5200, "KLEIN_CORE"),
    ("400 Example Canopy Ln, New Caney, TX",     30.2050, -95.2350, "I69_HIGH_DENSITY_SPINE"),
    ("500 Example Creek Way, Spring, TX",        30.1225, -95.3880, "SPRING_LUXURY_LOOP"),
    ("600 Example Ranch Rd, Cleveland, TX",      30.3450, -95.0900, "CLEVELAND_HUB"),
    ("700 Example Elm St, Klein, TX",            30.0460, -95.5120, "KLEIN_CORE"),
    ("800 Example Gemini Dr, New Caney, TX",     30.2120, -95.2280, "I69_HIGH_DENSITY_SPINE"),
    ("900 Example Field Ln, Spring, TX",         30.1290, -95.3810, "SPRING_LUXURY_LOOP"),
    ("1000 Example Hollow Dr, Klein, TX",        30.0520, -95.5050, "KLEIN_CORE"),
]
WHERE = {a: (lat, lng) for a, lat, lng, _ in STOPS}
# What each customer picked to mow (None = an older-style booking with a measured lawn size).
SCOPES = ["scope_yard", "scope_full", None, "scope_full", "scope_yard",
          "scope_yard", "scope_yard", None, "scope_full", None]


class MapGeocoder:
    """Stands in for the real geocoder: each test address resolves to a fixed point."""

    def geocode(self, address: str) -> GeoPoint:
        lat, lng = WHERE[address]
        return GeoPoint(lat=lat, lng=lng, formatted_address=address, precision="address")


class StripeRecorder:
    """Catches what we would POST to Stripe and answers like Stripe does."""

    def __init__(self):
        self.payloads: list[dict[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/checkout/sessions"
        self.payloads.append({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        n = len(self.payloads)
        return httpx.Response(200, json={"id": f"cs_test_{n}", "url": f"https://checkout.stripe.test/{n}"})


@pytest.fixture
def stripe_api():
    return StripeRecorder()


@pytest.fixture
def ops(settings, repo, stripe_api):
    settings.stripe_secret_key, settings.stripe_webhook_secret = "sk_test_x", WHSEC
    settings.google_review_url = REVIEW_URL
    sms = FakeSMS()
    stripe = StripeClient(settings, httpx.Client(transport=httpx.MockTransport(stripe_api)))
    client = TestClient(create_app(settings, repo=repo, geocoder=MapGeocoder(), sms=sms, stripe=stripe))
    client.sms = sms
    return client


def book(client, address, i, *, yard_type="STANDARD", scope="scope_yard", method="cash", charity="toys_for_tots", at=NOW):
    with patch("app.main.local_now", return_value=at):
        return client.post("/api/jobs", json={
            "name": f"Customer {i:02d}", "phone": f"(281) 555-01{i:02d}", "address": address,
            "service": "mowing", "yard_type": yard_type, "add_ons": [scope] if scope else [],
            "lawn_sqft": None if scope else 5_000, "charity_choice": charity,
            "scheduled_date": TOMORROW.isoformat(), "payment_method": method})


def build_route(client, at=NOW.replace(hour=17, minute=0)):
    """The 5 PM run: the cron hits /internal/nightly and tomorrow's route is built."""
    with patch("app.main.local_now", return_value=at):
        r = client.post("/internal/nightly", headers={"X-Cron-Secret": "cron"})
    assert r.status_code == 200, r.text
    return client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()


# ======================================================================
#  MILESTONE 1: address → lot profile → flat price → tax
# ======================================================================
def test_m1_address_check_sizes_the_lot_without_asking_for_square_feet(ops):
    r = ops.post("/api/check-address", json={"address": BRIDGEMONT}).json()
    assert r["in_area"] is True and r["zone_name"] == zone_by_key("SPRING_LUXURY_LOOP").name
    est = r["lawn_estimate"]
    assert (est["sqft"], est["full_sqft"], est["basis"]) == (4_500, 8_000, "typical")   # the Spring area's numbers
    assert "sq-ft" not in r["message"] and "from $75." in r["message"]


def test_m1_yard_pick_is_priced_by_the_yield_engine_at_75_plus_tax(ops):
    q = ops.post("/api/quote", json={"address": BRIDGEMONT, "service": "mowing", "yard_type": "STANDARD",
                                     "add_ons": ["scope_yard"], "lawn_sqft": 99_999}).json()   # browser's number is ignored
    assert q["lawn_sqft"] == 4_500 and q["lot_profile"] == "Standard Suburb Profile"
    assert (q["yard_type_label"], q["basis"], q["sqft_rate"], q["package"]) == ("Standard yard", "yield", None, None)
    assert (q["mow_fee"], q["density_stops"], q["density_discount"], q["price_locked"]) == (75.0, 0, 0.0, True)
    assert q["subtotal"] == 75.00 and q["tax_rate"] == 0.0825 and q["tax"] == 6.19 and q["total"] == 81.19
    # The flat bracket price, not a per-square-foot multiplication: the same price anywhere in the bracket.
    assert {yield_mow_fee(s, "STANDARD") for s in (100, 4_500, 5_000)} == {Decimal("75.00")}   # base covers 5,000
    assert Decimal("75.00") * Decimal("0.0825") == Decimal("6.187500")     # rounds half-up to $6.19
    # Nothing on the wire hints at a formula.
    text = json.dumps(q)
    for leak in ("per sq", "sq-ft", "0.009", "0.010", "0.012", "×"):
        assert leak not in text


def test_m1_booking_charges_exactly_what_was_quoted(ops):
    r = book(ops, BRIDGEMONT, 1)
    assert r.status_code == 201, r.text
    j = r.json()
    assert (j["lawn_sqft"], j["subtotal"], j["tax"], j["total"]) == (4_500, 75.0, 6.19, 81.19)
    assert j["charity_choice"] == "toys_for_tots" and j["charity_amount"] == 1.5       # 2% of $75, all to their pick
    info = ops.get("/api/booking-info").json()
    assert all("sqft_rate" not in p and "rate" not in p for p in info["packages"])
    assert [b["profile"] for b in info["packages"][0]["brackets"]][1] == "Standard Suburb Profile"


# ======================================================================
#  MILESTONE 2: Stripe gets integer cents and the audit tags
# ======================================================================
def test_m2_checkout_sends_8119_cents_with_audit_tags_on_session_and_payment_intent(ops, stripe_api, repo):
    j = book(ops, BRIDGEMONT, 1, method="card").json()
    stops = build_route(ops)["stops"]
    seq = next(s["sequence"] for s in stops if s["job_id"] == j["id"])
    token = j["pay_url"].rsplit("/", 1)[1]
    assert ops.post(f"/api/pay/{token}/checkout", json={}).status_code == 200

    sent = stripe_api.payloads[-1]
    assert sent["mode"] == "payment" and sent["metadata[amount_due_cents]"] == "8119"
    lines = [int(sent[f"line_items[{i}][price_data][unit_amount]"]) for i in range(2)]
    assert lines == [7500, 619] and sum(lines) == 8119 and "line_items[2][quantity]" not in sent
    assert sent["line_items[0][price_data][product_data][name]"].startswith("Mowing, Standard yard (")
    assert all(re.fullmatch(r"\d+", sent[k]) for k in sent if k.endswith("[unit_amount]"))   # whole cents only
    tags = {"property_profile": "Standard Suburb Profile · Yard only", "size_bracket": "3,501-7,500 sq ft",
            "service_track": "Yield engine · Standard yard", "charity_lane": "toys_for_tots",
            "crew_route_id": f"{TOMORROW}#{seq}", "job_id": j["id"]}
    for key, value in tags.items():
        assert sent[f"metadata[{key}]"] == sent[f"payment_intent_data[metadata][{key}]"] == value
    assert not any(v in json.dumps(sent) for v in ("Customer 01", "555-0101", "Bridgemont"))   # no personal info


def test_m2_payment_intent_succeeded_marks_the_job_paid(ops):
    j = book(ops, BRIDGEMONT, 1, method="card").json()
    event = {"type": "payment_intent.succeeded", "data": {"object": {"amount_received": 8119, "metadata": {
        "job_id": j["id"], "donation_cents": "0", "charity_choice": "toys_for_tots"}}}}
    payload, sig = signed(event)
    assert ops.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": sig}).status_code == 200
    v = ops.get(f"/api/visit/{j['access_code']}").json()["payment"]
    assert (v["status"], v["method"], v["amount_paid"]) == ("paid", "card", 81.19)


# ======================================================================
#  MILESTONE 3: 5 PM cutoff → provably shortest route → crew dashboard data
# ======================================================================
def loop_seconds(order, matrix) -> int:
    """Driving seconds base → stops in this order → base (node 0 is the base, then the stops)."""
    path = [0, *order, 0]
    return sum(matrix[a][b] for a, b in zip(path, path[1:]))


def shortest_loop_seconds(matrix, n) -> int:
    """Exact optimum (Held-Karp dynamic programming): the best any route could possibly do."""
    best = {(1 << i, i): matrix[0][i + 1] for i in range(n)}
    for size in range(2, n + 1):
        for subset in itertools.combinations(range(n), size):
            mask = sum(1 << i for i in subset)
            for last in subset:
                prev = mask & ~(1 << last)
                best[(mask, last)] = min(best[(prev, k)] + matrix[k + 1][last + 1] for k in subset if k != last)
    full = (1 << n) - 1
    return min(best[(full, i)] + matrix[i + 1][0] for i in range(n))


def test_m3_bookings_close_at_5_pm_the_day_before(ops):
    assert book(ops, BRIDGEMONT, 1, at=NOW.replace(hour=16, minute=59)).status_code == 201
    late = book(ops, STOPS[1][0], 2, at=NOW.replace(hour=17, minute=0))
    assert late.status_code == 409 and "already locked" in late.json()["detail"]


def test_m3_nightly_route_is_the_shortest_possible_loop_across_four_sectors(ops, settings):
    for i, (address, *_rest) in enumerate(STOPS, start=1):
        assert book(ops, address, i, scope=SCOPES[i - 1]).status_code == 201
    route = build_route(ops)
    stops = route["stops"]
    assert len(stops) == 10 and [s["sequence"] for s in stops] == list(range(1, 11))
    assert route["matrix_source"] == "haversine"       # tests never call OSRM; production uses OSRM road times

    # Same travel times the optimizer used (base → stops → base).
    points = [settings.start_point, *[(lat, lng) for _, lat, lng, _ in STOPS]]
    secs = haversine_matrix(points).durations_s
    index = {a: i + 1 for i, (a, *_r) in enumerate(STOPS)}
    chosen = [index[s["address"]] for s in stops]
    booked = list(range(1, 11))
    optimum = shortest_loop_seconds(secs, 10)
    assert loop_seconds(chosen, secs) == optimum                    # no shorter route exists
    assert loop_seconds(booked, secs) > optimum * 1.5               # booking order would zigzag across sectors

    # Each sector is finished before moving to the next: 4 sectors → 3 hand-offs.
    sectors = [find_zone(s["lat"], s["lng"]).key for s in stops]
    assert sum(a != b for a, b in zip(sectors, sectors[1:])) == 3
    assert {k for *_r, k in STOPS} == set(sectors)
    # ETAs run forward through the day.
    etas = [datetime.fromisoformat(s["eta"]) for s in stops]
    assert etas == sorted(etas) and etas[0].hour == 7


def test_m3_crew_dashboard_data_carries_the_scope_lock_and_time_by_lawn_size(ops):
    for i, (address, *_rest) in enumerate(STOPS, start=1):
        book(ops, address, i, scope=SCOPES[i - 1])
    stops = build_route(ops)["stops"]
    for s in stops:
        zone = find_zone(s["lat"], s["lng"])
        assert s["service_minutes"] == mow_minutes(s["lawn_sqft"])          # bigger lawn, longer stop
        if s["scope"] == "scope_yard":
            assert s["lawn_sqft"] == zone.yard_sqft
        elif s["scope"] == "scope_full":
            assert s["lawn_sqft"] == zone.full_property_sqft
        else:
            assert s["scope"] is None and s["lawn_sqft"] == 5_000
        # Hand-off links to the native Maps apps: the house address, URL-encoded (Maps drives to the front door).
        google, apple = urlparse(s["google_maps_url"]), urlparse(s["apple_maps_url"])
        assert (google.netloc, apple.netloc) == ("www.google.com", "maps.apple.com")
        assert parse_qs(google.query)["destination"] == [s["address"]] == parse_qs(apple.query)["daddr"]
        assert s["charity_choice_name"]
    cleveland_full = next(s for s in stops if s["scope"] == "scope_full" and "Cleveland" in s["address"])
    spring_yard = next(s for s in stops if s["scope"] == "scope_yard" and "Spring" in s["address"])
    assert (cleveland_full["lawn_sqft"], spring_yard["lawn_sqft"]) == (14_500, 4_500)
    assert cleveland_full["service_minutes"] > spring_yard["service_minutes"]

    page = ops.get("/crew/dashboard").text
    for words in ("SCOPE ENFORCEMENT", "COMPLIANCE LOCK: Core Yard Mowing Only", "FULL PARCEL ROTATION",
                  "START ROUTE TRANSIT", "ARRIVED ON SITE", "COMPLETE VISIT & INVOICE STRIPE"):
        assert words in page, words


# ======================================================================
#  MILESTONE 4: done → review ask (background) + local area page
# ======================================================================
def complete_bridgemont(ops):
    j = book(ops, BRIDGEMONT, 1).json()
    stop = next(s for s in build_route(ops)["stops"] if s["job_id"] == j["id"])
    r = ops.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"cash_collected": 81.19})
    assert r.status_code == 200 and r.json()["payment"]["status"] == "paid"
    return j


def test_m4_review_ask_waits_for_the_crew_to_leave_then_goes_out_once(ops, repo, settings):
    j = complete_bridgemont(ops)
    done = datetime.fromisoformat(repo.jobs[j["id"]]["completed_at"])
    texts = len(ops.sms.sent)
    assert send_due_review_requests(repo, settings, ops.sms, done, "https://example.test")["asked"] == 0   # not while on site
    report = send_due_review_requests(repo, settings, ops.sms, done + timedelta(minutes=20), "https://example.test")
    assert report["asked"] == 1 and len(ops.sms.sent) == texts + 1
    to, text = ops.sms.sent[-1]
    code = j["access_code"].replace("-", "")
    assert to.endswith("5550101") and settings.business_name in text and REVIEW_URL in text
    assert f"https://example.test/visit/{code}" in text
    for banned in ("5-star", "5 star", "Toys for Tots", "donat"):
        assert banned not in text
    assert send_due_review_requests(repo, settings, ops.sms, done + timedelta(minutes=25), "x")["asked"] == 0
    assert ops.get(f"/api/visit/{code}").json()["review_url"] == REVIEW_URL     # button on their visit page too


def test_m4_background_loop_sends_it_from_a_worker_thread(ops, repo):
    import threading
    j = complete_bridgemont(ops)
    finished = datetime.now(timezone.utc) - timedelta(minutes=21)           # as if the crew left 21 minutes ago
    repo.jobs[j["id"]]["completed_at"] = finished.isoformat()
    sent_from = []
    real_send = ops.sms.send_sms

    def send_sms(to, body):
        sent_from.append(threading.current_thread() is threading.main_thread())
        return real_send(to, body)

    naps = []

    async def nap(seconds):
        naps.append(seconds)
        if len(naps) > 1:
            raise asyncio.CancelledError          # stop after one pass

    with patch.object(ops.sms, "send_sms", side_effect=send_sms), patch("app.main.asyncio.sleep", nap):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(review_loop(ops.app))
    assert sent_from == [False] and REVIEW_URL in ops.sms.sent[-1][1]
    assert repo.jobs[j["id"]]["review_requested_at"]


def test_m4_local_area_page_carries_json_ld_and_no_customer_data(ops):
    complete_bridgemont(ops)
    r = ops.get("/local/spring/bridgemont-ln", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"].endswith("/local/spring")   # streets fold into the area page
    page = ops.get("/local/spring")
    assert page.status_code == 200
    html_text = page.text
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html_text, re.S)
    assert len(blocks) == 1
    graph = json.loads(blocks[0])["@graph"]
    types = {n["@type"] for n in graph}
    assert {"LocalBusiness", "Service", "BreadcrumbList"} <= types
    business = next(n for n in graph if n["@type"] == "LocalBusiness")
    low, high = price_range()
    assert business["priceRange"] == f"{dollars(low)}-{dollars(high)}" and low == Decimal("75.00")
    assert any("Spring" in a["name"] for a in business["areaServed"])
    for forbidden in ("aggregateRating", "review", "telephone", "streetAddress"):
        assert forbidden not in blocks[0]
    for private in ("Customer 01", "Bridgemont", "555-0101"):
        assert private not in html_text
    assert "per sq" not in html_text.lower()


# ======================================================================
#  MILESTONE 5: the whole pipeline, one booking, start to finish
# ======================================================================
def test_m5_one_booking_end_to_end(ops, repo, settings, stripe_api):
    j = book(ops, BRIDGEMONT, 1, method="card").json()
    assert j["total"] == 81.19
    stop = next(s for s in build_route(ops)["stops"] if s["job_id"] == j["id"])
    assert stop["scope"] == "scope_yard" and stop["amount_due"] == 81.19
    done = ops.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={}).json()
    assert done["payment"]["status"] == "unpaid"                     # card customer pays through Stripe
    token = j["pay_url"].rsplit("/", 1)[1]
    ops.post(f"/api/pay/{token}/checkout", json={})
    assert stripe_api.payloads[-1]["metadata[amount_due_cents]"] == "8119"
    payload, sig = signed({"type": "checkout.session.completed", "data": {"object": {
        "payment_status": "paid", "amount_total": 8119, "client_reference_id": j["id"],
        "metadata": {"job_id": j["id"], "donation_cents": "0", "charity_choice": "toys_for_tots"}}}})
    ops.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": sig})
    finished = datetime.fromisoformat(repo.jobs[j["id"]]["completed_at"])
    assert send_due_review_requests(repo, settings, ops.sms, finished + timedelta(minutes=20), "https://x")["asked"] == 1
    v = ops.get(f"/api/visit/{j['access_code']}").json()
    assert (v["status"], v["payment"]["status"], v["payment"]["amount_paid"], v["review_url"]) == \
        ("completed", "paid", 81.19, REVIEW_URL)
