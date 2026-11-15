"""Scarcity and framing from live bookings only: openings left when a route is nearly full, the real deadline,
what waiting costs, and homes booked nearby. Nothing shows when it isn't true."""
from datetime import date
from unittest.mock import patch

from app.booking import NEIGHBORS_SHOW, SCARCITY_SHOW

from .test_api_flow import NOW, TOMORROW, book

AREA = "/local/colony-ridge"          # Thursdays; TOMORROW (Oct 15, 2026) is its next day from NOW


def area_page(client):
    with patch("app.local_pages.local_now", return_value=NOW):
        return client.get(AREA).text


def fill(client, n):
    with patch("app.main.local_now", return_value=NOW):
        for i in range(n):
            assert book(client, "ABCDE"[i % 5], f"02{i:02d}").status_code == 201


def test_an_open_route_shows_the_deadline_and_what_waiting_costs_but_no_count(client, settings):
    page = area_page(client)
    assert "Booking for this day closes Wednesday at 5 PM." in page            # Oct 14, the day before, at the cutoff
    assert "After that, the next Colony Ridge day is Thursday, October 22." in page
    assert "We mow Colony Ridge on Thursdays, so the crew stays in your area all day." in page
    assert "openings left" not in page and "homes are booked" not in page    # 25 open, 0 booked: nothing to claim


def test_a_nearly_full_route_names_its_real_openings_and_neighbors(client, settings):
    settings.daily_job_quota = NEIGHBORS_SHOW + 3
    fill(client, NEIGHBORS_SHOW)
    page = area_page(client)
    assert "Only 3 openings left on Thursday's Colony Ridge route." in page
    assert f"{NEIGHBORS_SHOW} Colony Ridge homes are booked over the next two weeks." in page


def test_few_bookings_are_never_shown_as_a_crowd(client, settings):
    fill(client, NEIGHBORS_SHOW - 1)
    page = area_page(client)
    assert "homes are booked" not in page and "openings left" not in page


def test_the_same_line_drives_every_page_and_post(client):
    assert SCARCITY_SHOW == 8
    with patch("app.main.local_now", return_value=NOW):
        assert client.get("/api/booking-info").json()["scarcity_show"] == SCARCITY_SHOW
    assert "info.scarcity_show" in client.get("/").text and "window.SCARCITY_SHOW" in client.get("/book").text
    import inspect
    from app import marketing
    assert "spots <= SCARCITY_SHOW" in inspect.getsource(marketing.week_posts)
    spanish = client.get("/static/i18n.js").text
    for phrase in ("openings? left on", "Booking for this day closes", "After that, the next", "homes are booked over"):
        assert phrase in spanish
    assert date(2026, 10, 15) == TOMORROW
