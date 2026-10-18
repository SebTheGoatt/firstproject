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

from .conftest import FakeGeocoder, legacy_quoted_job
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
            "service": service, "lawn_sqft": 5000, "package": "standard",
            "scheduled_date": TOMORROW.isoformat(), "payment_method": method})


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
    # 5,000 sq ft on Block Lock: $105.00 flat + 8.25% tax ($8.66) = $113.66
    assert (stop["payment_method"], stop["payment_status"], stop["amount_due"]) == ("cash", "unpaid", 113.66)
    assert (stop["subtotal"], stop["tax_amount"], stop["tax_rate"]) == (105.0, 8.66, 0.0825)

    short = client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"cash_collected": 113})
    assert short.status_code == 422  # less than the $113.66 total
    # ...and a rejected cash amount must not mark the job done.
    assert client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]["completed_at"] is None

    r = client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"cash_collected": 127}).json()
    assert r["payment"] == {"status": "paid", "method": "cash", "amount_paid": 127.0, "donation": 13.34, "total": 113.66,
                            "donation_split": {"vfw": 4.4, "nicu": 4.4, "at_risk_youth": 4.54}}
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    assert (stop["payment_status"], stop["amount_paid"], stop["donation"]) == ("paid", 127.0, 13.34)


def test_card_prepay_with_donation_through_stripe(card_client, repo, stripe):
    r = book_with(card_client, "A", "0100", method="card").json()
    token = r["pay_url"].rsplit("/", 1)[1]
    assert len(token) >= 20

    info = card_client.get(f"/api/pay/{token}").json()
    assert (info["first_name"], info["amount_due"], info["payment_status"], info["card_enabled"]) == \
        ("Customer", 113.66, "unpaid", True)

    assert card_client.post(f"/api/pay/{token}/checkout", json={"donation": 600}).status_code == 422
    assert card_client.post(f"/api/pay/{token}/checkout", json={"donation": -1}).status_code == 422
    out = card_client.post(f"/api/pay/{token}/checkout", json={"donation": 10}).json()
    assert out["url"].startswith("https://checkout.stripe.test/")
    s = stripe.sessions[-1]
    assert (s["amount_due"], s["subtotal"], s["tax"], s["tax_rate"], s["donation"]) == (113.66, 105.0, 8.66, 0.0825, 10.0)
    assert stripe.sessions[-1]["success_url"].endswith(f"/pay/{token}?done=1")

    job_id = r["id"]
    payload, sig = signed(paid_event(job_id, 12366, 1000))
    assert card_client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": sig}).status_code == 200
    info = card_client.get(f"/api/pay/{token}").json()
    assert (info["payment_status"], info["amount_paid"], info["donation"]) == ("paid", 123.66, 10.0)
    assert [(c["key"], c["percent"], c["amount"]) for c in info["donation_ledger"]] == \
        [("vfw", 33, 3.3), ("nicu", 33, 3.3), ("at_risk_youth", 34, 3.4)]
    assert card_client.post(f"/api/pay/{token}/checkout", json={}).status_code == 409  # can't pay twice

    # Stripe retries webhooks; a replay must not change anything.
    payload, sig = signed(paid_event(job_id, 9900, 0))
    card_client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": sig})
    assert card_client.get(f"/api/pay/{token}").json()["amount_paid"] == 123.66


def test_webhook_rejects_bad_or_stale_signatures(card_client):
    payload, sig = signed(paid_event("x", 100, 0), secret="wrong")
    assert card_client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": sig}).status_code == 400
    assert card_client.post("/webhooks/stripe", content=payload).status_code == 400
    with pytest.raises(PaymentError, match="stale"):
        p, s = signed({"type": "x"}, t=time.time() - 3600)
        verify_webhook(p, s, WHSEC)


def test_quoted_service_gets_price_on_site_then_pay_link(card_client, repo, settings, sms):
    job = legacy_quoted_job(repo, "A", method="card")      # gutter-only booking from before add-ons
    token = job["pay_token"]
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


def test_stripe_return_links_are_https_behind_renders_proxy(settings, repo, sms, stripe):
    """Render ends TLS at its proxy, so the app may see http://; Stripe must still get https links."""
    settings.stripe_secret_key, settings.stripe_webhook_secret = "sk_test", WHSEC
    c = TestClient(create_app(settings, repo=repo, geocoder=FakeGeocoder(), sms=sms, stripe=stripe),
                   base_url="http://property-dispatch.onrender.com")
    token = book_with(c, "A", "0100", method="card").json()["pay_url"].rsplit("/", 1)[1]
    assert c.post(f"/api/pay/{token}/checkout", json={}).status_code == 200
    assert stripe.sessions[-1]["success_url"] == f"https://property-dispatch.onrender.com/pay/{token}?done=1"
    assert stripe.sessions[-1]["cancel_url"] == f"https://property-dispatch.onrender.com/pay/{token}"


