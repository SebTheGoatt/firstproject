"""The owner's dispatch board: one day's route on a map with its real road path, the numbers that matter, and
every visit that won't be on it (and why).

    GET /api/owner/dispatch/{day}     owner: the day's route, road path, schedule, money and unrouted visits
    GET /owner/dispatch               the page (static/dispatch.html)

The page uses the existing owner actions for changes: build / rebuild the route, move a visit, rain day.
The road path comes from OSRM (settings.osrm_url), drawn once per built route and kept in memory, so opening
the board again costs nothing; if OSRM doesn't answer, the page draws straight legs instead.
"""

import logging
from datetime import date, datetime, timedelta

from fastapi import Depends, FastAPI

from .booking import local_now
from .config import Settings
from .directions import DirectionsUnavailable, route_path
from .models import order_label
from .zones import MAKEUP_WEEKDAY, short_name, zone_for_weekday

log = logging.getLogger(__name__)
PATHS_KEPT = 40


def hours_for(settings: Settings, day: date) -> tuple[str, str] | None:
    """('08:00', '17:00') on weekdays, Saturday's make-up hours, None on Sunday."""
    if day.weekday() == 6:
        return None
    start, end = (settings.saturday_hours if day.weekday() == MAKEUP_WEEKDAY else settings.weekday_hours).split("-")
    return start.strip(), end.strip()


def finish_time(stops: list) -> datetime | None:
    """When the crew finishes the last stop: its arrival plus its time on site."""
    ends = [s.eta + timedelta(minutes=s.service_minutes or 0) for s in stops if s.eta is not None]
    return max(ends) if ends else None


def unrouted_reason(job: dict, settings: Settings, area_key: str | None) -> str:
    if area_key and job.get("zone_key") and job["zone_key"] != area_key:
        return "Not this day's area: move it to its own area day"
    if settings.prepay_required and settings.stripe_enabled and job["payment_method"] == "card" \
            and job["payment_status"] != "paid":
        return "Not paid yet: it joins the route once paid"
    return "Booked after the route was built: rebuild to add it"


def register_dispatch_board(app: FastAPI, settings: Settings, owner, page, route_view, route_areas) -> None:
    paths: dict[tuple, dict | None] = {}

    def road_path(route: dict) -> dict | None:
        key = (str(route["route_date"]), str(route.get("optimized_at")), tuple(s["stop_id"] for s in route["stops"]))
        if key not in paths:
            points = [(route["start_lat"], route["start_lng"]), *((s["lat"], s["lng"]) for s in route["stops"]),
                      (route["end_lat"], route["end_lng"])]
            try:
                paths[key] = route_path(settings.osrm_url, points)
            except DirectionsUnavailable as exc:
                log.warning("Dispatch board road path unavailable: %s", exc)
                return None                      # not kept: try again next time
            while len(paths) > PATHS_KEPT:
                paths.pop(next(iter(paths)))
        return paths[key]

    @app.get("/api/owner/dispatch/{day}", dependencies=[Depends(owner)])
    def dispatch_day(day: date):
        repo = app.state.repo
        zone = zone_for_weekday(day.weekday())
        route = repo.get_route(day)
        view = route_view(route, settings) if route else None
        jobs = repo.list_jobs(day)
        on_route = {s.job_id for s in view.stops} if view else set()
        hours = hours_for(settings, day)
        finish = finish_time(view.stops) if view else None
        close = (datetime.combine(day, datetime.strptime(hours[1], "%H:%M").time()) if hours else None)
        if finish is not None and close is not None:
            close = close.replace(tzinfo=finish.tzinfo)
        return {
            "date": day.isoformat(),
            "today": local_now(settings).date().isoformat(),
            "area": short_name(zone) if zone else ("Make-up" if day.weekday() == MAKEUP_WEEKDAY else None),
            "areas": [a.model_dump() for a in route_areas(route)] if route else
                     ([{"name": short_name(zone), "boxes": [list(b) for b in zone.boxes]}] if zone else []),
            "hours": {"start": hours[0], "end": hours[1]} if hours else None,
            "timezone": settings.business_timezone,
            "quota": settings.daily_job_quota,
            "route": view.model_dump(mode="json") if view else None,
            "base": {"lat": route["start_lat"], "lng": route["start_lng"]} if route else None,
            "path": road_path(route) if route else None,
            "finish_at": finish.isoformat() if finish else None,
            "close_at": close.isoformat() if close else None,
            "minutes_to_spare": round((close - finish).total_seconds() / 60) if finish and close else None,
            "on_site_min": sum(s.service_minutes or 0 for s in view.stops) if view else 0,
            "money": {
                "expected": round(sum(j["amount_due"] or 0 for j in jobs), 2),
                "collected": round(sum(j["amount_paid"] or 0 for j in jobs if j["payment_status"] == "paid"), 2),
                "unpaid": sum(1 for j in jobs if j["payment_status"] == "unpaid"),
            },
            "unrouted": [{
                "job_id": j["job_id"], "customer_name": j["customer_name"], "address": j["address"],
                "service_label": order_label(j["service"], j.get("add_ons")),
                "payment_status": j["payment_status"], "amount_due": j["amount_due"],
                "reason": unrouted_reason(j, settings, zone.key if zone else None),
            } for j in jobs if j["job_id"] not in on_route and j["status"] in ("pending", "scheduled")],
        }

    @app.get("/owner/dispatch", include_in_schema=False)
    def dispatch_page():
        resp = page("dispatch.html")
        resp.headers["X-Robots-Tag"] = "noindex"
        return resp
