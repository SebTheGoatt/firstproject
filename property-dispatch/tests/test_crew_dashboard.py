"""Crew dashboard: one-button route (/crew/dashboard), mid-day re-optimization and private stop notes."""

from datetime import datetime
from unittest.mock import patch

from app.nightly import run_nightly

from .test_api_flow import CREW, NOW, TOMORROW, TZ, book

ROUTE_DAY_MORNING = datetime(2026, 10, 15, 9, 0, tzinfo=TZ)     # the route's own day
CUTOFF_EVENING = datetime(2026, 10, 14, 18, 0, tzinfo=TZ)       # past 5 PM the day before


def booked(client, letters="ABCDE"):
    with patch("app.main.local_now", return_value=NOW):
        for i, letter in enumerate(letters):
            assert book(client, letter, f"02{i:02d}").status_code == 201


def optimize(client, when, **body):
    with patch("app.main.local_now", return_value=when):
        return client.post("/api/crew/optimize-route", json=body, headers=CREW)


def test_dashboard_page_is_served(client):
    r = client.get("/crew/dashboard")
    assert r.status_code == 200 and "START ROUTE TRANSIT" in r.text


def test_dashboard_is_a_field_hud(client):
    page = client.get("/crew/dashboard").text
    # Big button: start → arrived → a complete label that says what finishing does to the customer's bill.
    for label in ("START ROUTE TRANSIT", "ARRIVED ON SITE", "COMPLETE VISIT & INVOICE STRIPE", "COMPLETE VISIT & COLLECT CASH"):
        assert label in page
    # Scope enforcement block, with the lawn size filled in from the stop (never a fixed number).
    for text in ("SCOPE ENFORCEMENT", "COMPLIANCE LOCK", "FULL PARCEL ROTATION", "STANDARD VISIT"):
        assert text in page
    assert "4,500" not in page and "14,500" not in page
    # Mobile layout: 48px tap targets, a bottom sheet that moves with transform only, two columns when sideways.
    assert "--tap: 48px" in page and "translate3d" in page and "will-change: transform" in page
    assert "(orientation: landscape) and (min-width: 640px), (min-width: 900px)" in page
    # In-app directions stay the main action; the native Maps app is a plain link backup.
    assert "➤ Navigate" in page and "Open in Maps" in page and "apple_maps_url" in page and "google_maps_url" in page
    assert "OPERATIONAL BREAKDOWN" not in page and "START DAILY ROUTE" not in page


def test_route_stops_carry_what_the_hud_needs(client, repo, settings):
    booked(client, "AB")
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    for field in ("scope", "lawn_sqft", "service_minutes", "eta", "leg_distance_m", "leg_duration_s",
                  "payment_method", "payment_status", "amount_due", "apple_maps_url", "google_maps_url"):
        assert field in stop
    assert stop["apple_maps_url"].startswith("https://maps.apple.com/?")
    assert stop["google_maps_url"].startswith("https://www.google.com/maps/dir/?")


def test_crew_sign_in_is_required(client):
    assert client.post("/api/crew/optimize-route", json={}).status_code == 401
    assert client.put("/api/stops/x/note", json={"note": "hi"}).status_code == 401


def test_builds_a_locked_day_that_has_no_route_yet(client, repo):
    booked(client)
    r = optimize(client, CUTOFF_EVENING, day=TOMORROW.isoformat())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["built"] is True and body["remaining"] == 5 and body["used_gps"] is False
    assert [s["sequence"] for s in body["route"]["stops"]] == [1, 2, 3, 4, 5]
    assert all(s["service_minutes"] for s in body["route"]["stops"])


def test_unlocked_or_past_days_are_refused(client):
    booked(client)
    assert optimize(client, NOW, day=TOMORROW.isoformat()).status_code == 409        # before the 5 PM cutoff
    assert optimize(client, ROUTE_DAY_MORNING, day="2026-10-13").status_code == 409  # already passed


def test_reorders_only_open_stops_and_keeps_the_notified_customer_next(client, repo, settings):
    booked(client)
    run_nightly(repo, settings, TOMORROW)
    stops = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"]
    # Finish stop 1: the site tells the next customer they're next.
    client.post(f"/api/stops/{stops[0]['stop_id']}/complete", headers=CREW)
    told = stops[1]["stop_id"]

    # Re-plan from the far side of the area (near stop E's coordinates).
    r = optimize(client, ROUTE_DAY_MORNING, lat=30.16, lng=-95.32)
    assert r.status_code == 200, r.text
    body = r.json()
    new = body["route"]["stops"]
    assert body["used_gps"] and body["finished"] == 1 and body["kept_first"] == 1
    assert [s["sequence"] for s in new] == [1, 2, 3, 4, 5]                       # contiguous, nothing lost
    assert {s["stop_id"] for s in new} == {s["stop_id"] for s in stops}
    assert new[0]["stop_id"] == stops[0]["stop_id"] and new[0]["completed_at"]  # finished stays first
    assert new[1]["stop_id"] == told                                               # customer already told stays next
    etas = [datetime.fromisoformat(s["eta"]) for s in new[1:]]
    assert etas == sorted(etas) and etas[0] >= ROUTE_DAY_MORNING                  # ETAs move with the clock

    # Finishing the told stop notifies whichever stop is now next in the new order.
    r = client.post(f"/api/stops/{told}/complete", headers=CREW).json()
    assert r["notification"]["notified"] is True
    after = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"]
    assert after[2]["notified_at"] is not None


def test_no_gps_starts_from_the_last_finished_stop(client, repo, settings):
    booked(client, "ABC")
    run_nightly(repo, settings, TOMORROW)
    r = optimize(client, ROUTE_DAY_MORNING)
    assert r.status_code == 200 and r.json()["used_gps"] is False and r.json()["remaining"] == 3


