"""Live visitor feed: /api/track, owner-only /api/live/stats (dashboard lives in
the crew app's owner Dashboard tab), and the booking counter wired into
POST /api/jobs (counted once per job)."""
from datetime import date, timedelta

import pytest

import app.live_feed as live_feed

TOMORROW_PLUS = date.today() + timedelta(days=3)   # safely inside the booking window
OWNER = {"X-Crew-Token": "crew"}                  # master code, as in the crew tests


@pytest.fixture
def live(client, tmp_path):
    """Reset the feed's module state between tests."""
    live_feed.DATA_FILE = tmp_path / "live_stats.json"
    live_feed._day.update(date=None, visits=0, bookings=0, exits=0)
    live_feed._funnel = [0] * 6
    for d in (live_feed._sessions, live_feed._session_steps, live_feed._last_pageview,
              live_feed._last_pid, live_feed._last_exit_pid, live_feed._pending_exits,
              live_feed._committed_exit_pids, live_feed._exit_steps, live_feed._rate,
              live_feed._booked_jobs):
        d.clear()
    live_feed._counted_visits.clear()
    live_feed._recent.clear()
    live_feed._last_persist = 0.0
    return client


def track(client, **kw):
    return client.post("/api/track", json=kw)


def stats(client, token=None):
    headers = {"X-Crew-Token": token} if token else {}
    return client.get("/api/live/stats", headers=headers)


