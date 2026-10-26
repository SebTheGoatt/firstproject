"""Pre-orders: with LAUNCH_DATE set, the booking window opens on opening day, so every booking until then is a
pre-order (paid at booking like any other, free to cancel until the crew is on the way). Blank = no change."""

from datetime import date, timedelta
from unittest.mock import patch

from app.booking import (BookingRejected, earliest_bookable_day, latest_bookable_day, preorder_count, preorders_open,
                         validate_booking)
from app.config import Settings

from .test_api_flow import CREW, NOW, book

LAUNCH = date(2026, 11, 2)        # a Monday, 19 days after the test clock (Wed Oct 14)


def booked_on(client, letter, phone, day):
    with patch("app.main.local_now", return_value=NOW), patch("app.visit_routes.local_now", return_value=NOW):
        return book(client, letter, phone, day=day)


def info(client):
    with patch("app.main.local_now", return_value=NOW):
        return client.get("/api/booking-info").json()


def test_blank_launch_date_changes_nothing(settings):
    assert Settings(_env_file=None, launch_date="").launch_date is None
    assert not preorders_open(NOW, settings)
    assert earliest_bookable_day(NOW, settings.freeze_hour, settings.launch_date) == NOW.date() + timedelta(days=1)
    assert latest_bookable_day(NOW, settings) == NOW.date() + timedelta(days=settings.booking_horizon_days)


def test_the_window_opens_on_launch_day(settings):
    settings.launch_date = LAUNCH
    assert preorders_open(NOW, settings)
    assert earliest_bookable_day(NOW, settings.freeze_hour, LAUNCH) == LAUNCH
    assert latest_bookable_day(NOW, settings) == LAUNCH + timedelta(days=settings.booking_horizon_days)
    try:
        validate_booking(LAUNCH - timedelta(days=1), NOW, 0, settings)
        raise AssertionError("a day before launch must be refused")
    except BookingRejected as exc:
        assert "We start mowing on Monday, November 2" in str(exc)
    validate_booking(LAUNCH, NOW, 0, settings)                                        # opening day: fine
    validate_booking(LAUNCH + timedelta(days=settings.booking_horizon_days), NOW, 0, settings)   # horizon runs from launch


def test_pre_orders_through_the_api_and_the_real_count(client, settings, repo):
    settings.launch_date = LAUNCH
    r = booked_on(client, "A", "0100", NOW.date() + timedelta(days=2))                # before opening day
    assert r.status_code == 409 and "We start mowing" in r.json()["detail"]
    for i, letter in enumerate("ABCD"):
        assert booked_on(client, letter, f"010{i}", LAUNCH).status_code == 201, letter
    pre = info(client)["preorder"]
    assert pre["open"] and pre["launch_date"] == LAUNCH.isoformat()
    assert pre["count"] is None                                                       # 4: not shown publicly yet
    assert preorder_count(repo, NOW, settings) == 4                                   # the owner sees it
    assert booked_on(client, "E", "0104", LAUNCH + timedelta(days=7)).status_code == 201
    assert info(client)["preorder"]["count"] == 5                                     # a real 5 shows
    assert info(client)["earliest_date"] == LAUNCH.isoformat()
    with patch("app.marketing.local_now", return_value=NOW), patch("app.main.local_now", return_value=NOW):
        hub = client.get("/api/owner/marketing", headers=CREW).json()
    assert hub["preorders"] == {"open": True, "launch_date": LAUNCH.isoformat(), "count": 5}
    assert hub["posts"] and all(p["date"] >= LAUNCH.isoformat() for p in hub["posts"])   # posts point at opening week
    assert "pre-orders open" in hub["posts"][0]["posts"][0]["en"]


def test_after_launch_it_is_ordinary_booking(client, settings):
    settings.launch_date = NOW.date()                                                 # opened today
    pre = info(client)["preorder"]
    assert pre == {"open": False, "launch_date": None, "count": None}
    assert booked_on(client, "A", "0100", NOW.date() + timedelta(days=1)).status_code == 201


def test_pages_carry_the_notice_hooks(client):
    assert 'id="preorder-note"' in client.get("/book").text
    home = client.get("/").text
    assert 'id="next-kicker"' in home and 'id="preorder-count"' in home
