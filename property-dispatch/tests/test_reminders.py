"""Day-before reminder texts and the customer's "Something not right?" button."""
from datetime import datetime
from unittest.mock import patch

import httpx

from app.nightly import run_nightly
from app.reminders import arrival_window, reminder_message

from .conftest import FakeSMS
from .test_api_flow import CREW, NOW, TOMORROW, book
from .test_visit_owner import booked

EVENING = NOW.replace(hour=17, minute=30)          # the route builds at 5 PM the day before


def reminders(sms):
    return [m for m in sms.sent if "a reminder from" in m[1] or "te recuerda" in m[1]]


def book_two(client):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
        es = client.post("/api/jobs", json={"name": "Cliente B", "phone": "(281) 555-0101", "address": "100 B Example Rd",
                                            "service": "mowing", "lawn_sqft": 5000, "package": "standard",
                                            "scheduled_date": TOMORROW.isoformat(), "lang": "es"})
        assert es.status_code == 201, es.text


# ---------- Day-before reminder ----------

def test_route_build_texts_each_customer_once_in_their_language(client, repo, settings):
    settings.public_base_url = "https://postone.example"
    book_two(client)
    sms = FakeSMS()
    summary = run_nightly(repo, settings, TOMORROW, sms=sms, now=EVENING)
    assert summary["stops"] == 2 and summary["reminders"]["reminded"] == 2 and summary["reminders"]["texted"] == 2
    en = next(body for to, body in reminders(sms) if to.endswith("0100"))
    es = next(body for to, body in reminders(sms) if to.endswith("0101"))
    assert "We're coming tomorrow for your mowing, likely between" in en
    assert "unlock the gate, bring pets inside" in en and "free until our on-the-way text" in en
    assert "https://postone.example/visit/" in en and en.endswith("Reply STOP to opt out.")
    assert "Vamos mañana (corte de césped)" in es and "abre el portón" in es and es.endswith("Responde STOP para no recibir más mensajes.")
    # A booking update, never a pitch: SMS consent covers booking updates only.
    for body in (en, es):
        assert not any(w in body.lower() for w in ("discount", "book again", "review", "descuento", "reseña"))
    # The owner rebuilds the route: nobody gets a second text.
    again = run_nightly(repo, settings, TOMORROW, sms=sms, now=EVENING.replace(hour=18))
    assert again["reminders"]["reminded"] == 0 and len(reminders(sms)) == 2


def test_no_texts_in_quiet_hours_or_for_a_same_day_rebuild(client, repo, settings):
    book_two(client)
    sms = FakeSMS()
    late = run_nightly(repo, settings, TOMORROW, sms=sms, now=EVENING.replace(hour=21, minute=5))
    assert late["reminders"]["skipped"] == "quiet_hours" and reminders(sms) == []
    same_day = run_nightly(repo, settings, TOMORROW, sms=sms, now=datetime.combine(TOMORROW, EVENING.time(), EVENING.tzinfo))
    assert same_day["reminders"]["skipped"] == "not_upcoming" and reminders(sms) == []


def test_without_the_database_update_the_route_still_builds_and_nobody_is_texted(client, repo, settings):
    book_two(client)
    sms = FakeSMS()
    with patch.object(repo, "mark_reminded", side_effect=RuntimeError("column reminded_at does not exist")):
        summary = run_nightly(repo, settings, TOMORROW, sms=sms, now=EVENING)
    assert summary["stops"] == 2 and summary["reminders"]["skipped"] == "needs_migration" and reminders(sms) == []


def test_arrival_window_is_two_hours_and_never_before_the_first_mow():
    tz = NOW.tzinfo
    at = lambda h, m: datetime(2026, 10, 15, h, m, tzinfo=tz)          # noqa: E731
    assert arrival_window(at(8, 0), 8) == "between 8 and 10 AM"         # first stop: not "7 AM"
    assert arrival_window(at(9, 50), 8) == "between 9 and 11 AM"
    assert arrival_window(at(11, 10), 8) == "between 10 AM and 12 PM"
    assert arrival_window(at(13, 45), 8) == "between 1 and 3 PM"
    assert arrival_window(at(9, 50), 8, "es") == "entre las 9:00 y las 11:00"
    assert arrival_window(None, 8) == ""
    assert "likely" not in reminder_message("Ana", "Post One Lawn Co.", "mowing", "tomorrow", "", "")


# ---------- "Something not right?" ----------

def test_a_customer_reports_a_problem_privately_and_it_reaches_the_owner(client, repo, settings):
    code = booked(client)["access_code"]
    r = client.post(f"/api/visit/{code}/report", json={"note": "  The back corner by the fence wasn't mowed.  "})
    assert r.status_code == 201 and r.json() == {"received": True, "emailed": False}
    issues = client.get("/api/owner/issues", headers=CREW).json()
    assert issues["kinds"]["customer"] == "A customer says something's not right"
    mine = issues["issues"][0]
    assert mine["kind"] == "customer" and mine["note"] == "The back corner by the fence wasn't mowed." and mine["address"]
    assert "customer_name" not in mine and "phone" not in mine


def test_customer_reports_are_code_gated_need_words_and_are_rate_limited(client, repo):
    code = booked(client)["access_code"]
    assert client.post("/api/visit/ZZZZZZZZ/report", json={"note": "Nobody came"}).status_code == 404
    assert client.post(f"/api/visit/{code}/report", json={"note": "  "}).status_code == 422
    assert client.post(f"/api/visit/{code}/report", json={"note": "x" * 1001}).status_code == 422
    codes = [client.post(f"/api/visit/{code}/report", json={"note": f"Report number {i}"}).status_code for i in range(6)]
    assert codes[:5] == [201] * 5 and codes[5] == 429          # five an hour per visitor: no flooding the inbox


def test_before_the_database_update_the_customer_gets_a_way_to_reach_us(client, repo):
    code = booked(client)["access_code"]
    with patch.object(repo, "add_issue", side_effect=RuntimeError("violates check constraint job_issues_kind_check")):
        r = client.post(f"/api/visit/{code}/report", json={"note": "Gate was left open"})
    assert r.status_code == 503 and "reply to any of our text messages" in r.json()["detail"]


def test_the_owner_email_says_it_came_from_a_customer(settings):
    from app.issues import alert_owner
    sent = []
    settings.resend_api_key, settings.operational_alert_email = "re_test", "owner@example.com"
    mock = httpx.Client(transport=httpx.MockTransport(lambda req: sent.append(req) or httpx.Response(200, json={})))
    assert alert_owner(settings, {"kind": "customer", "note": "Clippings left on the driveway"}, "100 A Example Rd", mock)
    assert b"Customer reported" in sent[0].content and b"Clippings left on the driveway" in sent[0].content


def test_the_visit_page_shows_the_private_box_next_to_the_review_button_not_instead_of_it(client):
    page = client.get("/visit").text
    assert "Something not right?" in page and "Leave a Google review" in page
    # Shown to every finished visit; the review card depends only on the owner's review link (no "review gating").
    assert '$("v-report").hidden = v.status !== "completed";' in page
    assert "review.hidden = !v.review_url;" in page
    spanish = client.get("/static/i18n.js").text
    assert '"Something not right?": "¿Algo no salió bien?"' in spanish
