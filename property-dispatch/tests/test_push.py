"""Visit-page notifications: opt in with the access code, then get "on the way" and "done" pushes."""

import base64
import json
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException

from app import push
from app.nightly import run_nightly

from .test_api_flow import CREW, NOW, TOMORROW, book

ENDPOINT = "https://push.example.com/send/abc123abc123abc123"
SUB = {"endpoint": ENDPOINT, "keys": {"p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM",
                                       "auth": "tBHItJI5svbpez7KI4CCXg"}}


def make_pair() -> tuple[str, str]:
    """A real matching (public, private) key pair, like /push-setup makes."""
    from cryptography.hazmat.primitives import serialization
    key = ec.generate_private_key(ec.SECP256R1())
    d = key.private_numbers().private_value
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64 = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return b64(public), b64(d.to_bytes(32, "big"))


def make_key() -> str:
    return make_pair()[1]


@pytest.fixture
def on(settings):
    settings.vapid_public_key, settings.vapid_private_key = make_pair()
    settings.vapid_subject = "mailto:owner@example.com"
    return settings


def make_job(client, letter="A", phone="0100"):
    with patch("app.main.local_now", return_value=NOW):
        r = book(client, letter, phone)
    assert r.status_code == 201, r.text
    return r.json()


def subscribe(client, job, **extra):
    return client.post(f"/api/visit/{job['access_code'].replace('-', '')}/push", json={**SUB, **extra})


def test_push_is_off_until_keys_are_set(client, settings):
    assert client.get("/api/push-config").json() == {"public_key": None, "status": "off"}
    job = make_job(client)
    assert subscribe(client, job).status_code == 503
    settings.vapid_public_key, settings.vapid_private_key = make_pair()
    settings.public_base_url = "https://example.com"
    assert client.get("/api/push-config").json()["public_key"] == settings.vapid_public_key


def test_subscribing_needs_the_right_code_and_a_real_subscription(client, repo, on):
    job = make_job(client)
    assert subscribe(client, job).status_code == 204
    assert [s["visit_path"] for s in repo.list_push_subscriptions(job["id"])] == [f"/visit/{job['access_code'].replace('-', '')}"]
    assert client.post("/api/visit/ABCDEFGH/push", json=SUB).status_code == 404
    assert subscribe(client, job, endpoint="http://insecure.example.com/x" * 2).status_code == 422
    assert subscribe(client, job, keys={"p256dh": "x", "auth": "y"}).status_code == 422
    assert subscribe(client, job, lang="fr").status_code == 422
    subscribe(client, job)        # the same phone again doesn't add a second row
    assert len(repo.list_push_subscriptions(job["id"])) == 1


def test_on_the_way_and_done_pushes_go_to_the_right_phone_in_their_language(client, repo, settings, on, sms):
    a, b = make_job(client, "A", "0100"), make_job(client, "B", "0101")
    subscribe(client, b, lang="es")
    run_nightly(repo, settings, TOMORROW)
    stops = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"]
    first, second = (s for s in stops)       # stop order is decided by the router
    sent = []
    with patch("app.push.webpush", side_effect=lambda **kw: sent.append(kw)):
        client.post(f"/api/stops/{first['stop_id']}/complete", headers=CREW)
        client.post(f"/api/stops/{second['stop_id']}/complete", headers=CREW)
    bodies = [json.loads(kw["data"]) for kw in sent]
    # Only customer B subscribed, so exactly one push per event that touched B's booking.
    assert {x["body"] for x in bodies} <= {push.MESSAGES["on_the_way"]["es"], push.MESSAGES["done"]["es"]}
    assert bodies and all(x["title"] == settings.business_name and x["url"].startswith("/visit/") for x in bodies)
    assert all(kw["subscription_info"]["endpoint"] == ENDPOINT for kw in sent)
    assert any(x["body"] == push.MESSAGES["done"]["es"] for x in bodies)


def test_a_gone_phone_is_forgotten_and_a_failure_never_breaks_completion(client, repo, settings, on):
    job = make_job(client)
    subscribe(client, job)
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]

    class Gone:
        status_code = 410

    with patch("app.push.webpush", side_effect=WebPushException("gone", response=Gone())):
        r = client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW)
    assert r.status_code == 200 and repo.list_push_subscriptions(job["id"]) == []

    subscribe(client, job)
    with patch("app.push.webpush", side_effect=RuntimeError("network down")):
        assert push.notify_job(repo, settings, job["id"], "done") == 0
    assert len(repo.list_push_subscriptions(job["id"])) == 1       # a hiccup keeps the subscription


def test_nothing_is_sent_without_keys(client, repo, settings):
    job = make_job(client)
    repo.save_push_subscription(job["id"], ENDPOINT, SUB["keys"]["p256dh"], SUB["keys"]["auth"], "en", "/visit/X")
    with patch("app.push.webpush") as wp:
        assert push.notify_job(repo, settings, job["id"], "done") == 0
    wp.assert_not_called()


def test_the_private_key_from_the_setup_page_works(on):
    assert push._vapid(on.vapid_private_key) is not None


def test_setup_page_and_visit_page_have_the_pieces(client):
    page = client.get("/push-setup")
    assert page.status_code == 200 and "VAPID_PRIVATE_KEY" in page.text and "noindex" in page.headers["x-robots-tag"]
    assert "push-btn" in client.get("/visit").text


