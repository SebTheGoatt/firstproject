"""Booking fills in an estimated lawn size from the address, so customers don't have to guess."""

from app.lawn_estimate import MIN_SAMPLE, estimate_lawn
from app.zones import zone_by_key

from .test_api_flow import NOW, TOMORROW, book
from unittest.mock import patch


def test_check_address_returns_a_typical_estimate_for_a_new_area(client):
    r = client.post("/api/check-address", json={"address": "100 A Example Rd"}).json()
    assert r["in_area"] is True
    assert r["lawn_estimate"] == {"sqft": 4500, "full_sqft": 8000, "basis": "typical", "sample": 0, "zone_name": r["zone_name"]}


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
    assert e == {"sqft": 3200, "full_sqft": zone.full_property_sqft, "basis": "recent", "sample": 5, "zone_name": zone.name}

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



# ---------- Yard only / Full property: server-set size, locked price ----------
from app.zones import SERVICE_ZONES  # noqa: E402

CREW = {"X-Crew-Token": "crew"}


def scoped_booking(client, scope, lawn_sqft=None, letter="A", suffix="0400", method="cash"):
    body = {"name": f"Customer {letter}", "phone": f"(281) 555-{suffix}", "address": f"100 {letter} Example Rd",
            "service": "mowing", "package": "supporter", "scheduled_date": TOMORROW.isoformat(),
            "add_ons": [scope], "payment_method": method}
    if lawn_sqft is not None:
        body["lawn_sqft"] = lawn_sqft
    with patch("app.main.local_now", return_value=NOW):
        return client.post("/api/jobs", json=body)


def test_every_area_has_sensible_yard_and_full_sizes():
    for z in SERVICE_ZONES:
        assert 1000 <= z.yard_sqft < z.full_property_sqft <= 87_120
    cleveland = zone_by_key("CLEVELAND_HUB")
    assert cleveland.full_property_sqft == 14_500 and zone_by_key("COLONY_RIDGE").full_property_sqft == 14_500


def test_quote_prices_the_area_size_not_the_browsers_number(client):
    q = client.post("/api/quote", json={"address": "100 A Example Rd", "service": "mowing", "package": "supporter",
                                         "lawn_sqft": 200, "add_ons": ["scope_full"]}).json()
    assert q["lawn_sqft"] == 8000 and q["subtotal"] == 115.0 and q["total"] == round(115 * 1.0825, 2)   # $35 + 8,000 × $0.010
    q = client.post("/api/quote", json={"address": "100 A Example Rd", "service": "mowing", "package": "supporter",
                                         "add_ons": ["scope_yard"]}).json()
    assert q["lawn_sqft"] == 4500 and q["total"] == 86.6


def test_booking_with_full_property_is_sized_by_the_server(client, repo):
    r = scoped_booking(client, "scope_full", lawn_sqft=500)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["lawn_sqft"] == 8000 and body["subtotal"] == 115.0
    assert [a["key"] for a in body["add_ons"]] == ["scope_full"] and body["add_on_total"] == 0


def test_choosing_both_areas_is_refused(client):
    r = client.post("/api/quote", json={"address": "100 A Example Rd", "service": "mowing", "package": "supporter",
                                         "add_ons": ["scope_yard", "scope_full"]})
    assert r.status_code == 422


def test_locked_bookings_are_not_re_priced_on_site(client, repo, settings):
    from app.nightly import run_nightly
    assert scoped_booking(client, "scope_yard").status_code == 201
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    assert stop["service_label"] == "Mowing + Yard only"                       # the crew sees what was booked
    r = client.post(f"/api/stops/{stop['stop_id']}/complete", json={"lawn_sqft": 12000, "cash_collected": 86.60}, headers=CREW)
    assert r.status_code == 200, r.text
    assert r.json()["payment"]["total"] == 86.6                                 # locked: still the booked price
    assert repo.get_stop(stop["stop_id"])["lawn_sqft"] == 4500


def test_scope_choices_are_not_offered_as_add_on_checkboxes(client):
    info = client.get("/api/booking-info").json()
    scopes = [a["key"] for a in info["add_ons"] if a["scope"]]
    assert scopes == ["scope_yard", "scope_full"]


def test_stop_time_scales_with_lawn_size():
    from app.pricing import mow_minutes
    assert (mow_minutes(None), mow_minutes(2500), mow_minutes(4500), mow_minutes(8000), mow_minutes(14500)) == (45, 45, 45, 61, 90)


def test_crew_stop_carries_the_scope_and_a_longer_full_property_visit(client, repo, settings):
    from app.nightly import run_nightly
    assert scoped_booking(client, "scope_full", letter="A", suffix="0410").status_code == 201
    assert scoped_booking(client, "scope_yard", letter="B", suffix="0411").status_code == 201
    run_nightly(repo, settings, TOMORROW)
    stops = {s["scope"]: s for s in client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"]}
    assert stops["scope_full"]["lawn_sqft"] == 8000 and stops["scope_full"]["service_minutes"] == 61
    assert stops["scope_yard"]["lawn_sqft"] == 4500 and stops["scope_yard"]["service_minutes"] == 45
