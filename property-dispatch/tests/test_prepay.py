"""Pay first, then we mow: with Stripe set up, bookings are card only, the booking text carries the pay link,
and an unpaid card booking stays off the crew's route until it's paid."""
from app.nightly import run_nightly

from .test_api_flow import TOMORROW
from .test_payments import book_with, card_client, route_stops, stripe  # noqa: F401  (fixtures)


def test_cash_is_refused_and_card_is_required_once_stripe_is_set_up(card_client, sms):
    info = card_client.get("/api/booking-info").json()
    assert info["card_payments"] is True and info["prepay"] is True
    r = book_with(card_client, "A", "0100", method="cash")
    assert r.status_code == 422 and "when you book" in r.json()["detail"]
    r = book_with(card_client, "A", "0100", method="card")
    assert r.status_code == 201 and r.json()["pay_url"].startswith("/pay/")
    to, text = sms.sent[-1]
    assert "Pay here to lock in your visit" in text and r.json()["pay_url"] in text


def test_unpaid_card_bookings_stay_off_the_route_until_paid(card_client, repo, settings):
    paid = book_with(card_client, "A", "0100", method="card").json()
    owed = book_with(card_client, "B", "0101", method="card").json()
    repo.mark_paid(paid["id"], method="card", amount_paid=paid["total"], donation=0)
    summary = run_nightly(repo, settings, TOMORROW)
    assert summary["stops"] == 1 and summary["unpaid"] == [owed["id"]]
    stops = route_stops(card_client, repo, settings)
    assert [s["job_id"] for s in stops] == [paid["id"]]


def test_owner_screen_marks_unpaid_bookings(card_client):
    from unittest.mock import patch

    from .test_api_flow import CREW, NOW
    book_with(card_client, "A", "0100", method="card")
    with patch("app.command.local_now", return_value=NOW):
        rows = card_client.get("/api/owner/command", headers=CREW).json()["terminal"]
    assert rows and rows[0]["status"] == "AWAITING PAYMENT"


def test_without_stripe_cash_bookings_still_work(client):
    assert client.get("/api/booking-info").json()["prepay"] is False
    assert book_with(client, "A", "0100", method="cash").status_code == 201
