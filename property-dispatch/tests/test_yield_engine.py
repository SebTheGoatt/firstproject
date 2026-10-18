"""Owner's yield pricing engine: size scaling, complexity, real route-density discount, add-ons, tax."""

from unittest.mock import patch

from .test_api_flow import NOW, book

SPOT = {"latitude": 30.15, "longitude": -95.39}     # address "A" in the test geocoder


def price(client, **kw):
    body = {"street_address": "100 Test Rd, Spring, TX", **SPOT, "lot_size_sqft": 5000, "complexity_rating": "STANDARD",
            "has_bin_cleaning": False, "has_gutter_cleaning": False, **kw}
    r = client.post("/api/v1/calculate-yield-price", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_standard_5000_sqft_with_no_neighbors(client):
    assert price(client) == {"base_mow_fee": 75.0, "density_discount": 0.0, "addons_total": 0.0, "subtotal": 75.0,
                             "sales_tax": 6.19, "final_checkout_total": 81.19, "route_density_score": 0,
                             "is_cluster_optimized": False}


def test_size_complexity_and_add_ons(client):
    d = price(client, lot_size_sqft=10000, complexity_rating="STEEP_SLOPES", has_bin_cleaning=True, has_gutter_cleaning=True)
    # 75 x (1 + 5 x 0.08) x 1.25 = 131.25; + $30 add-ons = 161.25; tax 13.30
    assert (d["base_mow_fee"], d["addons_total"], d["subtotal"], d["sales_tax"], d["final_checkout_total"]) == \
        (131.25, 30.0, 161.25, 13.30, 174.55)
    assert price(client, lot_size_sqft=5001)["base_mow_fee"] == 81.0          # any part of 1,000 extra counts
    assert price(client, complexity_rating="COMPLEX_OBSTACLES")["base_mow_fee"] == 86.25
    assert price(client, complexity_rating="UNKNOWN")["base_mow_fee"] == 75.0


def test_density_discount_counts_real_bookings_nearby(client):
    def booked(n):
        for i in range(n):
            with patch("app.main.local_now", return_value=NOW):
                assert book(client, "A", f"02{i:02d}").status_code == 201
    with patch("app.yield_engine.local_now", return_value=NOW):
        booked(2)
        d = price(client)
        assert (d["route_density_score"], d["density_discount"], d["is_cluster_optimized"]) == (2, 3.75, True)
        booked(3)
        d = price(client)
        assert (d["route_density_score"], d["density_discount"], d["final_checkout_total"]) == (5, 7.5, 73.07)
        far = price(client, latitude=30.30, longitude=-95.0)
        assert far["route_density_score"] == 0 and far["density_discount"] == 0


def test_estimate_page_is_served_but_not_indexed(client):
    r = client.get("/estimate")
    assert r.status_code == 200 and r.headers["x-robots-tag"] == "noindex"
    assert '<script src="/static/yield-engine.js' in r.text and 'id="pricing-breakdown-display"' in r.text


# ---------- The booking form's real price ----------
from app.nightly import run_nightly                      # noqa: E402

from .test_api_flow import CREW, TOMORROW                # noqa: E402


def book_yield(client, letter="A", phone="0100", yard_type="STANDARD", sqft=5000, method="cash", add_ons=()):
    with patch("app.main.local_now", return_value=NOW), patch("app.yield_engine.local_now", return_value=NOW):
        r = client.post("/api/jobs", json={
            "name": f"Customer {letter}", "phone": f"(281) 555-{phone}", "address": f"100 {letter} Example Rd",
            "service": "mowing", "lawn_sqft": sqft, "yard_type": yard_type, "add_ons": list(add_ons),
            "scheduled_date": TOMORROW.isoformat(), "payment_method": method, "sms_consent": True})
    assert r.status_code == 201, r.text
    return r.json()


def test_booking_charges_the_yield_engine_price(client, repo):
    j = book_yield(client, yard_type="STEEP_SLOPES", sqft=10000, add_ons=["bin_cleaning", "gutters"])
    # 75 x 1.40 x 1.25 = 131.25 + $30 add-ons = 161.25 + 8.25% tax 13.30 = 174.55
    assert (j["subtotal"], j["tax"], j["total"], j["package"], j["charity_amount"]) == (161.25, 13.3, 174.55, None, 3.23)
    notes = {a["key"]: a for a in j["add_ons"] if a.get("info")}
    assert notes["yard_type"]["value"] == "STEEP_SLOPES" and notes["route_density"]["stops"] == 0
    saved = repo.jobs[j["id"]]
    assert saved["add_on_total"] == 30.0 and saved["service_minutes"] > 45
    v = client.get(f"/api/visit/{j['access_code']}").json()
    assert v["service_label"] == "Mowing + Bin cleaning + Gutter cleaning"      # notes are not add-ons


def test_neighbors_already_booked_give_the_density_discount(client):
    book_yield(client, "A", "0100"); book_yield(client, "A", "0101")
    third = book_yield(client, "A", "0102")
    # 2 bookings within half a mile: 5% off the $75 mow = 71.25 + tax 5.88
    assert (third["subtotal"], third["total"]) == (71.25, 77.13)
    note = next(a for a in third["add_ons"] if a["key"] == "route_density")
    assert (note["stops"], note["amount"]) == (2, -3.75) and note["label"] == "Route Cluster Optimization Benefit (2 stops)"
    far = book_yield(client, "Clv", "0103")                       # Cleveland: nobody nearby
    assert far["subtotal"] == 75.0


def test_crew_remeasure_keeps_the_yard_type_and_discount(client, repo, settings):
    book_yield(client, "A", "0100"); book_yield(client, "A", "0101")
    j = book_yield(client, "A", "0102", yard_type="COMPLEX_OBSTACLES", sqft=5000)
    assert j["subtotal"] == 81.94                                  # 86.25 - 5% (4.31)
    run_nightly(repo, settings, TOMORROW)
    stop = next(s for s in client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"] if s["job_id"] == j["id"])
    r = client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"lawn_sqft": 8000})
    # 75 x 1.24 x 1.15 = 106.95, 5% off (5.35) = 101.60, tax 8.38
    assert r.json()["payment"]["total"] == 109.98


