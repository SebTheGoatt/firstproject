"""Booking fills in an estimated lawn size from the address, so customers don't have to guess."""

from app.lawn_estimate import MIN_SAMPLE, estimate_lawn
from app.zones import zone_by_key

from .test_api_flow import NOW, TOMORROW, book
from unittest.mock import patch


def test_check_address_returns_a_typical_estimate_for_a_new_area(client):
    r = client.post("/api/check-address", json={"address": "100 A Example Rd"}).json()
    assert r["in_area"] is True
    assert r["lawn_estimate"] == {"sqft": 4500, "basis": "typical", "sample": 0, "zone_name": r["zone_name"]}


def test_outside_the_area_has_no_estimate(client):
    r = client.post("/api/check-address", json={"address": "100 Old Example Rd"}).json()
    assert r["in_area"] is False and r["lawn_estimate"] is None


def test_estimate_uses_crew_confirmed_lawns_once_there_are_enough(repo):
    zone = zone_by_key("SPRING_LUXURY_LOOP")

    class Repo:
        def __init__(self, sizes): self.sizes = sizes
        def recent_lawn_sizes(self, key, limit): assert key == zone.key; return self.sizes

    assert estimate_lawn(Repo([3000] * (MIN_SAMPLE - 1)), zone)["basis"] == "typical"
    e = estimate_lawn(Repo([3000, 3150, 6200, 3400, 2900]), zone)
    assert e == {"sqft": 3200, "basis": "recent", "sample": 5, "zone_name": zone.name}       # median 3150 → nearest 100

    class Broken:
        def recent_lawn_sizes(self, *a): raise RuntimeError("db down")
    assert estimate_lawn(Broken(), zone)["sqft"] == 4500                                      # never blocks the check


def test_memory_repo_reads_only_finished_jobs_in_the_zone(client, repo, settings):
    from app.nightly import run_nightly
    with patch("app.main.local_now", return_value=NOW):
        for i, letter in enumerate("AB"):
            assert book(client, letter, f"03{i:02d}").status_code == 201
    run_nightly(repo, settings, TOMORROW)
    assert repo.recent_lawn_sizes("SPRING_LUXURY_LOOP") == []                                 # booked, not finished
    stop = repo.get_route(TOMORROW)["stops"][0]
    repo.complete_stop(stop["stop_id"])
    assert repo.recent_lawn_sizes("SPRING_LUXURY_LOOP") == [5000]                             # the size from the booking
    assert repo.recent_lawn_sizes("KLEIN_CORE") == []
