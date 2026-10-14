"""Pay your way: cash to the crew, or card through Stripe, with optional donations."""

import hashlib
import hmac
import json
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.nightly import run_nightly
from app.payments import PaymentError, verify_webhook

from .conftest import FakeGeocoder
from .test_api_flow import CREW, NOW, TOMORROW, book

WHSEC = "whsec_test"


class FakeStripe:
    def __init__(self):
        self.sessions = []

    def create_checkout(self, **kw):
        self.sessions.append(kw)
        return {"id": f"cs_test_{len(self.sessions)}", "url": f"https://checkout.stripe.test/{len(self.sessions)}"}


@pytest.fixture
def stripe():
    return FakeStripe()


@pytest.fixture
def card_client(settings, repo, sms, stripe):
    settings.stripe_secret_key, settings.stripe_webhook_secret = "sk_test", WHSEC
    return TestClient(create_app(settings, repo=repo, geocoder=FakeGeocoder(), sms=sms, stripe=stripe))


def book_with(client, letter, phone, service="mowing", method="cash"):
    with patch("app.main.local_now", return_value=NOW):
        return client.post("/api/jobs", json={
            "name": f"Customer {letter}", "phone": f"(281) 555-{phone}", "address": f"100 {letter} Example Rd",
            "service": service, "scheduled_date": TOMORROW.isoformat(), "payment_method": method})


def signed(event: dict, secret=WHSEC, t=None):
    payload = json.dumps(event).encode()
    t = int(t or time.time())
    sig = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return payload, f"t={t},v1={sig}"


def paid_event(job_id, total_cents, donation_cents):
    return {"type": "checkout.session.completed", "data": {"object": {
        "payment_status": "paid", "amount_total": total_cents, "client_reference_id": job_id,
        "metadata": {"job_id": job_id, "donation_cents": str(donation_cents)}}}}


def route_stops(client, repo, settings):
    run_nightly(repo, settings, TOMORROW)
    return client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"]


def test_card_hidden_until_stripe_is_configured(client):
    assert client.get("/api/booking-info").json()["card_payments"] is False
    r = book_with(client, "A", "0100", method="card")
    assert r.status_code == 422 and "cash" in r.json()["detail"]


def test_cash_booking_and_crew_records_cash_with_donation(client, repo, settings):
    r = book_with(client, "A", "0100")
    assert r.status_code == 201 and r.json()["payment_method"] == "cash" and r.json()["pay_url"] is None
    stop = route_stops(client, repo, settings)[0]
    # Standard package, typical lot: $50 + 4,500 × 0.9¢ = $90.50 + 8.25% tax ($7.47) = $97.97
    assert (stop["payment_method"], stop["payment_status"], stop["amount_due"]) == ("cash", "unpaid", 97.97)
    assert (stop["subtotal"], stop["tax_amount"], stop["tax_rate"]) == (90.5, 7.47, 0.0825)

    short = client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"cash_collected": 97})
    assert short.status_code == 422  # less than the $97.97 total
    # ...and a rejected cash amount must not mark the job done.
    assert client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]["completed_at"] is None

    r = client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"cash_collected": 110}).json()
    assert r["payment"] == {"status": "paid", "method": "cash", "amount_paid": 110.0, "donation": 12.03, "total": 97.97,
                            "donation_split": {"vfw": 3.97, "nicu": 3.97, "at_risk_youth": 4.09}}
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    assert (stop["payment_status"], stop["amount_paid"], stop["donation"]) == ("paid", 110.0, 12.03)


def test_card_prepay_with_donation_through_stripe(card_client, repo, stripe):
    r = book_with(card_client, "A", "0100", method="card").json()
    token = r["pay_url"].rsplit("/", 1)[1]
    assert len(token) >= 20

    info = card_client.get(f"/api/pay/{token}").json()
    assert (info["first_name"], info["amount_due"], info["payment_status"], info["card_enabled"]) == \
        ("Customer", 97.97, "unpaid", True)

    assert card_client.post(f"/api/pay/{token}/checkout", json={"donation": 600}).status_code == 422
    assert card_client.post(f"/api/pay/{token}/checkout", json={"donation": -1}).status_code == 422
    out = card_client.post(f"/api/pay/{token}/checkout", json={"donation": 10}).json()
    assert out["url"].startswith("https://checkout.stripe.test/")
    s = stripe.sessions[-1]
    assert (s["amount_due"], s["subtotal"], s["tax"], s["tax_rate"], s["donation"]) == (97.97, 90.5, 7.47, 0.0825, 10.0)
    assert stripe.sessions[-1]["success_url"].endswith(f"/pay/{token}?done=1")

    job_id = r["id"]
    payload, sig = signed(paid_event(job_id, 10797, 1000))
    assert card_client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": sig}).status_code == 200
    info = card_client.get(f"/api/pay/{token}").json()
    assert (info["payment_status"], info["amount_paid"], info["donation"]) == ("paid", 107.97, 10.0)
    assert [(c["key"], c["percent"], c["amount"]) for c in info["donation_ledger"]] == \
        [("vfw", 33, 3.3), ("nicu", 33, 3.3), ("at_risk_youth", 34, 3.4)]
    assert card_client.post(f"/api/pay/{token}/checkout", json={}).status_code == 409  # can't pay twice

    # Stripe retries webhooks; a replay must not change anything.
    payload, sig = signed(paid_event(job_id, 9900, 0))
    card_client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": sig})
    assert card_client.get(f"/api/pay/{token}").json()["amount_paid"] == 107.97


def test_webhook_rejects_bad_or_stale_signatures(card_client):
    payload, sig = signed(paid_event("x", 100, 0), secret="wrong")
    assert card_client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": sig}).status_code == 400
    assert card_client.post("/webhooks/stripe", content=payload).status_code == 400
    with pytest.raises(PaymentError, match="stale"):
        p, s = signed({"type": "x"}, t=time.time() - 3600)
        verify_webhook(p, s, WHSEC)


def test_quoted_service_gets_price_on_site_then_pay_link(card_client, repo, settings, sms):
    r = book_with(card_client, "A", "0100", service="gutters", method="card").json()
    token = r["pay_url"].rsplit("/", 1)[1]
    assert r["quoted_price"] is None
    blocked = card_client.post(f"/api/pay/{token}/checkout", json={})
    assert blocked.status_code == 409 and "crew finishes" in blocked.json()["detail"]

    stop = route_stops(card_client, repo, settings)[0]
    res = card_client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"price": 120}).json()
    assert res["payment"]["pay_link"]["sent"] is True
    to, text = sms.sent[-1]
    assert to == stop["phone"] and f"/pay/{token}" in text and "VFW" in text and "No tip necessary" in text
    info = card_client.get(f"/api/pay/{token}").json()
    assert (info["subtotal"], info["tax"], info["amount_due"]) == (120.0, 9.9, 129.9)   # $120 + 8.25% tax
    assert card_client.post(f"/api/pay/{token}/checkout", json={}).status_code == 200


def test_unknown_or_short_pay_tokens_are_404(card_client):
    assert card_client.get("/api/pay/abc").status_code == 404
    assert card_client.get("/api/pay/" + "x" * 24).status_code == 404


def test_pay_page_is_private(card_client):
    r = card_client.get("/pay/whatever-token-value")
    assert r.status_code == 200 and r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-robots-tag"] == "noindex"
