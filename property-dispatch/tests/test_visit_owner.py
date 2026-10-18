"""Customer access codes, private before/after photos, and the owner dashboard."""

import base64
import re
from datetime import timedelta
from unittest.mock import patch

from app.nightly import run_nightly
from app.visit_routes import normalize_code

from .test_api_flow import CREW, NOW, TOMORROW, book
from .conftest import legacy_quoted_job

JPEG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x02" * 200).decode()


def booked(client, letter="A", phone="0100", **kw):
    with patch("app.main.local_now", return_value=NOW), patch("app.visit_routes.local_now", return_value=NOW):
        r = book(client, letter, phone, **kw)
    assert r.status_code == 201, r.text
    return r.json()


def owner_get(client, path):
    with patch("app.visit_routes.local_now", return_value=NOW):
        return client.get(path, headers=CREW)


# ---------- Access codes ----------
def test_booking_gets_an_access_code_and_confirmation_text(client, sms):
    r = booked(client)
    assert re.fullmatch(r"[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}", r["access_code"])
    assert r["visit_url"] == "/visit/" + r["access_code"].replace("-", "")
    to, text = sms.sent[-1]
    assert r["access_code"] in text and "/visit/" in text and "before & after photos" in text


def test_code_input_is_forgiving_but_strict():
    assert normalize_code(" k7mx-3qpa ") == "K7MX3QPA"
    for bad in ("K7MX3QP", "K7MX3QPA9", "O0I1L-ABCD", ""):
        assert normalize_code(bad) is None


