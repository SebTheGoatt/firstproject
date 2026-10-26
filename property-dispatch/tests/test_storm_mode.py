"""Storm mode (CLOSED_UNTIL): no service through that day, a notice on every page, bookings start the day after,
and the owner sees which booked visits still need a new day. It turns itself off once the date has passed."""

from datetime import date, timedelta
from unittest.mock import patch

from app.booking import BookingRejected, closed_through, earliest_bookable_day, service_floor, validate_booking
from app.config import Settings

from .test_api_flow import CREW, NOW, TOMORROW, book
from .test_visit_owner import booked

CLOSED = NOW.date() + timedelta(days=3)


def at_now(client, path, **kw):
    with patch("app.main.local_now", return_value=NOW), patch("app.local_pages.local_now", return_value=NOW), \
            patch("app.command.local_now", return_value=NOW), patch("app.visit_routes.local_now", return_value=NOW):
        return client.get(path, **kw)


def test_off_by_default_and_blank(settings):
    assert Settings(_env_file=None, closed_until="").closed_until is None
    assert closed_through(NOW, settings) is None and service_floor(NOW, settings) is None


def test_closed_days_are_refused_and_booking_starts_after(settings):
    settings.closed_until = CLOSED
    assert closed_through(NOW, settings) == CLOSED
    assert earliest_bookable_day(NOW, settings.freeze_hour, service_floor(NOW, settings)) == CLOSED + timedelta(days=1)
    try:
        validate_booking(CLOSED, NOW, 0, settings)
        raise AssertionError("a closed day must be refused")
    except BookingRejected as exc:
        assert "closed through Saturday, October 17" in str(exc)
    validate_booking(CLOSED + timedelta(days=1), NOW, 0, settings)
    settings.launch_date = CLOSED + timedelta(days=10)                     # pre-orders and a storm: the later one wins
    assert service_floor(NOW, settings) == CLOSED + timedelta(days=10)


def test_the_notice_tops_every_page_and_the_owner_sees_who_to_move(client, settings):
    booked(client, "A", "0100")                                           # tomorrow, before storm mode starts
    settings.closed_until = CLOSED
    settings.closed_note = 'Stay safe <b>everyone</b>.'
    for path in ("/", "/book", "/local", "/visit"):
        page = at_now(client, path).text
        assert "Storm update:" in page and "We're closed through Saturday, October 17." in page, path
        assert "Stay safe &lt;b&gt;everyone&lt;/b&gt;." in page, path    # the owner's note is shown as text
    info = at_now(client, "/api/booking-info").json()
    assert info["closed"] == {"until": CLOSED.isoformat(), "note": "Stay safe <b>everyone</b>."}
    assert info["earliest_date"] == (CLOSED + timedelta(days=1)).isoformat()
    with patch("app.main.local_now", return_value=NOW), patch("app.visit_routes.local_now", return_value=NOW):
        r = book(client, "B", "0101", day=TOMORROW)
    assert r.status_code == 409 and "closed through" in r.json()["detail"]
    cmd = at_now(client, "/api/owner/command", headers=CREW).json()
    assert cmd["closed"] == {"until": CLOSED.isoformat(), "affected": 1}


def test_it_turns_itself_off_after_the_date(client, settings):
    settings.closed_until = NOW.date() - timedelta(days=1)
    assert closed_through(NOW, settings) is None
    assert "Storm update:" not in at_now(client, "/").text
    assert at_now(client, "/api/booking-info").json()["closed"] is None
    assert date.fromisoformat(at_now(client, "/api/booking-info").json()["earliest_date"]) == TOMORROW
