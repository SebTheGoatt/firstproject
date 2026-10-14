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


# Same price in every area: $50 + typical lot (4,500 sq ft) × 0.9¢ (Standard) = $90.50
@pytest.mark.parametrize("letter, zone_key, price", [
    ("A", "SPRING_LUXURY_LOOP", 90.5),
    ("Spl", "I69_HIGH_DENSITY_SPINE", 90.5),
    ("Clv", "CLEVELAND_HUB", 90.5),
])
def test_intake_stores_zone_and_mow_price(client, repo, letter, zone_key, price):
    with patch("app.main.local_now", return_value=NOW):
        r = book(client, letter, "0100", service="mowing")
    assert r.status_code == 201, r.text
    assert r.json()["quoted_price"] == price
    job = repo.jobs[r.json()["id"]]
    assert job["zone_key"] == zone_key and job["quoted_price"] == price


def test_bins_and_gutters_are_add_ons_not_stand_alone_bookings(client, repo):
    with patch("app.main.local_now", return_value=NOW):
        r = book(client, "A", "0100", service="gutters")
    assert r.status_code == 422 and "add-ons to a mowing visit" in r.json()["detail"]
    assert not repo.jobs


def test_out_of_zone_address_is_turned_away(client, repo):
    with patch("app.main.local_now", return_value=NOW):
        r = book(client, "Old", "0100")
    assert r.status_code == 422 and "outside our current service areas" in r.json()["detail"]
    assert not repo.jobs


def test_booking_info_lists_zones(client):
    zones = client.get("/api/booking-info").json()["zones"]
    assert [z["mow_rate"] for z in zones] == [50.0, 50.0, 50.0, 50.0]  # one $50 minimum everywhere
    assert all(len(z["bbox"]) == 4 for z in zones)


@pytest.mark.parametrize("lat, lng, key", [
    (30.1160, -95.3636, "SPRING_LUXURY_LOOP"),   # Woodson's Reserve
    (30.3391, -95.0579, "CLEVELAND_HUB"),        # Kingston Heath Dr, Grand Oaks Reserve
    (30.3367, -95.0506, "CLEVELAND_HUB"),        # Spyglass Hill Dr, Grand Oaks clubhouse
    (30.3415, -95.0900, "CLEVELAND_HUB"),        # downtown Cleveland
])
def test_zones_cover_the_places_they_are_named_for(lat, lng, key):
    assert find_zone(lat, lng).key == key


@pytest.mark.parametrize("lat, lng, place", [
    (30.0600, -95.4921, "4726 Whispering Rock Ln, 77388"),
    (30.0198, -95.5224, "Klein High School, 77379"),
    (30.0633, -95.4762, "Klein Collins High School, 77388"),
    (30.0278, -95.5622, "9000 Spring Cypress Rd, 77379"),
    (30.0675, -95.4501, "2400 Spring Cypress Rd, 77388"),
])
def test_klein_covers_77379_and_77388(lat, lng, place):
    assert find_zone(lat, lng).key == "KLEIN_CORE", place


@pytest.mark.parametrize("lat, lng, place", [
    (30.0947, -95.5172, "Klein Oak HS, 77389 (not in core Klein)"),
    (30.0766, -95.4166, "Old Town Spring, east of I-45"),
])
def test_klein_stops_at_its_edges(lat, lng, place):
    assert find_zone(lat, lng) is None, place