def test_visit_page_follows_the_job_from_booking_to_photos(client, repo, settings):
    sam = client.post("/api/crew/members", headers=CREW, json={"display_name": "Sam Rivera", "code": "4321"}).json()
    h = {"X-Crew-Token": client.post("/api/crew/login", json={"member_id": sam["id"], "code": "4321"}).json()["token"]}
    r = booked(client)
    code = r["access_code"]

    v = client.get(f"/api/visit/{code.lower()}").json()
    assert (v["status"], v["eta"], v["first_name"], v["photos"]) == ("pending", None, "Customer", [])
    assert v["payment"]["amount_due"] == 113.66 and v["payment"]["tax"] == 8.66

    run_nightly(repo, settings, TOMORROW)
    v = client.get(f"/api/visit/{code}").json()
    assert v["status"] == "scheduled" and v["eta"]

    stop = client.get(f"/api/routes/{TOMORROW}", headers=h).json()["stops"][0]
    assert client.post(f"/api/stops/{stop['stop_id']}/photos", headers=h, json={"kind": "before", "photo": JPEG}).status_code == 201
    client.post(f"/api/stops/{stop['stop_id']}/complete", headers=h, json={"cash_collected": 113.66})
    client.post(f"/api/stops/{stop['stop_id']}/photos", headers=h, json={"kind": "after", "photo": JPEG})

    v = client.get(f"/api/visit/{code}").json()
    assert v["status"] == "completed" and v["completed_at"]
    assert v["crew_member"]["display_name"] == "Sam Rivera"
    assert [p["kind"] for p in v["photos"]] == ["before", "after"]
    assert v["payment"]["status"] == "paid" and v["payment"]["pay_url"] is None
    img = client.get(v["photos"][0]["url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"


def test_photos_are_private_to_their_visit(client, repo, settings):
    a, b = booked(client, "A", "0100"), booked(client, "B", "0101")
    run_nightly(repo, settings, TOMORROW)
    stops = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"]
    stop_a = next(s for s in stops if s["job_id"] == a["id"])
    pid = client.post(f"/api/stops/{stop_a['stop_id']}/photos", headers=CREW, json={"kind": "before", "photo": JPEG}).json()["id"]
    code_a, code_b = a["access_code"].replace("-", ""), b["access_code"].replace("-", "")
    assert client.get(f"/media/visit/{pid}?code={code_a}").status_code == 200
    assert client.get(f"/media/visit/{pid}?code={code_b}").status_code == 404   # someone else's code
    assert client.get(f"/media/visit/{pid}").status_code == 404
    assert client.post(f"/api/stops/{stop_a['stop_id']}/photos", json={"kind": "before", "photo": JPEG}).status_code == 401
    assert client.post(f"/api/stops/{stop_a['stop_id']}/photos", headers=CREW, json={"kind": "during", "photo": JPEG}).status_code == 422


def test_unknown_codes_and_guessing(client):
    assert client.get("/api/visit/ABCD-EFGH").status_code == 404
    assert client.get("/api/visit/not-a-code").status_code == 404
    codes = [client.get("/api/visit/ABCD-EFGH").status_code for _ in range(30)]
    assert codes[-1] == 429


def test_visit_pages_are_private(client):
    for path in ("/visit", "/visit/K7MX3QPA"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["x-robots-tag"] == "noindex"


# ---------- Owner dashboard ----------
def test_bookings_show_on_the_dashboard_before_any_route_exists(client, repo):
    booked(client, "A", "0100")
    legacy_quoted_job(repo, "B")                     # gutter-only booking from before add-ons
    d = owner_get(client, f"/api/owner/day/{TOMORROW}").json()
    assert [j["customer_name"] for j in d["jobs"]] == ["Customer A", "Customer B"]
    assert all(j["status"] == "pending" and j["sequence"] is None for j in d["jobs"])
    assert d["route"]["built"] is False and d["route"]["missing"] == 2
    assert d["totals"] == {"jobs": 2, "done": 0, "expected": 113.66, "collected": 0, "donations": 0,
                           "unpaid": 113.66, "quoted_on_site": 1, "sales_tax": 0, "charity_giving": 0,
                           "donations_by_charity": [
                               {"key": "vfw", "name": "Veterans of Foreign Wars (VFW)", "percent": 33, "amount": 0},
                               {"key": "nicu", "name": "Neonatal intensive care (NICU) families", "percent": 33, "amount": 0},
                               {"key": "at_risk_youth", "name": "At-risk youth programs", "percent": 34, "amount": 0},
                               {"key": "toys_for_tots", "name": "Holiday toy drive for local kids", "percent": 0, "amount": 0}]}
    assert re.fullmatch(r"\w{4}-\w{4}", d["jobs"][0]["access_code"])
    assert d["auto_build"]["hour"] == 17


def test_owner_builds_route_now_and_sees_order(client):
    booked(client, "A", "0100"); booked(client, "B", "0101"); booked(client, "C", "0102")
    with patch("app.visit_routes.local_now", return_value=NOW):
        r = client.post(f"/api/owner/routes/{TOMORROW}/build", headers=CREW)
    assert r.status_code == 200 and r.json()["stops"] == 3
    d = owner_get(client, f"/api/owner/day/{TOMORROW}").json()
    assert sorted(j["sequence"] for j in d["jobs"]) == [1, 2, 3] and d["route"]["missing"] == 0
    assert [j["sequence"] for j in d["jobs"]] == [1, 2, 3]       # listed in driving order

    # Once work has started, the route can't be rebuilt underneath the crew.
    first = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    client.post(f"/api/stops/{first['stop_id']}/complete", headers=CREW, json={"cash_collected": 130})
    with patch("app.visit_routes.local_now", return_value=NOW):
        assert client.post(f"/api/owner/routes/{TOMORROW}/build", headers=CREW).status_code == 409
        assert client.post(f"/api/owner/routes/{NOW.date() - timedelta(days=1)}/build", headers=CREW).status_code == 409
        assert client.post(f"/api/owner/routes/{TOMORROW + timedelta(days=3)}/build", headers=CREW).status_code == 409
    d = owner_get(client, f"/api/owner/day/{TOMORROW}").json()
    assert d["totals"]["collected"] == 130.0 and d["totals"]["donations"] == 16.34 and d["totals"]["done"] == 1
    assert d["totals"]["sales_tax"] == 8.66
    # To pass on: Block Lock's 2% ($2.10) + the $16.34 donation, each split 33% / 33% / 34%
    assert d["totals"]["charity_giving"] == 2.1
    assert [c["amount"] for c in d["totals"]["donations_by_charity"]] == [6.08, 6.08, 6.28, 0]   # tax on what's been paid, for the owner's sales-tax filing


def test_outlook_and_owner_only(client):
    booked(client, "A", "0100"); booked(client, "B", "0101")
    week = owner_get(client, "/api/owner/outlook?days=7").json()
    assert len(week) == 7 and week[0]["date"] == NOW.date().isoformat()
    tomorrow = next(d for d in week if d["date"] == TOMORROW.isoformat())
    assert tomorrow["jobs"] == 2 and tomorrow["expected"] == 227.32
    sam = client.post("/api/crew/members", headers=CREW, json={"display_name": "Sam", "code": "4321"}).json()
    h = {"X-Crew-Token": client.post("/api/crew/login", json={"member_id": sam["id"], "code": "4321"}).json()["token"]}
    assert client.get(f"/api/owner/day/{TOMORROW}", headers=h).status_code == 403
    assert client.get(f"/api/owner/day/{TOMORROW}").status_code == 401
