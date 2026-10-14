from datetime import date, datetime
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest

from app import deeplinks
from app.booking import BookingRejected, earliest_bookable_day, is_frozen, validate_booking
from app.models import normalize_us_phone

TZ = ZoneInfo("America/Chicago")


@pytest.mark.parametrize("now_hour, tomorrow_frozen", [(9, False), (19, False), (20, True), (23, True)])
def test_tomorrow_freezes_at_8pm(now_hour, tomorrow_frozen):
    now = datetime(2026, 10, 14, now_hour, 0, tzinfo=TZ)
    assert is_frozen(date(2026, 10, 15), now, 20) is tomorrow_frozen
    assert is_frozen(date(2026, 10, 14), now, 20)       # today: always frozen
    assert not is_frozen(date(2026, 10, 16), now, 20)   # day after: always open


def test_earliest_bookable_day_rolls_past_cutoff():
    assert earliest_bookable_day(datetime(2026, 10, 14, 19, 59, tzinfo=TZ), 20) == date(2026, 10, 15)
    assert earliest_bookable_day(datetime(2026, 10, 14, 20, 0, tzinfo=TZ), 20) == date(2026, 10, 16)


def test_quota_and_horizon(settings):
    now = datetime(2026, 10, 14, 10, 0, tzinfo=TZ)
    validate_booking(date(2026, 10, 15), now, settings.daily_job_quota - 1, settings)
    with pytest.raises(BookingRejected, match="fully booked"):
        validate_booking(date(2026, 10, 15), now, settings.daily_job_quota, settings)
    with pytest.raises(BookingRejected, match="within"):
        validate_booking(date(2027, 6, 1), now, 0, settings)


@pytest.mark.parametrize("raw", ["(281) 555-0123", "281.555.0123", "+1 281 555 0123", "12815550123"])
def test_phone_normalization(raw):
    assert normalize_us_phone(raw) == "+12815550123"


@pytest.mark.parametrize("raw", ["555-0123", "011 281 555 0123", "(081) 555-0123"])
def test_phone_rejects_bad_numbers(raw):
    with pytest.raises(ValueError):
        normalize_us_phone(raw)


def test_single_stop_links():
    g = urlparse(deeplinks.google_directions((30.1, -95.4)))
    assert g.netloc == "www.google.com"
    q = parse_qs(g.query)
    assert q["destination"] == ["30.100000,-95.400000"] and q["travelmode"] == ["driving"]
    assert "origin" not in q  # → phone's current location

    a = parse_qs(urlparse(deeplinks.apple_directions((30.1, -95.4))).query)
    assert a == {"daddr": ["30.100000,-95.400000"], "dirflg": ["d"]}


@pytest.mark.parametrize("n_stops, expected_links", [(1, 1), (9, 1), (10, 2), (19, 2), (20, 3)])
def test_full_route_is_chunked_and_chained(n_stops, expected_links):
    base = (30.0, -95.0)
    stops = [(30.0 + i / 100, -95.0) for i in range(1, n_stops + 1)]
    urls = deeplinks.google_full_route(base, stops, base)
    assert len(urls) == expected_links

    visited, prev_dest = [], None
    for k, url in enumerate(urls):
        q = parse_qs(urlparse(url).query)
        wps = q["waypoints"][0].split("|") if "waypoints" in q else []
        assert len(wps) <= deeplinks.GOOGLE_MAX_WAYPOINTS
        if k > 0:
            assert q["origin"][0] == prev_dest  # segments chain end-to-start
        visited += wps + [q["destination"][0]]
        prev_dest = q["destination"][0]

    expected = [deeplinks._fmt(p) for p in [*stops, base]]
    assert visited == expected
