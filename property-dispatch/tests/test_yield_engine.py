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
