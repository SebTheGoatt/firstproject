"""Google review follow-up: one honest ask, about 20 minutes after the crew finishes."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import reviews
from app.main import create_app
from app.nightly import run_nightly

from .conftest import FakeGeocoder
from .test_api_flow import CREW, NOW, TOMORROW, book

REVIEW_URL = "https://g.page/r/semper-green-test/review"
BASE = "https://property-dispatch.onrender.com"


def finished_job(client, repo, settings, letter="A", phone="0100"):
    with patch("app.main.local_now", return_value=NOW):
        job = book(client, letter, phone).json()
    run_nightly(repo, settings, TOMORROW)
    stop = next(s for s in client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"] if s["job_id"] == job["id"])
    client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"cash_collected": 113.66})
    return job, datetime.fromisoformat(repo.jobs[job["id"]]["completed_at"])


def run(repo, settings, sms, at, asked=None):
    with patch("app.reviews.push.send_to_job", return_value={"sent": 1}) as pushed:
        report = reviews.send_due_review_requests(repo, settings, sms, at, BASE, asked)
    return report, pushed


def test_asks_once_about_20_minutes_after_the_crew_leaves(client, repo, settings, sms):
    settings.google_review_url = REVIEW_URL
    job, done = finished_job(client, repo, settings)
    texts = len(sms.sent)

    report, pushed = run(repo, settings, sms, done + timedelta(minutes=10))
    assert report["asked"] == 0 and len(sms.sent) == texts            # too soon: the crew may still be packing up

    report, pushed = run(repo, settings, sms, done + timedelta(minutes=21))
    assert report == {"asked": 1, "pushed": 1, "texted": 1, "mode": "saved"}
    pushed.assert_called_once_with(repo, settings, job["id"], "review", link_suffix="?review=1")
    to, text = sms.sent[-1]
    code = job["access_code"].replace("-", "")
    assert to.endswith("5550100") and text.startswith("Hi Customer, thanks for choosing")
    assert REVIEW_URL in text and f"{BASE}/visit/{code}" in text and "Reply STOP" in text

    report, _ = run(repo, settings, sms, done + timedelta(minutes=40))
    assert report["asked"] == 0 and len(sms.sent) == texts + 1          # never twice


def test_old_jobs_and_missing_link_are_left_alone(client, repo, settings, sms):
    job, done = finished_job(client, repo, settings)
    texts = len(sms.sent)
    assert run(repo, settings, sms, done + timedelta(minutes=21))[0] == {"asked": 0, "pushed": 0, "texted": 0, "mode": "off"}
    settings.google_review_url = "javascript:alert(1)"                  # only real https links
    assert run(repo, settings, sms, done + timedelta(minutes=21))[0]["mode"] == "off"
    settings.google_review_url = REVIEW_URL
    assert run(repo, settings, sms, done + timedelta(hours=25))[0]["asked"] == 0
    assert len(sms.sent) == texts


def test_spanish_customers_get_spanish(client, repo, settings, sms):
    settings.google_review_url = REVIEW_URL
    job, done = finished_job(client, repo, settings)
    repo.jobs[job["id"]]["lang"] = "es"
    run(repo, settings, sms, done + timedelta(minutes=21))
    assert sms.sent[-1][1].startswith("Hola Customer, gracias por elegir") and "reseña en Google" in sms.sent[-1][1]


def test_works_before_the_database_column_exists(client, repo, settings, sms):
    settings.google_review_url = REVIEW_URL
    job, done = finished_job(client, repo, settings)
    asked = set()
    with patch.object(repo, "jobs_due_review", side_effect=RuntimeError("column jobs.review_requested_at does not exist")):
        first, _ = run(repo, settings, sms, done + timedelta(minutes=21), asked)
        again, _ = run(repo, settings, sms, done + timedelta(minutes=26), asked)
    assert (first["asked"], first["mode"], again["asked"]) == (1, "memory", 0)


def test_a_failing_text_doesnt_stop_the_others(client, repo, settings, sms):
    settings.google_review_url = REVIEW_URL
    a, done = finished_job(client, repo, settings, "A", "0100")
    b, _ = finished_job(client, repo, settings, "B", "0101")
    with patch("app.reviews.send_text", side_effect=[RuntimeError("boom"), {"sent": True}]):
        report, _ = run(repo, settings, sms, done + timedelta(minutes=21))
    assert report["asked"] == 2 and report["texted"] == 1


def test_wording_follows_googles_review_rules():
    for lang in ("en", "es"):
        text = reviews.review_message("Sam", "Semper Green Lawn Care", "https://x/visit/AB", REVIEW_URL, lang).lower()
        assert REVIEW_URL.lower() in text
        for banned in ("5-star", "5 star", "five star", "5 estrellas", "toys for tots", "donat", "discount", "descuento"):
            assert banned not in text


def test_visit_page_shows_the_review_button_only_after_the_visit(client, repo, settings):
    settings.google_review_url = REVIEW_URL
    with patch("app.main.local_now", return_value=NOW):
        job = book(client, "A", "0100").json()
    code = job["access_code"]
    assert client.get(f"/api/visit/{code}").json()["review_url"] is None
    finished = finished_job(client, repo, settings, "B", "0101")[0]
    assert client.get(f"/api/visit/{finished['access_code']}").json()["review_url"] == REVIEW_URL
    settings.google_review_url = ""
    assert client.get(f"/api/visit/{finished['access_code']}").json()["review_url"] is None


def test_cron_endpoint_needs_the_secret(client, repo, settings, sms):
    assert client.post("/internal/review-requests").status_code == 401
    r = client.post("/internal/review-requests", headers={"X-Cron-Secret": "cron"})
    assert r.status_code == 200 and r.json()["mode"] == "off"


def test_background_loop_runs_beside_the_app_without_blocking_it(settings, repo, sms):
    settings.google_review_url, settings.review_requests_every_min = REVIEW_URL, 5
    app = create_app(settings, repo=repo, geocoder=FakeGeocoder(), sms=sms)
    with TestClient(app) as c:                     # starts the loop (it waits 5 minutes before its first run)
        assert c.get("/healthz").status_code == 200
        assert c.get("/api/booking-info").status_code == 200
    # Leaving the block stops the loop cleanly; nothing hangs.


def test_loop_runs_off_the_main_thread_and_survives_errors(settings, repo, sms):
    import asyncio
    import threading
    import pytest
    from app.main import review_loop
    settings.review_requests_every_min = 5
    app = create_app(settings, repo=repo, geocoder=FakeGeocoder(), sms=sms)
    threads, naps = [], []

    async def nap(seconds):
        naps.append(seconds)
        if len(naps) > 2:
            raise asyncio.CancelledError      # stop after two runs

    def send(app, base_url):
        threads.append(threading.current_thread() is threading.main_thread())
        if len(threads) == 1:
            raise RuntimeError("database hiccup")   # logged; the loop keeps going

    with patch("app.main.asyncio.sleep", nap), patch("app.main.send_review_requests", side_effect=send):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(review_loop(app))
    assert naps == [300, 300, 300] and threads == [False, False]
