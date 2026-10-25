"""The owner's dispatch board: the day's route, its road path, the schedule against working hours, and every
visit that won't be on the route (with the reason)."""

from unittest.mock import patch

import httpx

from app.directions import DirectionsUnavailable, route_path
from app.dispatch_board import finish_time, hours_for

from .test_api_flow import CREW, NOW, TOMORROW
from .test_visit_owner import booked


def built(client, letters="ABC"):
    for i, L in enumerate(letters):
        booked(client, L, f"01{i:02d}")
    with patch("app.visit_routes.local_now", return_value=NOW):
        assert client.post(f"/api/owner/routes/{TOMORROW}/build", headers=CREW).status_code == 200


def test_board_shows_the_route_schedule_and_money(client, settings):
    built(client)
    d = client.get(f"/api/owner/dispatch/{TOMORROW}", headers=CREW).json()
    assert [s["sequence"] for s in d["route"]["stops"]] == [1, 2, 3]
    assert d["hours"] == {"start": "08:00", "end": "17:00"} and d["base"]["lat"]
    assert d["finish_at"] and d["close_at"].startswith(f"{TOMORROW}T17:00") and d["minutes_to_spare"] > 0
    assert d["on_site_min"] == sum(s["service_minutes"] for s in d["route"]["stops"])
    assert d["money"]["expected"] > 0 and d["unrouted"] == [] and d["areas"][0]["boxes"]
    assert d["path"] is None                                   # tests never call OSRM: the page draws straight legs


def test_board_lists_visits_that_wont_be_routed_and_why(client):
    built(client, "AB")
    booked(client, "C", "0109")                                # booked after the route was built
    d = client.get(f"/api/owner/dispatch/{TOMORROW}", headers=CREW).json()
    [late] = d["unrouted"]
    # Test addresses are all in Spring and the test day is a Thursday (Colony Ridge), so the board says so first.
    assert late["customer_name"] == "Customer C" and "area" in late["reason"]


def test_unrouted_reasons(settings):
    from app.dispatch_board import unrouted_reason
    job = {"zone_key": "SPRING_LUXURY_LOOP", "payment_method": "card", "payment_status": "unpaid"}
    assert "area" in unrouted_reason(job, settings, "KLEIN_CORE")
    assert "rebuild" in unrouted_reason(job, settings, "SPRING_LUXURY_LOOP")      # no Stripe in tests: not a pay hold
    settings.stripe_secret_key = "sk_test_x"
    if settings.stripe_enabled:
        assert "Not paid" in unrouted_reason(job, settings, "SPRING_LUXURY_LOOP")


def test_board_is_owner_only_and_the_page_loads(client):
    assert client.get(f"/api/owner/dispatch/{TOMORROW}").status_code in (401, 403)
    page = client.get("/owner/dispatch")
    assert page.status_code == 200 and "noindex" in page.headers.get("x-robots-tag", "")
    assert "buildings.pmtiles" in page.text and "/api/owner/dispatch/" in page.text
    assert 'href="/owner/dispatch"' in client.get("/owner/command").text


def test_hours_and_finish_time(settings):
    from datetime import date
    assert hours_for(settings, date(2026, 10, 26)) == ("08:00", "17:00")        # Monday
    assert hours_for(settings, date(2026, 10, 31)) == ("08:00", "14:00")        # Saturday make-ups
    assert hours_for(settings, date(2026, 11, 1)) is None                       # Sunday
    assert finish_time([]) is None


def test_road_path_reads_osrm_and_fails_softly():
    def handler(request):
        assert "-95.400000,30.100000;-95.300000,30.200000" in str(request.url)
        return httpx.Response(200, json={"code": "Ok", "routes": [{"distance": 1609.3, "duration": 600,
            "geometry": {"coordinates": [[-95.4, 30.1], [-95.3, 30.2]]}, "legs": [{"distance": 1609.3, "duration": 600}]}]})
    out = route_path("https://osrm.test", [(30.1, -95.4), (30.2, -95.3)], client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert out == {"distance_m": 1609, "duration_s": 600, "path": [[-95.4, 30.1], [-95.3, 30.2]],
                   "legs": [{"distance_m": 1609, "duration_s": 600}]}
    for bad in ("", ):
        try:
            route_path(bad, [(30.1, -95.4), (30.2, -95.3)]); assert False
        except DirectionsUnavailable:
            pass
