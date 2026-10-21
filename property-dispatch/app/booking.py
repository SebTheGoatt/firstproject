"""Runway quota & time-window freeze rules, shared by intake and the nightly run.

* A day is frozen once the daily cutoff (default 5 PM local) passes on the
  day before it. Today and any past day are always frozen.
* Each day accepts at most DAILY_JOB_QUOTA active (pending/scheduled) jobs.
* One area per day: an address can only be booked on its area's weekday (app/zones.py).
"""

import time
from datetime import date, datetime, timedelta

from .config import Settings
from .zones import WEEKDAY_NAMES, ServiceZone, service_days, short_name


class BookingRejected(Exception):
    pass


def local_now(settings: Settings) -> datetime:
    return datetime.now(settings.tz)


def next_service_day(now: datetime) -> date:
    return now.date() + timedelta(days=1)


def is_frozen(day: date, now: datetime, freeze_hour: int) -> bool:
    today = now.date()
    if day <= today:
        return True
    return day == today + timedelta(days=1) and now.hour >= freeze_hour


COUNT_TTL_S = 30.0   # display-only booking counts are reused this long (one database round trip saved per page view)


def cached_count(repo, day: date) -> int:
    """Active bookings on a day, remembered for COUNT_TTL_S on this repository. For pages and day pickers only;
    taking a booking always counts fresh (validate_booking), so a stale count can never overbook a day."""
    cache = repo.__dict__.setdefault("_count_cache", {})
    hit = cache.get(day)
    if hit and time.monotonic() - hit[0] < COUNT_TTL_S:
        return hit[1]
    n = repo.count_active_jobs(day)
    cache[day] = (time.monotonic(), n)
    return n


def forget_counts(repo) -> None:
    """Drop the remembered counts after a booking is made, moved or cancelled."""
    repo.__dict__.pop("_count_cache", None)


def earliest_bookable_day(now: datetime, freeze_hour: int) -> date:
    day = now.date() + timedelta(days=1)
    while is_frozen(day, now, freeze_hour):
        day += timedelta(days=1)
    return day


def validate_booking(day: date, now: datetime, active_jobs_that_day: int, settings: Settings) -> None:
    if is_frozen(day, now, settings.freeze_hour):
        first = earliest_bookable_day(now, settings.freeze_hour)
        raise BookingRejected(
            f"That day's route is already locked. The earliest available day is {first.strftime('%A, %b')} {first.day}."
        )
    if day > now.date() + timedelta(days=settings.booking_horizon_days):
        raise BookingRejected(f"Please book within the next {settings.booking_horizon_days} days.")
    if active_jobs_that_day >= settings.daily_job_quota:
        raise BookingRejected("That day is fully booked. Please choose another day.")


def check_area_day(day: date, zone: ServiceZone) -> None:
    """Hard rule: the crew works one area a day, so a booking must land on its area's weekday."""
    if day.weekday() != zone.service_weekday:
        name = WEEKDAY_NAMES[zone.service_weekday]
        raise BookingRejected(f"We mow {short_name(zone)} on {name}s only, so the crew stays in one area all day. "
                              f"Please pick a {name}.")


def open_area_days(zone: ServiceZone, now: datetime, settings: Settings, count_active) -> list[dict]:
    """The area's bookable days in the booking window, with spots left (full days included, marked 0)."""
    first = earliest_bookable_day(now, settings.freeze_hour)
    last = now.date() + timedelta(days=settings.booking_horizon_days)
    out = []
    for d in service_days(zone, first, last):
        try:
            left = max(0, settings.daily_job_quota - count_active(d))
        except Exception:
            left = None
        out.append({"date": d.isoformat(), "spots_left": left})
    return out
