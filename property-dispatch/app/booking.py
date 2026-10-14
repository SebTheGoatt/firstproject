"""Runway quota & time-window freeze rules, shared by intake and the nightly run.

* A day is frozen once the nightly cutoff (default 8 PM local) passes on the
  day before it. Today and any past day are always frozen.
* Each day accepts at most DAILY_JOB_QUOTA active (pending/scheduled) jobs.
"""

from datetime import date, datetime, timedelta

from .config import Settings


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


def earliest_bookable_day(now: datetime, freeze_hour: int) -> date:
    day = now.date() + timedelta(days=1)
    while is_frozen(day, now, freeze_hour):
        day += timedelta(days=1)
    return day


def validate_booking(day: date, now: datetime, active_jobs_that_day: int, settings: Settings) -> None:
    if is_frozen(day, now, settings.freeze_hour):
        first = earliest_bookable_day(now, settings.freeze_hour)
        raise BookingRejected(
            f"That day's route is already locked. The earliest available day is {first:%A, %b %-d}."
        )
    if day > now.date() + timedelta(days=settings.booking_horizon_days):
        raise BookingRejected(f"Please book within the next {settings.booking_horizon_days} days.")
    if active_jobs_that_day >= settings.daily_job_quota:
        raise BookingRejected("That day is fully booked. Please choose another day.")
