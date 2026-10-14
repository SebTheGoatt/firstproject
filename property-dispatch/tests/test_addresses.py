"""Real street addresses: house-number lookup, fallbacks, and navigation by address."""

from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.geocode import AddressGeocoder, GeocoderUnavailable, GeocodingError, street_variants
from app.zones import find_zone

from .test_api_flow import CREW, NOW, TOMORROW

CENSUS_HIT = {"result": {"addressMatches": [{
    "coordinates": {"x": -95.492095, "y": 30.059987},
    "matchedAddress": "4726 WHISPERING ROCK LN, SPRING, TX, 77388",
}]}}
CENSUS_MISS = {"result": {"addressMatches": []}}


def geocoder(settings, handler):
    g = AddressGeocoder(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    g.MIN_INTERVAL_S = 0
    return g


def test_census_finds_the_exact_house(settings):
    seen = []

    def handler(req):
        seen.append(req.url.host)
        return httpx.Response(200, json=CENSUS_HIT)

    geo = geocoder(settings, handler).geocode("4726 Whispering Rock Lane, Spring, Tx 77388")
    assert (round(geo.lat, 4), round(geo.lng, 4)) == (30.06, -95.4921)
    assert geo.formatted_address == "4726 Whispering Rock Ln, Spring, TX 77388"
    assert geo.precision == "address"
    assert seen == ["geocoding.geo.census.gov"]  # no need to ask anyone else


def test_new_subdivision_falls_back_to_street(settings):
    queries = []

    def handler(req):
        if req.url.host == "geocoding.geo.census.gov":
            return httpx.Response(200, json=CENSUS_MISS)
        q = req.url.params["q"]
        queries.append(q)
        if q == "Woodhill Spa Ln, TX 77327":  # only the street + ZIP form is known
            return httpx.Response(200, json=[{"lat": "30.3378", "lon": "-95.0604", "addresstype": "road",
                                              "display_name": "Woodhill Spa Lane, Cleveland"}])
        return httpx.Response(200, json=[])

    geo = geocoder(settings, handler).geocode("10340 Woodhill Spa Ln, Cleveland, TX 77327")
    assert queries == ["10340 Woodhill Spa Ln, Cleveland, TX 77327",
                       "Woodhill Spa Ln, Cleveland, TX 77327",
                       "Woodhill Spa Ln, TX 77327"]
    assert geo.precision == "street"
    assert find_zone(geo.lat, geo.lng).key == "CLEVELAND_HUB"


def test_census_outage_still_uses_osm(settings):
    def handler(req):
        if req.url.host == "geocoding.geo.census.gov":
            return httpx.Response(503)
        return httpx.Response(200, json=[{"lat": "30.1", "lon": "-95.3", "addresstype": "house"}])

    assert geocoder(settings, handler).geocode("1 Main St, Spring, TX 77386").precision == "address"


def test_not_found_vs_unavailable(settings):
    with pytest.raises(GeocoderUnavailable):
        geocoder(settings, lambda r: httpx.Response(500)).geocode("1 Main St, Spring, TX 77386")

    def nothing(req):
        return httpx.Response(200, json=CENSUS_MISS if req.url.host.startswith("geocoding") else [])

    with pytest.raises(GeocodingError) as exc:
        geocoder(settings, nothing).geocode("1 Nowhere St, Spring, TX 77386")
    assert not isinstance(exc.value, GeocoderUnavailable)


@pytest.mark.parametrize("address, expected", [
    ("4726 Whispering Rock Lane, Spring, Tx 77388",
     ["Whispering Rock Lane, Spring, Tx 77388", "Whispering Rock Lane, TX 77388"]),
    ("12B Oak Ln, Spring, TX 77386-1234", ["Oak Ln, Spring, TX 77386-1234", "Oak Ln, TX 77386"]),
    ("Trinity Park Lane, TX 77386", ["Trinity Park Lane, TX 77386"][:0]),  # nothing looser to try
])
def test_street_variants(address, expected):
    assert street_variants(address) == expected


@pytest.mark.parametrize("address", ["Whispering Rock Lane, Spring, TX 77388", "Oak Forest Lane", "   "])
def test_booking_requires_a_house_number(client, address):
    with patch("app.main.local_now", return_value=NOW):
        r = client.post("/api/jobs", json={"name": "X", "phone": "2815550100", "address": address,
                                           "service": "mowing", "scheduled_date": TOMORROW.isoformat()})
    assert r.status_code == 422


def test_crew_sees_and_navigates_to_the_typed_address(client, repo, settings):
    from app.nightly import run_nightly

    typed = "4726 Whispering Rock Ln, Spring, TX 77388"
    with patch("app.main.local_now", return_value=NOW):
        r = client.post("/api/jobs", json={"name": "Pat Doe", "phone": "2815550100", "address": "100 A " + typed[5:],
                                           "service": "mowing", "scheduled_date": TOMORROW.isoformat()})
    assert r.status_code == 201
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    assert stop["address"] == "100 A " + typed[5:]
    assert parse_qs(urlparse(stop["google_maps_url"]).query)["destination"] == [stop["address"]]
    assert parse_qs(urlparse(stop["apple_maps_url"]).query)["daddr"] == [stop["address"]]


@pytest.mark.parametrize("lat, lng", [(30.2244, -95.2369), (30.2304, -95.2335), (30.2270, -95.2359)])
def test_the_canopies_is_in_the_i69_zone(lat, lng):
    assert find_zone(lat, lng).key == "I69_HIGH_DENSITY_SPINE"
