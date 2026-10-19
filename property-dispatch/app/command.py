"""Owner command view: one screen of live numbers (bookings, money, route load, liability).

    GET /api/owner/command   owner only: the numbers below, read from real bookings and settings
    GET /owner/command       the page (uses the crew sign-in saved on the phone)

Every figure comes from the database or the owner's settings. Anything the app doesn't track yet
(Stripe disputes, mower hours) is returned as None and shown as NOT TRACKED, never a made-up value.
"""

from datetime import date, timedelta

from fastapi import Depends, FastAPI

from .booking import local_now
from .config import Settings
from .models import order_label
from .zones import MAKEUP_WEEKDAY, short_name, zone_by_key, zone_for_weekday

TERMINAL_DAYS = 7
TERMINAL_LIMIT = 40


def _money(v) -> float:
    return round(float(v or 0), 2)


def day_area(day: date) -> str | None:
    zone = zone_for_weekday(day.weekday())
    return short_name(zone) if zone else ("Make-up" if day.weekday() == MAKEUP_WEEKDAY else None)


def revenue(rows: list[dict]) -> dict:
    paid = [r for r in rows if r.get("payment_status") == "paid"]
    return {
        "bookings": len(rows),
        "expected": _money(sum(float(r.get("amount_due") or 0) for r in rows)),
        "collected": _money(sum(float(r.get("amount_paid") or 0) for r in paid)),
        "unpaid": _money(sum(float(r.get("amount_due") or 0) for r in rows if r.get("payment_status") != "paid")),
        "sales_tax": _money(sum(float(r.get("tax_amount") or 0) for r in paid)),
        "paid_count": len(paid),
    }


def next_area_day(zone, after: date) -> date | None:
    """The area's next weekday after `after` (where INTERCEPT moves an outlier)."""
    if zone is None:
        return None
    return after + timedelta(days=(zone.service_weekday - after.weekday()) % 7 or 7)


def terminal_row(j: dict, day: date, today: date) -> dict:
    zone = zone_by_key(j.get("zone_key"))
    off = bool(zone_for_weekday(day.weekday()) and zone and zone.key != zone_for_weekday(day.weekday()).key)
    scope = next((a["key"] for a in (j.get("add_ons") or []) if a.get("key") in ("scope_yard", "scope_full")), None)
    return {
        "ref": "P1-" + str(j["job_id"])[:4].upper(),
        "job_id": j["job_id"],
        "name": j.get("customer_name"),          # owner-only screen, same as the owner dashboard
        "address": j.get("address"),
        "date": day.isoformat(),
        "area": short_name(zone) if zone else "?",
        "sqft": j.get("lawn_sqft"),
        "scope": {"scope_yard": "Fenced core", "scope_full": "Full property"}.get(scope),
        "service": order_label(j["service"], j.get("add_ons")),
        "status": "DONE" if j.get("completed_at") else ("ROUTED" if j.get("sequence") else "PENDING DISPATCH"),
        "pay": j.get("payment_method"),
        "paid": j.get("payment_status") == "paid",
        "amount": _money(j.get("amount_due")),
        "off_area": off,
        "move_to": next_area_day(zone, today).isoformat() if off and zone else None,
    }


def register_command(app: FastAPI, settings: Settings, owner, page) -> None:
    def repo():
        return app.state.repo

    @app.get("/api/owner/command", dependencies=[Depends(owner)])
    def command():
        today = local_now(settings).date()
        month = repo().list_jobs_between(today.replace(day=1), today)
        week_rows = repo().list_jobs_between(today, today + timedelta(days=TERMINAL_DAYS - 1))
        week = []
        terminal = []
        for i in range(TERMINAL_DAYS):
            d = today + timedelta(days=i)
            rows = [r for r in week_rows if str(r["scheduled_date"]) == d.isoformat()]
            week.append({"date": d.isoformat(), "area": day_area(d), "jobs": len(rows), "quota": settings.daily_job_quota,
                         "expected": _money(sum(float(r.get("amount_due") or 0) for r in rows))})
            if rows and len(terminal) < TERMINAL_LIMIT:
                terminal += [terminal_row(j, d, today) for j in repo().list_jobs(d)][: TERMINAL_LIMIT - len(terminal)]
        # Pre/post photo log for today's visits (the crew's before and after shots).
        photos = []
        for j in repo().list_jobs(today):
            kinds = [p.get("kind") for p in repo().list_job_photos(j["job_id"])]
            photos.append({"ref": "P1-" + str(j["job_id"])[:4].upper(), "before": "before" in kinds, "after": "after" in kinds,
                           "done": bool(j.get("completed_at"))})
        cgl = settings.liability_coverage.strip() or None
        # The next route to compute: the first upcoming day that has bookings.
        nxt = next((date.fromisoformat(w["date"]) for w in week if w["jobs"] and w["date"] > today.isoformat()), None)
        route = repo().get_route(nxt) if nxt else None
        return {
            "next_route": {"date": nxt.isoformat() if nxt else None, "built": route is not None,
                           "stops": len(route["stops"]) if route else 0},
            "date": today.isoformat(),
            "area_today": day_area(today),
            "revenue_mtd": revenue(month),
            "week": week,
            "terminal": terminal,
            "defense": {
                "cgl": cgl,                                         # from LIABILITY_COVERAGE; None = not on file
                "background_checked": settings.crew_background_checked,
                "photo_log": photos,
                "stripe_live": app.state.stripe is not None,
                "stripe_disputes": None,                            # not tracked yet: see the Stripe dashboard
                "fleet": None,                                      # mower hours/backups: not tracked in the app
                "tda": "N/A: no pesticide or herbicide application offered (no TDA license needed for mowing)",
            },
        }

    @app.get("/owner/command", include_in_schema=False)
    def command_page():
        resp = page("command.html")
        resp.headers["X-Robots-Tag"] = "noindex"
        return resp
