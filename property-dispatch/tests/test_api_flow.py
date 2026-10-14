from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.nightly import compute_etas, run_nightly

TZ = ZoneInfo("America/Chicago")
NOW = datetime(2026, 10, 14, 10, 0, tzinfo=TZ)
TOMORROW = date(2026, 10, 15)
CREW = {"X-Crew-Token": "crew"}


def book(client, letter, phone_suffix, service="mowing", day=TOMORROW):
    return client.post("/api/jobs", json={
        "name": f"Customer {letter}",
        "phone": f"(281) 555-{phone_suffix}",
        "address": f"{letter} Example Rd",
        "service": service,
        "scheduled_date": day.isoformat(),
    })


def test_full_day_flow(client, repo, settings, sms):
    with patch("app.main.local_now", return_value=NOW):
        for i, letter in enumerate("ABCDE"):
            r = book(client, letter, f"01{i:02d}", service=["mowing", "gutters", "bin_cleaning"][i % 3])
            assert r.status_code == 201, r.text
            assert r.json()["lat"] and r.json()["lng"]

    # 8 PM freeze + optimize
    summary = run_nightly(repo, settings, TOMORROW)
    assert summary["stops"] == 5
    assert all(j.status == "scheduled" for j in repo.list_routable_jobs(TOMORROW))

    route = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()
    stops = route["stops"]
    assert [s["sequence"] for s in stops] == [1, 2, 3, 4, 5]
    assert all(s["google_maps_url"].startswith("https://www.google.com/maps/dir/") for s in stops)
    assert all(s["apple_maps_url"].startswith("https://maps.apple.com/") for s in stops)
    assert len(route["full_route_google_urls"]) == 1
    assert "origin=" in route["full_route_google_urls"][0]  # starts at base before any work
    assert route["timezone"] == "America/Chicago"
    etas = [datetime.fromisoformat(s["eta"]).astimezone(TZ) for s in stops]
    assert etas == sorted(etas) and etas[0].hour == 8

    # Crew completes stop 1 → stop 2's customer is texted
    r = client.post(f"/api/stops/{stops[0]['stop_id']}/complete", headers=CREW).json()
    assert r["notification"]["notified"] is True
    assert sms.sent[-1][0] == stops[1]["phone"]
    assert stops[1]["customer_name"].split()[0] in sms.sent[-1][1]

    # Retrying the same completion must not double-text
    r = client.post(f"/api/stops/{stops[0]['stop_id']}/complete", headers=CREW).json()
    assert r["notification"]["reason"] == "already_completed"
    assert len(sms.sent) == 1

    # Mid-day, the full-route link starts from live location
    route = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()
    assert "origin=" not in route["full_route_google_urls"][0]

    # Out of order: finishing 3 before 2 texts stop 4; finishing 2 then finds
    # stop 4 already texted and does not send again.
    client.post(f"/api/stops/{stops[2]['stop_id']}/complete", headers=CREW)
    assert sms.sent[-1][0] == stops[3]["phone"]
    r = client.post(f"/api/stops/{stops[1]['stop_id']}/complete", headers=CREW).json()
    assert r["notification"]["reason"] == "already_notified"
    assert len(sms.sent) == 2

    for s in stops[3:]:
        r = client.post(f"/api/stops/{s['stop_id']}/complete", headers=CREW).json()
    assert r["notification"]["reason"] == "route_complete"


def test_intake_enforces_freeze_and_quota(client, settings):
    after_cutoff = NOW.replace(hour=20, minute=5)
    with patch("app.main.local_now", return_value=after_cutoff):
        r = book(client, "A", "0100")
        assert r.status_code == 409 and "locked" in r.json()["detail"]

    settings.daily_job_quota = 2
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
        assert book(client, "B", "0101").status_code == 201
        r = book(client, "C", "0102")
        assert r.status_code == 409 and "fully booked" in r.json()["detail"]


