"""Mid-day re-optimization for the crew dashboard.

The 5 PM nightly run (app/nightly.py) plans the whole day from the base. During the day the
crew can ask for a fresh order of the stops that are still open, starting from where they are
now (phone GPS), so the next job is always the closest sensible one.

Rules:
- Finished stops keep their place at the front (renumbered by finish time).
- A stop whose customer was already told "on the way" stays next: we don't make them wait.
- Everything else is re-solved with the same matrix + OR-Tools solver as the nightly run.
- No GPS → start from the last finished stop, or the base if none is finished yet.
"""

from datetime import date, datetime, time

from .config import Settings
from .db import Repository
from .nightly import compute_etas
from .routing import optimize_route
from .routing.matrix import TravelMatrix

LatLng = tuple[float, float]


def reoptimize_remaining(repo: Repository, settings: Settings, day: date, now: datetime,
                         origin: LatLng | None = None, *, matrix: TravelMatrix | None = None) -> dict:
    route = repo.get_route(day)
    if route is None:
        raise LookupError(f"No route has been built for {day}")
    stops = route["stops"]
    done = sorted((s for s in stops if s["completed_at"]), key=lambda s: str(s["completed_at"]))
    open_ = [s for s in stops if not s["completed_at"]]
    pinned = [s for s in open_ if s.get("notified_at")]          # customer already told we're coming
    free = [s for s in open_ if not s.get("notified_at")]

    if origin is None:
        origin = (done[-1]["lat"], done[-1]["lng"]) if done else settings.start_point
    # The solver starts after the last pinned stop (we're going there first anyway).
    solve_from = (pinned[-1]["lat"], pinned[-1]["lng"]) if pinned else origin

    if free:
        result = optimize_route(solve_from, settings.end_point, [(s["lat"], s["lng"]) for s in free],
                                osrm_url=settings.osrm_url, optimize_for=settings.optimize_for,
                                time_limit_s=settings.solver_time_limit_s, matrix=matrix)
        ordered_free = [(free[leg.stop_index], leg.distance_m, leg.duration_s) for leg in result.order]
        source = result.matrix_source
    else:
        ordered_free, source = [], route["matrix_source"]

    # Pinned stops keep their old legs; their ETAs move with the clock.
    ordered = [(s, s["leg_distance_m"], s["leg_duration_s"]) for s in pinned] + ordered_free
    hh, mm = map(int, settings.crew_start_time.split(":"))
    start_at = max(now, datetime.combine(day, time(hh, mm), tzinfo=settings.tz))
    etas = compute_etas(start_at, [(dur, s.get("service_minutes") or 0) for s, _, dur in ordered])

    updates = [{"stop_id": s["stop_id"], "sequence": seq, "leg_distance_m": s["leg_distance_m"],
                "leg_duration_s": s["leg_duration_s"], "eta": s["eta"]}
               for seq, s in enumerate(done, start=1)]
    updates += [{"stop_id": s["stop_id"], "sequence": len(done) + i, "leg_distance_m": dist,
                 "leg_duration_s": dur, "eta": eta.isoformat()}
                for i, ((s, dist, dur), eta) in enumerate(zip(ordered, etas), start=1)]
    repo.resequence_stops(route["id"], updates)
    return {"route_date": day.isoformat(), "finished": len(done), "remaining": len(ordered),
            "kept_first": len(pinned), "matrix_source": source}
