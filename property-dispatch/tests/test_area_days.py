"""One area per day: Mon Spring, Tue Klein, Wed New Caney & Splendora, Thu Colony Ridge, Fri Cleveland & Plum Grove.
The crew never drives from Cleveland to Spring in a day: booking, owner moves and the route all hold to it."""
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.nightly import run_nightly
from app.zones import SERVICE_ZONES, ServiceZone, schedule_text, validate_schedule, zone_by_key

from .test_api_flow import CREW, NOW, book

pytestmark = pytest.mark.area_days

MONDAY, THURSDAY, FRIDAY, SATURDAY = date(2026, 10, 19), date(2026, 10, 15), date(2026, 10, 16), date(2026, 10, 17)


def test_every_weekday_has_one_area_west_to_east():
    assert schedule_text() == "Mon Spring · Tue Klein · Wed New Caney & Splendora · Thu Colony Ridge · Fri Cleveland & Plum Grove"
    assert sorted(z.service_weekday for z in SERVICE_ZONES) == [0, 1, 2, 3, 4]
    two_mondays = (zone_by_key("SPRING_LUXURY_LOOP"), ServiceZone(key="X", name="X", bbox=(0, 0, 1, 1), mow_rate=1))
    with pytest.raises(ValueError, match="own weekday"):
        validate_schedule(two_mondays)


def test_an_address_books_only_on_its_area_day(client):
    with patch("app.main.local_now", return_value=NOW):
        wrong = book(client, "A", "0100", day=THURSDAY)          # Spring on a Thursday
        right = book(client, "A", "0101", day=MONDAY)
        cleveland = book(client, "Clv", "0102", day=MONDAY)      # Cleveland on Spring's day
    assert wrong.status_code == 409 and "Spring on Mondays only" in wrong.json()["detail"]
    assert right.status_code == 201, right.text
    assert cleveland.status_code == 409 and "Fridays" in cleveland.json()["detail"]


def test_address_check_offers_only_the_area_days(client):
    with patch("app.main.local_now", return_value=NOW):
        r = client.post("/api/check-address", json={"address": "100 Clv Example Rd"}).json()
    days = [date.fromisoformat(d["date"]) for d in r["service_days"]]
    assert r["service_weekday"] == "Friday" and r["area_short"] == "Cleveland & Plum Grove"
    assert days and all(d.weekday() == 4 for d in days) and days[0] == FRIDAY
    assert client.get("/api/booking-info").json()["schedule"][0] == {"weekday": "Monday", "area": "Spring",
                                                                      "zone_key": "SPRING_LUXURY_LOOP"}


def test_route_leaves_off_a_visit_from_another_area(client, repo, settings):
    with patch("app.main.local_now", return_value=NOW):
        spring = book(client, "A", "0100", day=MONDAY).json()
        clv = book(client, "Clv", "0101", day=FRIDAY).json()
    repo.jobs[clv["id"]]["scheduled_date"] = MONDAY             # e.g. typed in by hand
    summary = run_nightly(repo, settings, MONDAY)
    assert summary["stops"] == 1 and summary["off_area"] == [clv["id"]]
    assert [s["job_id"] for s in repo.get_route(MONDAY)["stops"]] == [spring["id"]]


def test_owner_moves_stay_on_the_area_day_or_saturday(client):
    with patch("app.main.local_now", return_value=NOW):
        job = book(client, "A", "0100", day=MONDAY).json()
    with patch("app.changes.local_now", return_value=NOW):
        bad = client.post(f"/api/owner/jobs/{job['id']}/move", json={"day": str(THURSDAY)}, headers=CREW)
        sat = client.post(f"/api/owner/jobs/{job['id']}/move", json={"day": str(SATURDAY)}, headers=CREW)
        nxt = client.post(f"/api/owner/jobs/{job['id']}/move", json={"day": str(MONDAY + timedelta(days=7))}, headers=CREW)
    assert bad.status_code == 422 and "Spring is mowed on Mondays" in bad.json()["detail"]
    assert sat.status_code == 200 and nxt.status_code == 200
