"""Cancelling and moving bookings: customer cancel (with automatic card refund), owner cancel / move / rain day."""

import json
from unittest.mock import patch

import httpx

from app.nightly import run_nightly
from app.payments import StripeClient

from .test_api_flow import CREW, NOW, TOMORROW, book
from .test_visit_owner import booked


def test_customer_can_cancel_before_the_crew_is_on_the_way(client, repo, sms):
    j = booked(client)
    code = j["access_code"].replace("-", "")
    with patch("app.changes.local_now", return_value=NOW):
        assert client.post(f"/api/visit/{code}/cancel", json={"confirm": False}).status_code == 422
        r = client.post(f"/api/visit/{code}/cancel", json={"confirm": True})
    assert r.status_code == 200 and r.json() == {"cancelled": True, "refund": "none"}
    assert repo.jobs[j["id"]]["status"] == "cancelled"
    assert "is cancelled" in sms.sent[-1][1] and "Reply STOP" in sms.sent[-1][1]
    assert client.get(f"/api/visit/{code}").json()["status"] == "cancelled"
    assert client.post(f"/api/visit/{code}/cancel", json={"confirm": True}).status_code == 409      # only once


def test_no_online_cancel_once_the_crew_is_on_the_way(client, repo, settings):
    j = booked(client)
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    repo.stops[stop["stop_id"]]["notified_at"] = "2026-10-15T08:00:00+00:00"
    r = client.post(f"/api/visit/{j['access_code']}/cancel", json={"confirm": True})
    assert r.status_code == 409 and "on the way" in r.json()["detail"]


def test_cancelled_visit_leaves_the_route_and_stops_are_renumbered(client, repo, settings):
    a = booked(client, "A", "0100"); booked(client, "B", "0101"); booked(client, "C", "0102")
    run_nightly(repo, settings, TOMORROW)
    r = client.post(f"/api/owner/jobs/{a['id']}/cancel", headers=CREW)
    assert r.status_code == 200
    stops = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"]
    assert len(stops) == 2 and [s["sequence"] for s in stops] == [1, 2] and a["id"] not in {s["job_id"] for s in stops}


def test_paid_card_visit_is_refunded_through_stripe(settings, repo, sms):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from .conftest import FakeGeocoder
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path, req.content.decode()))
        if req.url.path.startswith("/v1/checkout/sessions/"):
            return httpx.Response(200, json={"id": "cs_1", "payment_intent": "pi_1"})
        if req.url.path == "/v1/refunds":
            return httpx.Response(200, json={"id": "re_1"})
        return httpx.Response(200, json={"id": "cs_1", "url": "https://checkout.stripe.test/1"})

    settings.stripe_secret_key, settings.stripe_webhook_secret = "sk_test", "whsec_test"
    client = TestClient(create_app(settings, repo=repo, geocoder=FakeGeocoder(), sms=sms,
                                   stripe=StripeClient(settings, httpx.Client(transport=httpx.MockTransport(handler)))))
    with patch("app.main.local_now", return_value=NOW):
        j = client.post("/api/jobs", json={"name": "Customer A", "phone": "(281) 555-0100", "address": "100 A Example Rd",
                                           "service": "mowing", "lawn_sqft": 5000, "yard_type": "STANDARD",
                                           "scheduled_date": TOMORROW.isoformat(), "payment_method": "card"}).json()
    repo.jobs[j["id"]]["stripe_session_id"] = "cs_1"
    repo.mark_paid(j["id"], method="card", amount_paid=81.19, donation=0)
    r = client.post(f"/api/visit/{j['access_code']}/cancel", json={"confirm": True})
    assert r.json() == {"cancelled": True, "refund": "started"}
    assert ("POST", "/v1/refunds", "payment_intent=pi_1&metadata%5Breason%5D=visit_cancelled") in calls
    assert "full refund is on its way" in sms.sent[-1][1]


def test_owner_moves_a_visit_and_the_customer_is_told(client, repo, sms):
    from datetime import timedelta
    j = booked(client)
    later = TOMORROW + timedelta(days=2)
    with patch("app.changes.local_now", return_value=NOW):
        assert client.post(f"/api/owner/jobs/{j['id']}/move", headers=CREW, json={"day": str(NOW.date())}).status_code == 422
        r = client.post(f"/api/owner/jobs/{j['id']}/move", headers=CREW, json={"day": str(later)})
    assert r.status_code == 200 and repo.jobs[j["id"]]["scheduled_date"] == later
    assert "we moved your" in sms.sent[-1][1].lower() and "full refund" in sms.sent[-1][1]
    assert client.post(f"/api/owner/jobs/{j['id']}/move", json={"day": str(later)}).status_code == 401


def test_rain_day_moves_every_unstarted_visit(client, repo, settings, sms):
    from datetime import timedelta
    a = booked(client, "A", "0100"); b = booked(client, "B", "0101")
    run_nightly(repo, settings, TOMORROW)
    with patch("app.changes.local_now", return_value=NOW):
        r = client.post(f"/api/owner/days/{TOMORROW}/rain", headers=CREW).json()
    saturday = TOMORROW + timedelta(days=(5 - TOMORROW.weekday()) % 7)      # that week's weather make-up day
    assert r == {"moved": 2, "to": str(saturday)}
    assert all(repo.jobs[x["id"]]["scheduled_date"] == saturday for x in (a, b))
    assert sum("because of the weather" in m[1] for m in sms.sent) == 2


def test_security_headers_and_friendly_404(client):
    r = client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    r = client.get("/pay/" + "x" * 20)
    assert r.headers["referrer-policy"] == "no-referrer"                    # the route's stricter header wins
    page = client.get("/no-such-page", headers={"accept": "text/html"})
    assert page.status_code == 404 and "We couldn't find that page" in page.text
    api = client.get("/api/no-such-thing", headers={"accept": "text/html"})
    assert api.status_code == 404 and api.json() == {"detail": "Not Found"}
