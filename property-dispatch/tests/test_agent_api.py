"""StarNet agent gateway: separate keys, no personal details, ops-only actions, audit log."""

from unittest.mock import patch

import pytest

from app import agent_api
from app.nightly import run_nightly

from .test_api_flow import CREW, NOW, TOMORROW, book

READ = {"X-Agent-Key": "read-key-123"}
OPS = {"X-Agent-Key": "ops-key-456"}


@pytest.fixture
def on(settings):
    settings.agent_key_read, settings.agent_key_ops = "read-key-123", "ops-key-456"
    return settings


def make_day(client, repo, settings, build=True):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
        assert book(client, "B", "0101").status_code == 201
    if build:
        run_nightly(repo, settings, TOMORROW)


def test_off_until_keys_are_set_and_bad_keys_are_refused(client, settings):
    assert client.get("/api/agent/health", headers=READ).status_code == 503
    settings.agent_key_read = "read-key-123"
    assert client.get("/api/agent/health").status_code == 401
    assert client.get("/api/agent/health", headers={"X-Agent-Key": "nope"}).status_code == 401
    assert client.get("/api/agent/health", headers=CREW).status_code == 401      # the owner code is not an agent key
    assert client.get("/api/agent/health", headers=READ).json()["your_access"] == "read"
    assert client.get("/api/agent/health", headers=OPS).status_code == 401       # ops key not configured yet


def test_health_reports_features_not_secrets(client, settings, on):
    out = client.get("/api/agent/health", headers=READ).json()
    assert out["business"] == "Post One Lawn Co." and set(out["features"]) == {
        "card_payments", "texting", "visit_notifications", "notification_keys", "dispatch_assistant"}
    text = str(out)
    for secret in ("read-key-123", "ops-key-456", settings.vapid_private_key, settings.crew_access_token):
        assert not secret or secret not in text


def test_day_summary_has_no_personal_details_and_addresses_only_for_ops(client, repo, settings, on):
    make_day(client, repo, settings)
    out = client.get(f"/api/agent/day/{TOMORROW}", headers=READ).json()
    assert out["totals"]["bookings"] == 2 and out["route"]["built"] is True and out["route"]["stops"] == 2
    assert [b["route_stop"] for b in out["bookings"]] == [1, 2]
    text = str(out)
    for private in ("Customer A", "Customer B", "281", "555", "access_code", "phone", "100 A Example", "pay_token"):
        assert private not in text, private
    assert "address" not in out["bookings"][0]
    asked = client.get(f"/api/agent/day/{TOMORROW}?include_addresses=true", headers=READ).json()
    assert "address" not in asked["bookings"][0]                                  # the read key never gets addresses
    ops = client.get(f"/api/agent/day/{TOMORROW}?include_addresses=true", headers=OPS).json()
    assert {b["address"] for b in ops["bookings"]} == {"100 A Example Rd", "100 B Example Rd"}
    assert "Customer" not in str(ops)


def test_outlook(client, repo, settings, on):
    make_day(client, repo, settings, build=False)
    days = client.get("/api/agent/outlook?days=3", headers=READ).json()["days"]
    assert len(days) == 3 and all({"date", "bookings", "quota", "expected"} <= set(d) for d in days)


def test_only_the_ops_key_can_build_a_route_and_the_same_guards_apply(client, repo, settings, on):
    make_day(client, repo, settings, build=False)
    url = f"/api/agent/routes/{TOMORROW}/build"
    assert client.post(url, headers=READ).status_code == 403
    assert client.post(url).status_code == 401
    with patch("app.agent_api.local_now", return_value=NOW):
        r = client.post(url, headers=OPS)
        assert r.status_code == 200 and r.json() == {"built": True, "date": TOMORROW.isoformat(), "stops": 2}
        stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
        client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW)
        assert client.post(url, headers=OPS).status_code == 409                   # can't rebuild once work has started
        assert client.post("/api/agent/routes/2020-01-01/build", headers=OPS).status_code == 409


def test_every_call_is_audited_without_secrets(client, repo, settings, on):
    make_day(client, repo, settings, build=False)
    client.get("/api/agent/health", headers=READ)
    client.get("/api/agent/health", headers={"X-Agent-Key": "wrong-guess"})
    client.post(f"/api/agent/routes/{TOMORROW}/build", headers=READ)
    entries = client.get("/api/agent/audit", headers=READ).json()["entries"]
    calls = [(e["role"], e["call"], e["outcome"]) for e in entries]
    assert ("read", "GET /api/agent/health", "ok") in calls
    assert ("unknown", "GET /api/agent/health", "denied") in calls
    assert any(c[2].startswith("denied: needs the ops key") for c in calls)
    assert "wrong-guess" not in str(entries) and "read-key-123" not in str(entries)


