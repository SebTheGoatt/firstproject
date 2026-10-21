"""Crew problem reports: saved with a photo, private to the owner, handled from the owner screen."""
import base64
from unittest.mock import patch

from .test_api_flow import CREW, NOW, book
from .test_payments import route_stops

JPEG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x03" * 200).decode()


def first_stop(client, repo, settings):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
    return route_stops(client, repo, settings)[0]


def test_crew_reports_a_problem_with_a_photo_and_the_owner_handles_it(client, repo, settings):
    stop = first_stop(client, repo, settings)
    r = client.post(f"/api/stops/{stop['stop_id']}/issues", headers=CREW,
                    json={"kind": "damage", "note": "Mower hit a sprinkler head by the driveway", "photo": JPEG})
    assert r.status_code == 201 and r.json()["kind"] == "damage" and r.json()["emailed"] is False
    issues = client.get("/api/owner/issues", headers=CREW).json()["issues"]
    assert len(issues) == 1 and issues[0]["has_photo"] and issues[0]["address"]
    assert "customer_name" not in issues[0] and "phone" not in issues[0]          # no customer details in reports
    photo = client.get(f"/api/owner/issues/{issues[0]['id']}/photo", headers=CREW)
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg"
    with patch("app.command.local_now", return_value=NOW):
        assert len(client.get("/api/owner/command", headers=CREW).json()["issues"]) == 1
    assert client.post(f"/api/owner/issues/{issues[0]['id']}/resolve", headers=CREW).json() == {"resolved": True}
    assert client.get("/api/owner/issues", headers=CREW).json()["issues"] == []
    assert client.post(f"/api/owner/issues/{issues[0]['id']}/resolve", headers=CREW).status_code == 404


def test_reports_need_a_note_or_photo_and_stay_private(client, repo, settings):
    stop = first_stop(client, repo, settings)
    assert client.post(f"/api/stops/{stop['stop_id']}/issues", headers=CREW, json={"kind": "damage"}).status_code == 422
    assert client.post(f"/api/stops/{stop['stop_id']}/issues", headers=CREW, json={"kind": "delay"}).status_code == 201
    assert client.post(f"/api/stops/{stop['stop_id']}/issues", json={"kind": "delay"}).status_code in (401, 403)
    assert client.get("/api/owner/issues").status_code in (401, 403)
    assert client.post("/api/stops/nope/issues", headers=CREW, json={"kind": "delay"}).status_code == 404


def test_a_missing_database_update_answers_with_the_fix(client, repo, settings):
    stop = first_stop(client, repo, settings)
    with patch.object(repo, "add_issue", side_effect=RuntimeError("relation job_issues does not exist")):
        r = client.post(f"/api/stops/{stop['stop_id']}/issues", headers=CREW, json={"kind": "delay"})
    assert r.status_code == 503 and "20261028000000_issues_and_sources.sql" in r.json()["detail"]
    with patch.object(repo, "list_issues", side_effect=RuntimeError("missing")), patch("app.command.local_now", return_value=NOW):
        assert client.get("/api/owner/command", headers=CREW).json()["issues"] is None   # the screen still loads


def test_the_owner_gets_an_email_when_resend_is_set_up(settings):
    import httpx
    from app.issues import alert_owner
    sent = []
    settings.resend_api_key, settings.operational_alert_email = "re_test", "owner@example.com"
    client = httpx.Client(transport=httpx.MockTransport(lambda req: sent.append(req) or httpx.Response(200, json={})))
    assert alert_owner(settings, {"kind": "equipment", "note": "Belt snapped"}, "100 A Example Rd", client) is True
    assert b"Equipment broke down" in sent[0].content and b"Belt snapped" in sent[0].content
