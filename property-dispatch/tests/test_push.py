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


def make_key() -> str:
    d = ec.generate_private_key(ec.SECP256R1()).private_numbers().private_value
    return base64.urlsafe_b64encode(d.to_bytes(32, "big")).decode().rstrip("=")


@pytest.fixture
def on(settings):
    settings.vapid_public_key = "BPublicKeyPlaceholderPublicKeyPlaceholderPublicKeyPlaceholderPublicKeyPlaceholder"
    settings.vapid_private_key = make_key()
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
    assert client.get("/api/push-config").json() == {"public_key": None}
    job = make_job(client)
    assert subscribe(client, job).status_code == 503
    settings.vapid_public_key, settings.vapid_private_key = "BKey" * 20, make_key()
    settings.public_base_url = "https://example.com"
    assert client.get("/api/push-config").json()["public_key"] == "BKey" * 20


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
