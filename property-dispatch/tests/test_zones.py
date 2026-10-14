from unittest.mock import patch

import pytest

from app.zones import SERVICE_ZONES, ServiceZone, find_zone, validate_zones

from .test_api_flow import NOW, book


def test_each_zone_center_maps_to_that_zone():
    for z in SERVICE_ZONES:
        min_lng, min_lat, max_lng, max_lat = z.bbox
        assert find_zone((min_lat + max_lat) / 2, (min_lng + max_lng) / 2) is z


def test_edges_are_inclusive_and_just_outside_is_rejected():
    z = SERVICE_ZONES[0]
    min_lng, min_lat, max_lng, max_lat = z.bbox
    assert find_zone(min_lat, min_lng) is z and find_zone(max_lat, max_lng) is z
    assert find_zone(min_lat - 1e-4, min_lng) is None
    assert find_zone(max_lat, max_lng + 1e-4) is None


def test_lat_lng_are_not_swapped():
    # Passing (lng, lat) by mistake must not match anything.
    z = SERVICE_ZONES[0]
    assert find_zone(z.bbox[0], z.bbox[1]) is None


@pytest.mark.parametrize("bbox", [(-95.0, 30.2, -95.1, 30.3), (-95.1, 30.3, -95.0, 30.2), (30.2, -95.1, 30.3, -95.0)])
def test_validation_rejects_bad_boxes(bbox):
    with pytest.raises(ValueError):
        validate_zones((ServiceZone("X", "x", bbox, 10.0),))


def test_validation_rejects_overlap():
    a = ServiceZone("A", "a", (-95.4, 30.1, -95.2, 30.2), 50.0)
    b = ServiceZone("B", "b", (-95.3, 30.15, -95.1, 30.25), 40.0)
    with pytest.raises(ValueError, match="overlap"):
        validate_zones((a, b))


@pytest.mark.parametrize("letter, zone_key, price", [
    ("A", "SPRING_LUXURY_LOOP", 55.0),
    ("Spl", "I69_HIGH_DENSITY_SPINE", 40.0),
    ("Clv", "CLEVELAND_HUB", 45.0),
])
def test_intake_stores_zone_and_mow_price(client, repo, letter, zone_key, price):
    with patch("app.main.local_now", return_value=NOW):
        r = book(client, letter, "0100", service="mowing")
    assert r.status_code == 201, r.text
    assert r.json()["quoted_price"] == price
    job = repo.jobs[r.json()["id"]]
    assert job["zone_key"] == zone_key and job["quoted_price"] == price


def test_non_mowing_services_get_no_quoted_price(client, repo):
    with patch("app.main.local_now", return_value=NOW):
        r = book(client, "A", "0100", service="gutters")
    assert r.status_code == 201 and r.json()["quoted_price"] is None
    assert repo.jobs[r.json()["id"]]["zone_key"] == "SPRING_LUXURY_LOOP"


def test_out_of_zone_address_is_turned_away(client, repo):
    with patch("app.main.local_now", return_value=NOW):
        r = book(client, "Old", "0100")
    assert r.status_code == 422 and "outside our current service areas" in r.json()["detail"]
    assert not repo.jobs


def test_booking_info_lists_zones(client):
    zones = client.get("/api/booking-info").json()["zones"]
    assert [z["mow_rate"] for z in zones] == [55.0, 40.0, 45.0]