def test_on_my_way_button_sends_a_notification_not_a_text(client, repo, settings, on, sms):
    job = make_job(client)
    subscribe(client, job, lang="es")
    texts_before = len(sms.sent)
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    assert stop["notified_at"] is None
    url = f"/api/stops/{stop['stop_id']}/on-the-way"
    assert client.post(url).status_code == 401                      # crew only

    sent = []
    with patch("app.push.webpush", side_effect=lambda **kw: sent.append(kw)):
        r = client.post(url, headers=CREW).json()
        again = client.post(url, headers=CREW).json()
    assert r["notified"] is True and r["pushed"] == 1 and len(sent) == 1
    payload = json.loads(sent[0]["data"])
    assert payload["body"] == push.MESSAGES["on_the_way"]["es"] and payload["action"] == "Ver mi visita"
    assert len(sms.sent) == texts_before                            # the button never sends a text message
    assert again["reason"] == "already_notified" and len(sent) == 1   # never twice
    assert client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]["notified_at"]
    assert client.get(f"/api/visit/{job['access_code']}").json()["on_the_way_at"]

    client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW)
    assert client.post(url, headers=CREW).status_code == 409        # already done
    assert client.post("/api/stops/nope/on-the-way", headers=CREW).status_code == 404


def test_on_my_way_still_updates_the_visit_page_for_customers_without_notifications(client, repo, settings, sms):
    job = make_job(client)                                          # never opted in, push keys not even set
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    r = client.post(f"/api/stops/{stop['stop_id']}/on-the-way", headers=CREW).json()
    assert r["notified"] is False and r["pushed"] == 0 and r["reason"] == "no_subscribers"
    assert client.get(f"/api/visit/{job['access_code']}").json()["on_the_way_at"]   # the page shows it live


def test_booking_and_visit_pages_load_the_shared_opt_in_script(client):
    for path in ("/book", "/visit"):
        assert "/static/push.js" in client.get(path).text
    assert "SGPush" in client.get("/static/push.js").text
    book_page = client.get("/book").text
    assert "Want a heads-up when we're on the way?" in book_page and "SGPush?.setup" in book_page


def _fail_with(status):
    class Resp:
        status_code = status
    return WebPushException("nope", response=Resp() if status else None)


@pytest.mark.parametrize("status, problem", [(403, "key_mismatch"), (401, "key_mismatch"), (500, "service_busy"),
                                             (None, "service_busy"), (400, "rejected")])
def test_a_failed_push_says_why_and_can_be_retried(client, repo, settings, on, status, problem):
    job = make_job(client)
    subscribe(client, job)
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    url = f"/api/stops/{stop['stop_id']}/on-the-way"
    with patch("app.push.webpush", side_effect=_fail_with(status)):
        r = client.post(url, headers=CREW).json()
    assert r["reason"] == "push_failed" and r["problem"] == problem and r["detail"] == push.PROBLEMS[problem]
    assert r["pushed"] == 0 and r["notified"] is False
    assert len(repo.list_push_subscriptions(job["id"])) == 1                      # a hiccup keeps the sign-up
    with patch("app.push.webpush", side_effect=lambda **kw: None):                # after fixing the cause, tap again
        again = client.post(url, headers=CREW).json()
    assert again["pushed"] == 1 and again["reason"] is None


def test_an_expired_phone_is_forgotten_and_explained(client, repo, settings, on):
    job = make_job(client)
    subscribe(client, job)
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    with patch("app.push.webpush", side_effect=_fail_with(410)):
        r = client.post(f"/api/stops/{stop['stop_id']}/on-the-way", headers=CREW).json()
    assert r["problem"] == "phone_gone" and repo.list_push_subscriptions(job["id"]) == []


def test_a_broken_private_key_is_reported_not_hidden(client, repo, settings, on):
    settings.vapid_private_key = "this-is-not-a-key"
    job = make_job(client)
    subscribe(client, job)
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    r = client.post(f"/api/stops/{stop['stop_id']}/on-the-way", headers=CREW).json()
    assert r["reason"] == "push_failed" and r["problem"] == "key_invalid"


def test_finishing_a_job_reports_a_failed_done_alert_to_the_crew(client, repo, settings, on):
    job = make_job(client)
    subscribe(client, job)
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    with patch("app.push.webpush", side_effect=_fail_with(403)):
        done = client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW)
    assert done.status_code == 200 and done.json()["done_notification_problem"] == push.PROBLEMS["key_mismatch"]


def test_mismatched_keys_are_caught_before_anyone_signs_up(client, repo, settings, on):
    good = client.get("/api/push-config").json()
    assert good["status"] == "ok" and good["public_key"] == settings.vapid_public_key
    settings.vapid_private_key = make_key()                       # a private key from a different pair
    bad = client.get("/api/push-config").json()
    assert bad == {"public_key": None, "status": "key_mismatch"}  # the button stays hidden: it couldn't work
    settings.vapid_private_key = "not-a-key"
    assert client.get("/api/push-config").json()["status"] == "key_invalid"
    settings.vapid_private_key = ""
    assert client.get("/api/push-config").json() == {"public_key": None, "status": "off"}


def test_the_crew_sees_a_key_mismatch_instead_of_silence(client, repo, settings, on):
    job = make_day = make_job(client)
    subscribe(client, job)                                        # signed up while the keys still matched
    settings.vapid_private_key = make_key()                       # ...then the pair got mixed up in Render
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    with patch("app.push.webpush") as wp:
        r = client.post(f"/api/stops/{stop['stop_id']}/on-the-way", headers=CREW).json()
    wp.assert_not_called()
    assert r["reason"] == "push_failed" and r["problem"] == "key_mismatch"


def test_the_agent_health_report_includes_the_key_status(client, settings, on):
    settings.agent_key_read = "read-key-123"
    out = client.get("/api/agent/health", headers={"X-Agent-Key": "read-key-123"}).json()
    assert out["features"]["notification_keys"] == "ok" and out["features"]["visit_notifications"] is True