def test_public_base_url_wins_for_stripe_links(settings, repo, sms, stripe):
    settings.stripe_secret_key, settings.stripe_webhook_secret = "sk_test", WHSEC
    settings.public_base_url = "https://www.mandalawncare.example/"
    c = TestClient(create_app(settings, repo=repo, geocoder=FakeGeocoder(), sms=sms, stripe=stripe))
    token = book_with(c, "A", "0100", method="card").json()["pay_url"].rsplit("/", 1)[1]
    c.post(f"/api/pay/{token}/checkout", json={})
    assert stripe.sessions[-1]["success_url"].startswith("https://www.mandalawncare.example/pay/")


# ---------- Stripe audit metadata + payment_intent.succeeded ----------
def book_supporter(client, letter="A", phone="0100", charity_choice="vfw"):
    with patch("app.main.local_now", return_value=NOW):
        r = client.post("/api/jobs", json={
            "name": f"Customer {letter}", "phone": f"(281) 555-{phone}", "address": f"100 {letter} Example Rd",
            "service": "mowing", "lawn_sqft": 5000, "package": "supporter", "charity_choice": charity_choice,
            "scheduled_date": TOMORROW.isoformat(), "payment_method": "card"})
    assert r.status_code == 201, r.text
    return r.json()


def test_checkout_charges_the_bracket_total_and_tags_it_for_the_audit(card_client, repo, settings, stripe):
    r = book_supporter(card_client)
    token = r["pay_url"].rsplit("/", 1)[1]
    card_client.post(f"/api/pay/{token}/checkout", json={})
    s = stripe.sessions[-1]
    # 5,000 sq ft on Operational Target: $114.00 flat + 8.25% tax ($9.41) = $123.41 → 12341 cents
    assert (s["amount_due"], s["subtotal"], s["tax"]) == (123.41, 114.0, 9.41)
    assert s["audit"] == {"property_profile": "Standard Suburb Profile", "size_bracket": "3,501-7,500 sq ft",
                          "service_track": "Operational Target",
                          "charity_lane": "vfw", "crew_route_id": f"{TOMORROW}#not-routed"}

    route_stops(card_client, repo, settings)          # once the route is built, the stop number is known
    card_client.post(f"/api/pay/{token}/checkout", json={})
    assert stripe.sessions[-1]["audit"]["crew_route_id"] == f"{TOMORROW}#1"
    assert not any(v in str(stripe.sessions[-1]["audit"]) for v in ("Customer", "555", "Example Rd"))   # no personal info


def test_audit_metadata_goes_on_the_session_and_the_payment_intent(settings):
    import httpx
    from urllib.parse import parse_qs
    from app.payments import StripeClient
    sent = {}

    def handler(req):
        sent.update({k: v[0] for k, v in parse_qs(req.content.decode()).items()})
        return httpx.Response(200, json={"id": "cs_1", "url": "https://checkout.stripe.test/1"})

    settings.stripe_secret_key = "sk_test"
    audit = {"property_profile": "Standard Suburb Profile", "size_bracket": "3,501-7,500 sq ft", "service_track": "Operational Target",
             "charity_lane": "vfw", "crew_route_id": "2026-10-20#3"}
    StripeClient(settings, httpx.Client(transport=httpx.MockTransport(handler))).create_checkout(
        job_id="j1", service_label="Mowing", service_date="2026-10-20", amount_due=123.41, donation=0,
        success_url="https://x/ok", cancel_url="https://x/no", subtotal=114.0, tax=9.41, tax_rate=0.0825,
        charity_choice="vfw", audit=audit)
    assert sent["metadata[amount_due_cents]"] == "12341"
    assert [sent[f"line_items[{i}][price_data][unit_amount]"] for i in (0, 1)] == ["11400", "941"]
    for key, value in {**audit, "job_id": "j1", "charity_choice": "vfw"}.items():
        assert sent[f"metadata[{key}]"] == sent[f"payment_intent_data[metadata][{key}]"] == value


def intent_event(job_id, cents, donation_cents=0, choice="vfw"):
    return {"type": "payment_intent.succeeded", "data": {"object": {
        "amount_received": cents, "metadata": {"job_id": job_id, "donation_cents": str(donation_cents),
                                               "charity_choice": choice}}}}


def test_payment_intent_succeeded_marks_paid_once_and_notifies_once(card_client, repo):
    r = book_supporter(card_client)
    token = r["pay_url"].rsplit("/", 1)[1]
    with patch("app.pay_routes.push.send_to_job", return_value={"sent": 1}) as notify:
        for event in (intent_event(r["id"], 13341, 1000), paid_event(r["id"], 13341, 1000), intent_event(r["id"], 13341, 1000)):
            payload, sig = signed(event)
            assert card_client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": sig}).status_code == 200
    assert [c.args[2:] for c in notify.call_args_list] == [(r["id"], "paid")]     # Stripe sends both events; one message
    info = card_client.get(f"/api/pay/{token}").json()
    assert (info["payment_status"], info["amount_paid"], info["donation"]) == ("paid", 133.41, 10.0)
    assert [(c["key"], c["amount"]) for c in info["donation_ledger"]] == [("vfw", 10.0)]   # all to their pick


def test_payment_intents_that_arent_ours_are_ignored(card_client):
    event = {"type": "payment_intent.succeeded", "data": {"object": {"amount_received": 500, "metadata": {}}}}
    payload, sig = signed(event)
    assert card_client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": sig}).status_code == 200