def test_rate_limit(client, on, monkeypatch):
    monkeypatch.setattr(agent_api, "RATE_LIMIT", 3)
    codes = [client.get("/api/agent/health", headers=READ).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]


# ---------- the guarded "on the way" action ----------

from datetime import date, datetime  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

MORNING = datetime(2026, 10, 15, 6, 45, tzinfo=ZoneInfo("America/Chicago"))      # the route day itself, near the first ETA


def build_the_route(client, repo, settings):
    make_day(client, repo, settings, build=True)
    return client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"]


NO_KEY = {"X-Other-Header": "1"}


def notify(client, sequence=1, day=TOMORROW, headers=OPS, at=MORNING):
    with patch("app.agent_api.local_now", return_value=at):
        return client.post(f"/api/agent/routes/{day}/stops/{sequence}/on-the-way", headers=headers)


def test_the_ops_key_can_tell_the_next_customer_the_crew_is_on_the_way(client, repo, settings, sms, on):
    stops = build_the_route(client, repo, settings)
    before = len(sms.sent)
    assert notify(client, headers=READ).status_code == 403                    # the read key can't
    assert notify(client, headers=NO_KEY).status_code == 401
    r = notify(client)
    assert r.status_code == 200 and r.json() == {"notified": True, "texted": True, "pushed": 0, "reason": None}
    assert len(sms.sent) == before + 1 and sms.sent[-1][0] == stops[0]["phone"]
    text = str(r.json())
    for private in (stops[0]["phone"], "Customer", "heading your way", "Reply STOP"):
        assert private not in text                                            # the agent never sees the message or the phone
    again = notify(client).json()
    assert again["notified"] is False and again["reason"] == "already_notified" and len(sms.sent) == before + 1
    assert client.get(f"/api/visit/{repo.jobs[stops[0]['job_id']]['access_code']}").json()["on_the_way_at"]


def test_the_site_refuses_an_on_the_way_that_would_not_be_true(client, repo, settings, sms, on):
    build_the_route(client, repo, settings)
    before = len(sms.sent)
    assert notify(client, day=date(2026, 10, 16)).status_code == 409                       # not today's visit
    early = notify(client, at=MORNING.replace(hour=6, minute=15))                          # too far before the arrival time
    assert early.status_code == 409 and "Too early" in early.json()["detail"]
    for hour in (5, 20, 23):
        quiet = notify(client, at=MORNING.replace(hour=hour, minute=30))
        assert quiet.status_code == 409 and "Quiet hours" in quiet.json()["detail"]
    skip = notify(client, sequence=2)
    assert skip.status_code == 409 and "next stop" in skip.json()["detail"]                # only the next unfinished stop
    assert notify(client, sequence=9).status_code == 404
    assert len(sms.sent) == before                                                         # none of those sent anything


def test_a_finished_stop_cannot_be_notified_and_the_site_already_handles_the_next_one(client, repo, settings, sms, on):
    stops = build_the_route(client, repo, settings)
    before = len(sms.sent)
    client.post(f"/api/stops/{stops[0]['stop_id']}/complete", headers=CREW)               # the site texts stop 2 by itself here
    assert len(sms.sent) == before + 1 and sms.sent[-1][0] == stops[1]["phone"]
    assert notify(client, sequence=1).status_code == 409                                   # stop 1 is done
    again = notify(client, sequence=2, at=MORNING.replace(hour=12))                        # stop 2 was already told
    assert again.json()["reason"] == "already_notified" and len(sms.sent) == before + 1   # so the agent adds nothing twice


def test_the_owner_can_pause_everything_agents_do(client, repo, settings, on):
    build_the_route(client, repo, settings)
    settings.agent_actions_paused = True
    paused = notify(client)
    assert paused.status_code == 403 and "paused by the owner" in paused.json()["detail"]
    assert client.post(f"/api/agent/routes/{TOMORROW}/build", headers=OPS).status_code == 403
    assert client.get("/api/agent/health", headers=READ).status_code == 200              # looking still works
    assert client.get("/api/agent/manifest", headers=READ).json()["features"]["agent_actions_paused"] is True
    settings.agent_actions_paused = False
    assert notify(client).status_code == 200


def test_the_notify_action_is_in_the_audit_log(client, repo, settings, on):
    build_the_route(client, repo, settings)
    notify(client)
    entries = client.get("/api/agent/audit", headers=READ).json()["entries"]
    assert any(e["role"] == "ops" and e["call"].endswith("/stops/1/on-the-way") and e["outcome"] == "ok" for e in entries)