def test_private_notes(client, repo, settings):
    booked(client, "AB")
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    r = client.put(f"/api/stops/{stop['stop_id']}/note", json={"note": "  Gate code changed to 4411  "}, headers=CREW)
    assert r.status_code == 200 and r.json()["note"] == "Gate code changed to 4411"
    assert client.get(f"/api/routes/{TOMORROW}/notes", headers=CREW).json() == {stop["stop_id"]: "Gate code changed to 4411"}
    assert client.put(f"/api/stops/{stop['stop_id']}/note", json={"note": "x" * 501}, headers=CREW).status_code == 422
    assert client.put("/api/stops/nope/note", json={"note": "hi"}, headers=CREW).status_code == 404
    client.put(f"/api/stops/{stop['stop_id']}/note", json={"note": ""}, headers=CREW)
    assert client.get(f"/api/routes/{TOMORROW}/notes", headers=CREW).json() == {}


# ---------- In-app turn-by-turn ----------
from app.directions import DirectionsUnavailable, instruction  # noqa: E402

OSRM_ROUTE = {"code": "Ok", "routes": [{"distance": 1500.4, "duration": 180.2,
    "geometry": {"coordinates": [[-95.39, 30.15], [-95.38, 30.15], [-95.38, 30.16]]},
    "legs": [{"steps": [
        {"name": "Avalon Springs Ln", "distance": 900, "duration": 100,
         "maneuver": {"type": "depart", "bearing_after": 90, "location": [-95.39, 30.15]}},
        {"name": "Kuykendahl Rd", "distance": 600, "duration": 80,
         "maneuver": {"type": "turn", "modifier": "left", "location": [-95.38, 30.15]}},
        {"name": "", "distance": 0, "duration": 0,
         "maneuver": {"type": "arrive", "modifier": "right", "location": [-95.38, 30.16]}}]}]}]}


def test_instructions_read_like_a_person_talking():
    assert instruction({"name": "Avalon Springs Ln", "maneuver": {"type": "depart", "bearing_after": 90}}) == "Head east on Avalon Springs Ln"
    assert instruction({"name": "Kuykendahl Rd", "maneuver": {"type": "turn", "modifier": "left"}}) == "Turn left onto Kuykendahl Rd"
    assert instruction({"name": "FM 1314", "maneuver": {"type": "turn", "modifier": "slight right"}}) == "Bear right onto FM 1314"
    assert instruction({"name": "", "maneuver": {"type": "off ramp", "modifier": "slight right"}}) == "Take the exit on the right"
    assert instruction({"name": "Main St", "maneuver": {"type": "roundabout", "exit": 2}}) == "At the roundabout, take the 2nd exit onto Main St"
    assert instruction({"name": "", "maneuver": {"type": "arrive", "modifier": "left"}}) == "Arrive at the stop on the left"
    assert instruction({"name": "Spring Cypress", "maneuver": {"type": "new name", "modifier": "straight"}}) == "Continue straight onto Spring Cypress"


def test_directions_endpoint_returns_path_and_steps(client, repo, settings):
    booked(client, "AB")
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return OSRM_ROUTE

    settings.osrm_url = "https://osrm.test"
    with patch("app.directions._http") as http:
        http.return_value.get.return_value = FakeResp()
        r = client.get(f"/api/crew/directions/{stop['stop_id']}?lat=30.15&lng=-95.39", headers=CREW)
    get = http.return_value.get
    assert r.status_code == 200, r.text
    body = r.json()
    assert get.call_args.args[0].startswith("https://osrm.test/route/v1/driving/-95.390000,30.150000;")
    assert [s["instruction"] for s in body["steps"]] == ["Head east on Avalon Springs Ln", "Turn left onto Kuykendahl Rd",
                                                         "Arrive at the stop on the right"]
    assert body["distance_m"] == 1500 and body["duration_s"] == 180 and len(body["path"]) == 3
    assert body["destination"] == [stop["lng"], stop["lat"]]


def test_directions_need_gps_sign_in_and_a_working_service(client, repo, settings):
    booked(client, "A")
    run_nightly(repo, settings, TOMORROW)
    sid = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]["stop_id"]
    assert client.get(f"/api/crew/directions/{sid}?lat=30.1&lng=-95.3").status_code == 401
    assert client.get(f"/api/crew/directions/{sid}", headers=CREW).status_code == 422
    assert client.get(f"/api/crew/directions/nope?lat=30.1&lng=-95.3", headers=CREW).status_code == 404
    r = client.get(f"/api/crew/directions/{sid}?lat=30.1&lng=-95.3", headers=CREW)   # tests have no OSRM_URL
    assert r.status_code == 503 and r.json()["detail"]


def test_crew_and_owner_pages_wear_the_post_one_look(client):
    """Post One crew look: every owner control is still on /crew, the HUD keeps its mark, the owner pages get the brand bar."""
    crew = client.get("/crew").text
    for piece in ('id="rain-day"', 'id="print-manifest"', 'href="/owner/readiness"', 'id="dash-refresh"', 'href="/crew/dashboard"',
                  'id="stops"', 'id="job-list"', 'id="live-station"', '<p class="crew-brandbar-name">Post One · <span>Crew</span></p>'):
        assert piece in crew, piece
    hud = client.get("/crew/dashboard").text
    assert 'src="/static/brand/post-one-mark.svg" alt=""' in hud and "--brass" in hud and "fonts.googleapis.com" not in hud
    for path in ("/owner/readiness", "/push-setup"):
        page = client.get(path).text
        assert '<p class="crew-brandbar-name">Post One · <span>Owner</span></p>' in page and "{{" not in page, path
        assert 'style="' not in page, path                       # styled from styles.css only
    assert '<body class="site page-team">' in client.get("/team").text
