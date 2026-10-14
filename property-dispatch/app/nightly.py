"""Next-day freeze + route optimization (runs at close of business, 5 PM local).

    python -m app.nightly                 # optimize tomorrow, if it's past the 5 PM cutoff
    python -m app.nightly --force         # optimize tomorrow now
    python -m app.nightly --date 2026-10-15 --force

Hosted cron services schedule in UTC, and 5 PM Central is 22:00 UTC in
summer but 23:00 UTC in winter. Schedule it hourly 22:00-02:00 UTC.
Each run exits before the local freeze hour (FREEZE_HOUR, default 17),
builds tomorrow's route at or after it, and skips if that route already
exists. So the first run after 5 PM does the work, and later runs catch up
if that one was missed (host outage, maintenance). --force rebuilds regardless.
"""

import argparse
import logging
import sys
from datetime import date, datetime, time, timedelta

from .booking import local_now, next_service_day
from .config import Settings, get_settings
from .db import Repository, make_repository
from .routing import optimize_route
from .routing.matrix import TravelMatrix

log = logging.getLogger("nightly")


def compute_etas(start_at: datetime, legs: list[tuple[int, int]]) -> list[datetime]:
    """legs = [(drive_seconds_from_previous, service_minutes_at_stop), ...]"""
    etas, clock = [], start_at
    for drive_s, service_min in legs:
        clock += timedelta(seconds=drive_s)
        etas.append(clock)
        clock += timedelta(minutes=service_min)
    return etas


def run_nightly(
    repo: Repository,
    settings: Settings,
    day: date,
    *,
    matrix: TravelMatrix | None = None,
) -> dict:
    jobs = repo.list_routable_jobs(day)
    if len(jobs) > settings.daily_job_quota:
        # Quota is enforced at intake; this only trips on manual inserts.
        log.warning("%d jobs exceed quota of %d for %s", len(jobs), settings.daily_job_quota, day)

    result = optimize_route(
        settings.start_point,
        settings.end_point,
        [(j.lat, j.lng) for j in jobs],
        osrm_url=settings.osrm_url,
        optimize_for=settings.optimize_for,
        time_limit_s=settings.solver_time_limit_s,
        matrix=matrix,
    )

    hh, mm = map(int, settings.crew_start_time.split(":"))
    start_at = datetime.combine(day, time(hh, mm), tzinfo=settings.tz)
    ordered = [jobs[leg.stop_index] for leg in result.order]
    etas = compute_etas(start_at, [(leg.duration_s, j.service_minutes) for leg, j in zip(result.order, ordered)])

    stops = [
        {
            "job_id": job.id,
            "sequence": seq,
            "leg_distance_m": leg.distance_m,
            "leg_duration_s": leg.duration_s,
            "eta": eta.isoformat(),
        }
        for seq, (leg, job, eta) in enumerate(zip(result.order, ordered, etas), start=1)
    ]

    route_id = repo.save_route(
        day=day,
        start=settings.start_point,
        end=settings.end_point,
        total_distance_m=result.total_distance_m,
        total_duration_s=result.total_duration_s,
        matrix_source=result.matrix_source,
        stops=stops,
    )
    summary = {
        "route_id": route_id,
        "route_date": day.isoformat(),
        "stops": len(stops),
        "total_miles": round(result.total_distance_m / 1609.344, 1),
        "drive_minutes": round(result.total_duration_s / 60),
        "matrix_source": result.matrix_source,
    }
    log.info("Route built: %s", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", type=date.fromisoformat, help="service date (default: tomorrow, local)")
    parser.add_argument("--force", action="store_true", help="skip the time guard and rebuild even if a route exists")
    args = parser.parse_args(argv)

    settings = get_settings()
    now = local_now(settings)
    if not args.force and now.hour < settings.freeze_hour:
        log.info("Local time is %s; before the %d:00 freeze. Exiting.", now.strftime("%H:%M %Z"), settings.freeze_hour)
        return 0

    day = args.date or next_service_day(now)
    repo = make_repository(settings)
    if not args.force and repo.get_route(day) is not None:
        log.info("Route for %s already built. Nothing to do.", day)
        return 0

    run_nightly(repo, settings, day)
    return 0


if __name__ == "__main__":
    sys.exit(main())
