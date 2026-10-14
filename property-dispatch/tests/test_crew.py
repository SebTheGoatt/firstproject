"""Crew members: personal sign-in, profiles, portfolios, and public pages."""

import base64

import pytest

from app.nightly import run_nightly

from .test_api_flow import CREW, NOW, TOMORROW, book
from unittest.mock import patch

JPEG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 200).decode()
OWNER = CREW  # the master code


def owner_token(client):
    r = client.post("/api/crew/login/owner", json={"code": "crew"})
    assert r.status_code == 200 and r.json()["is_owner"] is True
    return {"X-Crew-Token": r.json()["token"]}


def add_member(client, name="Sam Rivera", code="4321", role="Lead Mower"):
    r = client.post("/api/crew/members", headers=OWNER, json={"display_name": name, "code": code, "role_title": role})
    assert r.status_code == 201, r.text
    return r.json()


def login(client, member_id, code="4321"):
    r = client.post("/api/crew/login", json={"member_id": member_id, "code": code})
    assert r.status_code == 200, r.text
    return {"X-Crew-Token": r.json()["token"]}


def test_owner_signs_in_and_adds_crew(client):
    assert client.post("/api/crew/login/owner", json={"code": "nope"}).status_code == 401
    h = owner_token(client)
    assert client.get("/api/crew/me", headers=h).json()["is_owner"] is True
    sam = add_member(client)
    assert sam["slug"] == "sam-rivera"
    again = add_member(client, code="9999")
    assert again["slug"] == "sam-rivera-2"  # unique public URL
    roster = client.get("/api/crew/roster").json()
    assert [m["display_name"] for m in roster] == ["Sam Rivera", "Sam Rivera"]
    assert all("passcode_hash" not in m for m in roster)


def test_member_profile_photo_and_portfolio(client):
    sam = add_member(client)
    assert client.post("/api/crew/login", json={"member_id": sam["id"], "code": "0000"}).status_code == 401
    h = login(client, sam["id"])

    me = client.get("/api/crew/me", headers=h).json()
    assert me["member"]["display_name"] == "Sam Rivera" and me["stats"] == {"jobs_total": 0, "jobs_week": 0, "photos": 0}

    r = client.put("/api/crew/me", headers=h, json={
        "bio": "Marine Corps vet. I treat every lawn like a parade ground.", "years_experience": 6,
        "specialties": ["Stripe patterns", "Edging", "Edging", " "], "service_branch": "U.S. Marine Corps veteran",
        "accent_color": "#1f4e8c"})
    assert r.status_code == 200
    assert r.json()["specialties"] == ["Stripe patterns", "Edging"]
    assert client.put("/api/crew/me", headers=h, json={"accent_color": "blue"}).status_code == 422

    assert client.put("/api/crew/me/photo", headers=h, json={"photo": "data:text/html;base64,PGI+"}).status_code == 422
    fake_png_as_jpeg = "data:image/jpeg;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
    assert client.put("/api/crew/me/photo", headers=h, json={"photo": fake_png_as_jpeg}).status_code == 422
    photo_url = client.put("/api/crew/me/photo", headers=h, json={"photo": JPEG}).json()["photo_url"]
    img = client.get(photo_url)
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"

    item = client.post("/api/crew/me/portfolio", headers=h,
                       json={"photo": JPEG, "caption": "Fresh stripes on Oak Forest", "service": "mowing"}).json()
    assert client.get(item["photo_url"]).status_code == 200
    assert [i["caption"] for i in client.get("/api/crew/me/portfolio", headers=h).json()] == ["Fresh stripes on Oak Forest"]

    # Someone else can't delete Sam's photo.
    jo = add_member(client, "Jo Park", "8765")
    assert client.delete(f"/api/crew/me/portfolio/{item['id']}", headers=login(client, jo["id"], "8765")).status_code == 404
    assert client.delete(f"/api/crew/me/portfolio/{item['id']}", headers=h).status_code == 204


def test_public_team_pages(client):
    sam = add_member(client)
    h = login(client, sam["id"])
    client.put("/api/crew/me", headers=h, json={"bio": "Hi!", "service_branch": "U.S. Army veteran"})
    client.post("/api/crew/me/portfolio", headers=h, json={"photo": JPEG, "caption": "Before/after"})

    team = client.get("/api/team").json()
    assert team[0]["display_name"] == "Sam Rivera" and team[0]["service_branch"] == "U.S. Army veteran"
    profile = client.get("/api/team/sam-rivera").json()
    assert profile["portfolio"][0]["caption"] == "Before/after" and profile["jobs_total"] == 0
    assert "passcode_hash" not in str(profile) and "passcode_hash" not in str(team)
    assert client.get("/api/team/nobody").status_code == 404
    for path in ("/team", "/team/sam-rivera"):
        assert client.get(path).status_code == 200


def test_member_completes_job_named_in_text_and_stats(client, repo, settings, sms):
    sam = add_member(client)
    h = login(client, sam["id"])
    with patch("app.main.local_now", return_value=NOW):
        book(client, "A", "0100")
        book(client, "B", "0101")
    run_nightly(repo, settings, TOMORROW)
    stops = client.get(f"/api/routes/{TOMORROW}", headers=h).json()["stops"]
    client.post(f"/api/stops/{stops[0]['stop_id']}/complete", headers=h)
    assert "this is Sam from" in sms.sent[-1][1]
    stop = client.get(f"/api/routes/{TOMORROW}", headers=h).json()["stops"][0]
    assert stop["completed_by_name"] == "Sam Rivera"
    assert client.get("/api/crew/me", headers=h).json()["stats"]["jobs_total"] == 1
    assert client.get("/api/team/sam-rivera").json()["jobs_total"] == 1


def test_permissions_and_deactivation(client):
    sam = add_member(client)
    h = login(client, sam["id"])
    assert client.get("/api/crew/members", headers=h).status_code == 403          # owner only
    assert client.put("/api/crew/me", headers=OWNER, json={"bio": "x"}).status_code == 403  # owner has no profile
    assert client.get("/api/crew/me", headers={"X-Crew-Token": "cs1.forged.sig"}).status_code == 401

    assert client.patch(f"/api/crew/members/{sam['id']}", headers=OWNER, json={"active": False}).json()["active"] is False
    assert client.get("/api/crew/me", headers=h).status_code == 401              # signed out everywhere
    assert client.get("/api/crew/roster").json() == []
    assert client.get("/api/team/sam-rivera").status_code == 404


def test_change_code_and_owner_reset(client):
    sam = add_member(client)
    h = login(client, sam["id"])
    assert client.put("/api/crew/me/code", headers=h, json={"current": "bad!", "new": "5555"}).status_code == 401
    assert client.put("/api/crew/me/code", headers=h, json={"current": "4321", "new": "12"}).status_code == 422
    assert client.put("/api/crew/me/code", headers=h, json={"current": "4321", "new": "5555"}).status_code == 200
    login(client, sam["id"], "5555")
    client.patch(f"/api/crew/members/{sam['id']}", headers=OWNER, json={"code": "7777"})
    login(client, sam["id"], "7777")


def test_guessing_is_throttled(client):
    sam = add_member(client)
    for _ in range(8):
        assert client.post("/api/crew/login", json={"member_id": sam["id"], "code": "0000"}).status_code == 401
    r = client.post("/api/crew/login", json={"member_id": sam["id"], "code": "4321"})
    assert r.status_code == 429
