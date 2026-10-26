"""The owner's numbers: what a mow really earns, what it takes to break even, and whether the business is getting
healthier. Managerial economics (contribution margin, break-even, price), corporate finance (fixed costs, equipment
payback) and business analysis (a few KPIs that drive decisions), read from real bookings and routes.

    GET /api/owner/numbers?days=90   owner only: actuals for the period, per-visit unit numbers, the next 4 weeks
    GET /owner/numbers               the page (static/numbers.html); cost assumptions are typed there and kept on
                                     that phone, since they're the owner's own estimates, not booking data

Until visits are done, the unit numbers fall back to planning values (the base price, a standard yard's minutes,
10 minutes and 4 miles of driving per stop) and say so. No names, phones or addresses are read.
"""

from collections import Counter, defaultdict
from datetime import date, timedelta

from fastapi import Depends, FastAPI

from .booking import local_now
from .config import Settings
from .pricing import YIELD_BASE, mow_minutes
from .zones import DEFAULT_TAX_RATE, WEEKDAY_NAMES, short_name, zone_by_key, zone_for_weekday

CARD_FEE = {"rate": 0.029, "fixed": 0.30}       # Stripe's standard US card price
PLANNING = {"drive_min": 10.0, "miles": 4.0}    # per stop, until real routes exist
AHEAD_DAYS = 28


def _f(v) -> float:
    return float(v or 0)


def pre_tax(r: dict) -> float:
    """The price before tax: the saved subtotal, or what was due minus the tax on older bookings."""
    return _f(r.get("subtotal")) if r.get("subtotal") is not None else max(0.0, _f(r.get("amount_due")) - _f(r.get("tax_amount")))


def compute(rows: list[dict], history: list[dict], routes: list[dict], ahead: list[dict], settings: Settings,
            today: date, days: int) -> dict:
    """rows: bookings scheduled in the period (cancelled too); history: the last year and the booked months ahead,
    for repeat customers; routes: built routes in the period; ahead: bookings in the next AHEAD_DAYS."""
    done = [r for r in rows if r.get("status") == "completed"]
    revenue = sum(pre_tax(r) for r in done)
    giving = sum(_f(r.get("charity_amount")) + _f(r.get("donation")) for r in done)
    onsite = sum(_f(r.get("service_minutes")) for r in done)
    drive = sum(_f(x.get("total_duration_s")) for x in routes) / 60
    miles = sum(_f(x.get("total_distance_m")) for x in routes) / 1609.344
    crew_min = onsite + drive
    n = len(done)

    live = Counter(r["customer_id"] for r in history if r.get("status") != "cancelled" and r.get("customer_id"))
    customers = len(live)
    repeat = sum(1 for c in live.values() if c >= 2)

    by_area = defaultdict(lambda: {"visits": 0, "revenue": 0.0})
    for r in done:
        a = by_area[r.get("zone_key") or "?"]
        a["visits"] += 1
        a["revenue"] += pre_tax(r)

    actual = n >= 3 and bool(routes)             # a handful of real visits beats planning numbers
    unit = ({"basis": "actual", "ticket": revenue / n, "onsite_min": onsite / n, "drive_min": drive / n,
             "miles": miles / n, "giving_rate": giving / revenue if revenue else 0.0} if actual else
            {"basis": "planning", "ticket": float(YIELD_BASE), "onsite_min": float(mow_minutes(None)),
             "drive_min": PLANNING["drive_min"], "miles": PLANNING["miles"], "giving_rate": 0.02})
    unit = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in unit.items()}

    per_day = Counter(str(r["scheduled_date"]) for r in ahead if r.get("status") != "cancelled")
    upcoming = []
    for i in range(1, AHEAD_DAYS + 1):
        d = today + timedelta(days=i)
        zone = zone_for_weekday(d.weekday())
        if zone is None:
            continue
        upcoming.append({"date": d.isoformat(), "weekday": WEEKDAY_NAMES[d.weekday()][:3], "area": short_name(zone),
                         "booked": per_day.get(d.isoformat(), 0), "quota": settings.daily_job_quota})
    capacity = sum(u["quota"] for u in upcoming)

    return {
        "period": {"days": days, "start": (today - timedelta(days=days)).isoformat(), "end": today.isoformat()},
        "actual": {
            "visits": n, "revenue": round(revenue, 2), "giving": round(giving, 2),
            "avg_ticket": round(revenue / n, 2) if n else None,
            "visits_per_week": round(n / (days / 7), 1),
            "cancel_rate": round(sum(1 for r in rows if r.get("status") == "cancelled") / len(rows), 3) if rows else None,
            "repeat_rate": round(repeat / customers, 3) if customers else None, "customers": customers,
            "lawn_share": round(onsite / crew_min, 3) if crew_min else None,
            "per_crew_hour": round(revenue / (crew_min / 60), 2) if crew_min else None,
            "drive_min": round(drive), "onsite_min": round(onsite), "miles": round(miles, 1),
        },
        "areas": sorted(({"area": short_name(zone_by_key(k)) if zone_by_key(k) else "Other", "visits": v["visits"],
                          "revenue": round(v["revenue"], 2)} for k, v in by_area.items()), key=lambda a: -a["revenue"]),
        "unit": unit,
        "ahead": upcoming,
        "fill_rate": round(sum(u["booked"] for u in upcoming) / capacity, 3) if capacity else None,
        "tax_rate": DEFAULT_TAX_RATE, "card_fee": CARD_FEE,
    }


def register_numbers(app: FastAPI, settings: Settings, owner, page) -> None:
    @app.get("/api/owner/numbers", dependencies=[Depends(owner)])
    def numbers(days: int = 90):
        days = max(7, min(days, 365))
        repo = app.state.repo
        today = local_now(settings).date()
        start = today - timedelta(days=days)
        rows = repo.business_rows(start, today)
        history = repo.business_rows(today - timedelta(days=365), today + timedelta(days=settings.booking_horizon_days))
        routes = repo.route_totals_between(start, today)
        ahead = repo.business_rows(today + timedelta(days=1), today + timedelta(days=AHEAD_DAYS))
        return compute(rows, history, routes, ahead, settings, today, days)

    @app.get("/owner/numbers", include_in_schema=False)
    def numbers_page():
        resp = page("numbers.html")
        resp.headers["X-Robots-Tag"] = "noindex"
        return resp