def test_stripe_line_names_the_yard_type_and_discount(settings, repo):
    import httpx
    from urllib.parse import parse_qs
    from app.payments import StripeClient
    sent = {}

    def handler(req):
        sent.update({k: v[0] for k, v in parse_qs(req.content.decode()).items()})
        return httpx.Response(200, json={"id": "cs_1", "url": "https://checkout.stripe.test/1"})

    settings.stripe_secret_key = "sk_test"
    notes = [{"key": "yard_type", "label": "Yard type: Steep slopes", "price": None, "info": True, "value": "STEEP_SLOPES"},
             {"key": "route_density", "label": "Route Cluster Optimization Benefit (2 stops)", "price": None, "info": True,
              "stops": 2, "amount": -4.69}]
    StripeClient(settings, httpx.Client(transport=httpx.MockTransport(handler))).create_checkout(
        job_id="j1", service_label="Mowing", service_date="2026-10-20", amount_due=96.39, donation=0,
        success_url="https://x/ok", cancel_url="https://x/no", subtotal=89.06, tax=7.33, tax_rate=0.0825, add_ons=notes)
    assert sent["line_items[0][price_data][product_data][name]"] == \
        "Mowing, Steep slopes (2026-10-20), after a $4.69 route cluster discount"
    assert [sent[f"line_items[{i}][price_data][unit_amount]"] for i in (0, 1)] == ["8906", "733"]


def test_booking_form_asks_for_yard_type_not_tiers(client):
    t = client.get("/book").text
    assert "Your yard type" in t and "yard_type: yardKey" in t and "Guaranteed Enterprise Total" in t
    assert "data.package =" not in t and "Choose a rate" not in t
    info = client.get("/api/booking-info").json()["yield"]
    assert (info["base"], info["included_sqft"], info["step"], info["giving_rate"]) == (75.0, 5000, 0.08, 0.02)
    assert [y["key"] for y in info["yard_types"]] == ["STANDARD", "COMPLEX_OBSTACLES", "STEEP_SLOPES"]