def owner_session_token(client):
    """A signed owner token from the real owner-login endpoint."""
    r = client.post("/api/crew/login/owner", json={"code": "crew"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def crew_member_token(client):
    """Create a crew member and return their session token."""
    r = client.post("/api/crew/members", headers=OWNER,
                   json={"display_name": "Sam Rivera", "code": "4321", "role_title": "Lead Mower"})
    assert r.status_code == 201, r.text
    member_id = r.json()["id"]
    r = client.post("/api/crew/login", json={"member_id": member_id, "code": "4321"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def book_job(client, letter="A"):
    return client.post("/api/jobs", json={
        "name": f"Customer {letter}", "phone": "(281) 555-0101", "address": f"100 {letter} Example Rd",
        "service": "mowing", "lawn_sqft": 5000, "package": "standard",
        "scheduled_date": TOMORROW_PLUS.isoformat(),
    })


def test_tracker_tag_on_public_pages(live):
    for path in ("/", "/book", "/team"):
        r = live.get(path)
        assert r.status_code == 200
        assert "/static/tracker.js" in r.text, path


def test_no_standalone_dashboard_route_or_page(live):
    # The live station has no page of its own: it lives inside the owner's
    # crew-app Dashboard tab. There is no /live route and no static/live.html.
    assert live.get("/live").status_code == 404
    assert live.get("/static/live.html").status_code == 404
    # No link to /live or /static/live.html from any public page.
    for path in ("/", "/book", "/team", "/crew"):
        body = live.get(path).text
        assert "/live" not in body.replace("/api/live", ""), path


def test_stats_is_owner_only(live):
    # public: rejected
    assert stats(live).status_code == 401
    assert stats(live, "forged-token").status_code == 401
    # crew member: rejected with 403 — the station is not for crew logins
    member_tok = crew_member_token(live)
    assert stats(live, member_tok).status_code == 403
    # owner: master code AND a signed owner session token both work
    assert stats(live, "crew").status_code == 200
    assert stats(live, owner_session_token(live)).status_code == 200


def test_track_events_and_rejections(live):
    assert track(live, event="pageview", sid="sess-aaaaaa", pid="page-111111", path="home").status_code == 200
    assert track(live, event="step", sid="sess-aaaaaa", pid="page-111111", path="booking", step=1).status_code == 200
    # raw URL paths are coerced to a safe label, never stored
    assert track(live, event="pageview", sid="sess-aaaaaa", pid="page-111111", path="/visit/SECRET").status_code == 200
    # invalid payloads are rejected
    assert track(live, event="pageview", sid="bad sid!", path="home").status_code == 400
    assert track(live, event="bogus", sid="sess-aaaaaa", path="home").status_code == 400
    assert track(live, event="exit", sid="sess-aaaaaa", pid="bad pid!", path="home").status_code == 400


def test_stats_counts_visits_and_funnel(live):
    track(live, event="pageview", sid="sess-aaaaaa", pid="page-111111", path="home")
    track(live, event="step", sid="sess-aaaaaa", pid="page-111111", path="booking", step=1)
    track(live, event="step", sid="sess-aaaaaa", pid="page-111111", path="booking", step=1)   # dedupe
    track(live, event="step", sid="sess-bbbbbb", pid="page-222222", path="booking", step=2)
    data = stats(live, "crew").json()
    assert data["today"]["visits"] == 1
    assert data["funnel"][0] == {"step": 1, "label": "Lawn size entered", "count": 1}
    assert data["funnel"][1]["count"] == 1     # rate chosen by the second visitor


def test_immediate_departure_is_not_swallowed(live):
    # A visitor who leaves one second after arriving still counts: the exit
    # beacon's page id matches the latest pageview, so it's a real departure —
    # no timing heuristic mislabels it as internal navigation.
    track(live, event="pageview", sid="sess-quickk", pid="page-quick1", path="home")
    track(live, event="exit", sid="sess-quickk", pid="page-quick1", path="home", dwell_ms=1000)
    live_feed._pending_exits["sess-quickk"]["ts"] -= 60   # grace has passed
    track(live, event="ping", sid="sess-otherx", pid="page-other1", path="home")
    data = stats(live, "crew").json()
    assert data["today"]["visits"] == 1, data["today"]
    assert data["today"]["exits"] == 1, data["today"]


def test_internal_navigation_in_order(live):
    # Exit beacon lands before the next page's pageview.
    track(live, event="pageview", sid="sess-aaaaaa", pid="page-111111", path="home")
    track(live, event="exit", sid="sess-aaaaaa", pid="page-111111", path="home", dwell_ms=30000)
    track(live, event="pageview", sid="sess-aaaaaa", pid="page-222222", path="booking")
    data = stats(live, "crew").json()
    assert data["today"]["visits"] == 1, data["today"]
    assert data["today"]["exits"] == 0, data["today"]

    # Milestone dedupe survives the internal navigation: the new page
    # re-reports step 1, but the session already reached it.
    track(live, event="step", sid="sess-aaaaaa", pid="page-222222", path="booking", step=1)
    data = stats(live, "crew").json()
    assert data["funnel"][0]["count"] == 1, data["funnel"]


def test_internal_navigation_out_of_order(live):
    # The old page's exit beacon lands AFTER the new pageview.
    track(live, event="pageview", sid="sess-aaaaaa", pid="page-111111", path="home")
    track(live, event="pageview", sid="sess-aaaaaa", pid="page-222222", path="booking")
    track(live, event="exit", sid="sess-aaaaaa", pid="page-111111", path="home", dwell_ms=30000)
    data = stats(live, "crew").json()
    assert data["today"]["visits"] == 1, data["today"]      # one visit, still browsing
    assert data["today"]["exits"] == 0, data["today"]

    # Replaying the stale exit changes nothing (no double counting, no
    # visit subtraction).
    track(live, event="exit", sid="sess-aaaaaa", pid="page-111111", path="home", dwell_ms=30000)
    track(live, event="exit", sid="sess-aaaaaa", pid="page-111111", path="home", dwell_ms=30000)
    data = stats(live, "crew").json()
    assert data["today"]["visits"] == 1, data["today"]
    assert data["today"]["exits"] == 0, data["today"]


def test_return_visit_counts_again(live):
    # After a real departure, the same tab coming back is a new visit.
    track(live, event="pageview", sid="sess-aaaaaa", pid="page-111111", path="home")
    track(live, event="exit", sid="sess-aaaaaa", pid="page-111111", path="home", dwell_ms=60000)
    live_feed._pending_exits["sess-aaaaaa"]["ts"] -= 60          # grace has passed
    track(live, event="ping", sid="sess-cccccc", pid="page-333333", path="home")
    data = stats(live, "crew").json()
    assert data["today"]["visits"] == 1 and data["today"]["exits"] == 1
    track(live, event="pageview", sid="sess-aaaaaa", pid="page-444444", path="home")
    data = stats(live, "crew").json()
    assert data["today"]["visits"] == 2, data["today"]
    assert data["today"]["exits"] == 1, data["today"]


def test_booking_counted_once_per_job(live):
    for letter in "AB":
        r = book_job(live, letter)
        assert r.status_code == 201, r.text
    data = stats(live, "crew").json()
    assert data["today"]["bookings"] == 2
    assert data["funnel"][4] == {"step": 5, "label": "Booked", "count": 2}


def test_first_booking_retry_after_rollover(live):
    # Day rolls over; the day's first booking with a job id is counted even
    # when its retry follows immediately (dedupe is applied after rollover).
    live_feed._day["date"] = "2000-01-01"
    live_feed._booked_jobs.add("job-1")          # stale id from "yesterday"
    live_feed.record_booking(job_id="job-1")
    live_feed.record_booking(job_id="job-1")      # retry
    assert live_feed._day["bookings"] == 1, live_feed._day


def test_replayed_exit_after_commit_counts_once(live):
    # pageview -> departure -> commit -> identical replayed beacon -> commit
    # again: still one visit, one departure.
    track(live, event="pageview", sid="sess-aaaaaa", pid="page-111111", path="home")
    track(live, event="exit", sid="sess-aaaaaa", pid="page-111111", path="home", dwell_ms=60000)
    live_feed._pending_exits["sess-aaaaaa"]["ts"] -= 60          # grace has passed
    track(live, event="ping", sid="sess-cccccc", pid="page-333333", path="home")  # prune
    data = stats(live, "crew").json()
    assert data["today"]["visits"] == 1 and data["today"]["exits"] == 1

    # replay the identical exit beacon: it must be ignored outright (no new
    # pending exit, no double count) — the committed-departure record blocks it
    track(live, event="exit", sid="sess-aaaaaa", pid="page-111111", path="home", dwell_ms=60000)
    track(live, event="exit", sid="sess-aaaaaa", pid="page-111111", path="home", dwell_ms=60000)
    assert "sess-aaaaaa" not in live_feed._pending_exits
    track(live, event="ping", sid="sess-cccccc", pid="page-333333", path="home")
    data = stats(live, "crew").json()
    assert data["today"]["visits"] == 1, data["today"]
    assert data["today"]["exits"] == 1, data["today"]

    # a NEW page load in the same tab departing again is a second departure
    track(live, event="pageview", sid="sess-aaaaaa", pid="page-555555", path="home")
    track(live, event="exit", sid="sess-aaaaaa", pid="page-555555", path="home", dwell_ms=30000)
    live_feed._pending_exits["sess-aaaaaa"]["ts"] -= 60
    track(live, event="ping", sid="sess-cccccc", pid="page-333333", path="home")
    data = stats(live, "crew").json()
    assert data["today"]["visits"] == 2, data["today"]
    assert data["today"]["exits"] == 2, data["today"]

    # replaying the FIRST departure's beacon after the second committed must
    # not create a third: records are keyed by (sid, pid), not just the latest.
    track(live, event="exit", sid="sess-aaaaaa", pid="page-111111", path="home", dwell_ms=60000)
    assert "sess-aaaaaa" not in live_feed._pending_exits
    track(live, event="ping", sid="sess-cccccc", pid="page-333333", path="home")
    data = stats(live, "crew").json()
    assert data["today"]["visits"] == 2, data["today"]
    assert data["today"]["exits"] == 2, data["today"]


def test_exit_lands_in_drop_off(live):
    track(live, event="pageview", sid="sess-aaaaaa", pid="page-111111", path="booking")
    track(live, event="step", sid="sess-aaaaaa", pid="page-111111", path="booking", step=4)
    track(live, event="exit", sid="sess-aaaaaa", pid="page-111111", path="booking", step=4, dwell_ms=60000)
    live_feed._pending_exits["sess-aaaaaa"]["ts"] -= 60          # grace has passed
    track(live, event="ping", sid="sess-cccccc", pid="page-333333", path="home")
    data = stats(live, "crew").json()
    assert data["today"]["exits"] == 1
    assert data["drop_off"].get("Submit clicked") == 1, data["drop_off"]