def test_intake_validation_errors(client):
    with patch("app.main.local_now", return_value=NOW):
        r = client.post("/api/jobs", json={"name": "X", "phone": "123", "address": "A Example Rd",
                                           "service": "mowing", "scheduled_date": TOMORROW.isoformat()})
        assert r.status_code == 422
        r = client.post("/api/jobs", json={"name": "X", "phone": "2815550100", "address": "A Example Rd",
                                           "service": "pressure_washing", "scheduled_date": TOMORROW.isoformat()})
        assert r.status_code == 422


def test_auth_is_required(client, repo, settings):
    assert client.get(f"/api/routes/{TOMORROW}").status_code == 401
    assert client.get(f"/api/routes/{TOMORROW}", headers={"X-Crew-Token": "nope"}).status_code == 401
    assert client.post("/webhooks/job-completed", json={"stop_id": "x"}).status_code == 401
    assert client.post("/internal/nightly").status_code == 401


def test_webhook_and_http_nightly(client, repo, sms):
    with patch("app.main.local_now", return_value=NOW):
        book(client, "A", "0100")
        book(client, "B", "0101")
        r = client.post("/internal/nightly", headers={"X-Cron-Secret": "cron"})
    assert r.status_code == 200 and r.json()["stops"] == 2

    stops = repo.get_route(TOMORROW)["stops"]
    hook = {"X-Webhook-Secret": "hook"}

    # Supabase DB-webhook shape: non-completion updates are ignored
    r = client.post("/webhooks/job-completed", headers=hook,
                    json={"type": "UPDATE", "record": {"id": stops[0]["job_id"], "status": "scheduled"}})
    assert r.json()["ignored"] is True and not sms.sent

    r = client.post("/webhooks/job-completed", headers=hook,
                    json={"type": "UPDATE", "record": {"id": stops[0]["job_id"], "status": "completed"}})
    assert r.json()["notification"]["notified"] is True
    assert sms.sent[-1][0] == stops[1]["phone"]


def test_compute_etas():
    start = datetime(2026, 10, 15, 8, 0, tzinfo=TZ)
    etas = compute_etas(start, [(600, 45), (300, 15)])
    assert etas == [start + timedelta(minutes=10), start + timedelta(minutes=10 + 45 + 5)]


def test_supabase_mode_refuses_default_secrets():
    import pytest

    from app.config import Settings
    from app.main import create_app

    with pytest.raises(RuntimeError, match="CREW_ACCESS_TOKEN"):
        create_app(Settings(_env_file=None, data_backend="supabase"))


def test_geocoder_outage_is_503_not_422(settings, repo):
    import httpx
    from fastapi.testclient import TestClient

    from app.geocode import NominatimGeocoder
    from app.main import create_app

    down = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    nowhere = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    for http, code in ((down, 503), (nowhere, 422)):
        geo = NominatimGeocoder(settings, http)
        geo.MIN_INTERVAL_S = 0
        c = TestClient(create_app(settings, repo=repo, geocoder=geo, sms=None))
        with patch("app.main.local_now", return_value=NOW):
            assert book(c, "A", "0100").status_code == code


def test_nightly_main_time_guard_and_catch_up(monkeypatch, repo, settings):
    from app import nightly

    monkeypatch.setattr(nightly, "get_settings", lambda: settings)
    monkeypatch.setattr(nightly, "make_repository", lambda s: repo)
    calls = []
    real = nightly.run_nightly
    monkeypatch.setattr(nightly, "run_nightly", lambda r, s, d, **kw: calls.append(d) or real(r, s, d, **kw))

    def at(hour):
        monkeypatch.setattr(nightly, "local_now", lambda s: NOW.replace(hour=hour))
        return nightly.main([])

    at(19)                          # 7 PM: before the freeze → nothing
    assert calls == []
    at(21)                          # 8 PM run was missed; 9 PM catches up
    assert calls == [TOMORROW]
    at(22)                          # route exists → no rebuild
    assert calls == [TOMORROW]
    nightly.main(["--force"])       # explicit rebuild still works
    assert calls == [TOMORROW, TOMORROW]
