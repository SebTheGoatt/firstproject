"""A safe door for your AI agents (StarNet) to watch and help run the site.

Agents never get your owner code. They get their own keys, which you can change or turn off in Render at any time:

    AGENT_KEY_READ   can look: site health, a day's numbers, the week ahead, the audit log
    AGENT_KEY_OPS    can look, and also build/rebuild a day's route (the same safe action the owner button does)

Endpoints (header  X-Agent-Key: <key>):
    GET  /api/agent/health
    GET  /api/agent/day/{date}                 counts, money totals, route status, bookings without names/phones/codes
    GET  /api/agent/outlook?days=7
    GET  /api/agent/audit                      the last 100 things any agent did
    GET  /api/agent/manifest                   the site's facts, features and settings status, for StarNet to compare
    POST /api/agent/routes/{date}/build        (ops key only)
    POST /api/agent/routes/{date}/stops/{n}/on-the-way   (ops key only) the site tells that customer the crew is on the way

What agents can never do here: see customer names, phone numbers or access codes, see payment details beyond totals,
refund or change prices, change settings or keys, delete anything, or deploy. Street addresses are only returned to
the ops key and only when asked for. Every call is rate limited and written to an audit log (also in Render's logs).
"""

import hmac
import logging
import time
from collections import deque
from datetime import date, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from . import push
from .agent_manifest import build_manifest
from .booking import local_now
from .config import Settings
from .models import order_label
from .nightly import run_nightly
from .notify import notify_stop

log = logging.getLogger("agent_api")

RATE_LIMIT = 120          # calls per minute per key
AUDIT_SIZE = 200


API_VERSION = 2
CLIENT_MIN_VERSION = 2
QUIET_BEFORE, QUIET_AFTER = 6, 20      # customers are never notified before 6 AM or after 8 PM
EARLY_MINUTES = 30                     # ...nor more than 30 minutes before the crew is due


def _as_dt(value, settings):
    """A stop's arrival time as an aware datetime (it may arrive as text or already parsed)."""
    if value is None:
        return None
    from datetime import datetime
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    return dt if dt.tzinfo else dt.replace(tzinfo=settings.tz)       # the oldest StarNet client file this site still works with

# One list of everything agents can do. StarNet's client uses the same tool names; /api/agent/manifest publishes this.
ENDPOINTS = [
    {"tool": "site_health", "method": "GET", "path": "/api/agent/health", "scope": "read", "needs_approval": False,
     "does": "Is the site up, and which features are on"},
    {"tool": "day_summary", "method": "GET", "path": "/api/agent/day/{date}", "scope": "read", "needs_approval": False,
     "does": "One day's bookings, totals and route status, without names or phone numbers"},
    {"tool": "week_outlook", "method": "GET", "path": "/api/agent/outlook", "scope": "read", "needs_approval": False,
     "does": "Bookings and expected revenue for the coming days"},
    {"tool": "audit_log", "method": "GET", "path": "/api/agent/audit", "scope": "read", "needs_approval": False,
     "does": "The last things any agent did"},
    {"tool": "sync_check", "method": "GET", "path": "/api/agent/manifest", "scope": "read", "needs_approval": False,
     "does": "What the site is, its facts and settings, for comparing with StarNet"},
    {"tool": "build_route", "method": "POST", "path": "/api/agent/routes/{date}/build", "scope": "ops",
     "needs_approval": False, "does": "Build or rebuild a day's driving route (the owner delegated this; it is reversible)"},
    {"tool": "notify_on_the_way", "method": "POST", "path": "/api/agent/routes/{date}/stops/{sequence}/on-the-way",
     "scope": "ops", "needs_approval": False,
     "does": "Tell the next customer the crew is on the way (the website writes and sends the message itself)"},
]


class Gate:
    """Checks the agent key, rate limits it, and remembers what was done."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.hits: dict[str, deque] = {"read": deque(), "ops": deque()}
        self.audit: deque = deque(maxlen=AUDIT_SIZE)

    def role_for(self, key: str | None) -> str | None:
        if not key:
            return None
        for role, expected in (("ops", self.settings.agent_key_ops), ("read", self.settings.agent_key_read)):
            if expected and hmac.compare_digest(key.encode(), expected.encode()):
                return role
        return None

    def record(self, role: str, request: Request, outcome: str = "ok") -> None:
        entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "role": role,
                 "call": f"{request.method} {request.url.path}", "outcome": outcome}
        self.audit.append(entry)
        log.info("agent %s %s %s", role, entry["call"], outcome)

    def require(self, need: str):
        def dependency(request: Request, x_agent_key: str | None = Header(default=None)) -> str:
            if not (self.settings.agent_key_read or self.settings.agent_key_ops):
                raise HTTPException(status_code=503, detail="Agent access isn't turned on.")
            role = self.role_for(x_agent_key)
            if role is None:
                self.record("unknown", request, "denied")
                raise HTTPException(status_code=401, detail="Unauthorized")
            if need == "ops" and role != "ops":
                self.record(role, request, "denied: needs the ops key")
                raise HTTPException(status_code=403, detail="This needs the ops key.")
            now = time.time()
            hits = self.hits[role]
            while hits and now - hits[0] > 60:
                hits.popleft()
            if len(hits) >= RATE_LIMIT:
                self.record(role, request, "rate limited")
                raise HTTPException(status_code=429, detail="Too many calls. Slow down.")
            hits.append(now)
            self.record(role, request)
            return role
        return dependency


def register_agent_api(app: FastAPI, settings: Settings, build: dict | None = None):
    gate = Gate(settings)
    read, ops = Depends(gate.require("read")), Depends(gate.require("ops"))

    def repo(request: Request):
        return request.app.state.repo

    @app.get("/api/agent/health")
    def health(role: str = read, request: Request = None):
        s = request.app.state
        return {"ok": True, "now": local_now(settings).isoformat(), "business": settings.business_name,
                "features": {"card_payments": s.stripe is not None, "texting": s.sms is not None,
                             "visit_notifications": push.keys_status(settings) == "ok",
                             "notification_keys": push.keys_status(settings), "dispatch_assistant": settings.agent_enabled},
                "your_access": role}

    @app.get("/api/agent/day/{day}")
    def day_summary(day: date, include_addresses: bool = False, role: str = read, request: Request = None):
        r = repo(request)
        jobs = r.list_jobs(day)
        route = r.get_route(day)
        live = [j for j in jobs if j["status"] != "cancelled"]
        paid = [j for j in live if j["payment_status"] == "paid"]
        stops = {s["job_id"]: s for s in (route["stops"] if route else [])}
        bookings = []
        for j in live:
            row = {"services": order_label(j["service"], j.get("add_ons")), "zone": j.get("zone_key"),
                   "lawn_sqft": j.get("lawn_sqft"), "package": j.get("package"), "status": j["status"],
                   "payment_status": j["payment_status"], "route_stop": (stops.get(j["job_id"]) or {}).get("sequence")}
            if include_addresses and role == "ops":
                row["address"] = j["address"]
            bookings.append(row)
        bookings.sort(key=lambda b: (b["route_stop"] is None, b["route_stop"] or 0))
        return {
            "date": day.isoformat(),
            "totals": {"bookings": len(live), "completed": sum(1 for j in live if j["status"] == "completed"),
                       "expected": round(sum(j["amount_due"] or 0 for j in live), 2),
                       "collected": round(sum(j["amount_paid"] or 0 for j in paid), 2),
                       "unpaid": round(sum(j["amount_due"] or 0 for j in live if j["payment_status"] == "unpaid"), 2),
                       "quoted_on_site": sum(1 for j in live if j["amount_due"] is None)},
            "route": {"built": route is not None, "stops": len(stops),
                      "finished": sum(1 for s in stops.values() if s["completed_at"]),
                      "drive_minutes": round(route["total_duration_s"] / 60) if route else 0,
                      "bookings_not_on_route": sum(1 for j in live if j["job_id"] not in stops
                                                   and j["status"] in ("pending", "scheduled"))},
            "bookings": bookings,
        }

    @app.get("/api/agent/outlook")
    def outlook(days: int = 7, role: str = read, request: Request = None):
        days = max(1, min(days, 31))
        start = local_now(settings).date()
        rows = repo(request).list_jobs_between(start, start + timedelta(days=days - 1))
        out = []
        for i in range(days):
            d = (start + timedelta(days=i)).isoformat()
            day_rows = [x for x in rows if str(x["scheduled_date"]) == d]
            out.append({"date": d, "bookings": len(day_rows), "quota": settings.daily_job_quota,
                        "expected": round(sum(float(x["amount_due"] or 0) for x in day_rows), 2)})
        return {"days": out}

    @app.get("/api/agent/manifest")
    def manifest(role: str = read, request: Request = None):
        return build_manifest(settings, request.app.state, ENDPOINTS, build or {}, CLIENT_MIN_VERSION, API_VERSION)

    @app.get("/api/agent/audit")
    def audit(role: str = read):
        return {"entries": list(gate.audit)[-100:], "rate_limit_per_minute": RATE_LIMIT}

    def not_paused():
        if settings.agent_actions_paused:
            raise HTTPException(status_code=403, detail="Agent actions are paused by the owner (AGENT_ACTIONS_PAUSED).")

    @app.post("/api/agent/routes/{day}/stops/{sequence}/on-the-way")
    def notify_stop_on_the_way(day: date, sequence: int, role: str = ops, request: Request = None):
        """The site tells the next customer the crew is on the way. Agents trigger it; they never write the
        message and never see the phone number. Guarded so it can only be true:
        today's visit, the next unfinished stop, close to its arrival time, and not in quiet hours."""
        not_paused()
        r = repo(request)
        now = local_now(settings)
        if day != now.date():
            raise HTTPException(status_code=409, detail="Customers are only told 'on the way' on the day of their visit.")
        if not (QUIET_BEFORE <= now.hour < QUIET_AFTER):
            raise HTTPException(status_code=409, detail="Quiet hours: customers aren't notified before 6 AM or after 8 PM.")
        route = r.get_route(day)
        stop = next((s for s in (route["stops"] if route else []) if s["sequence"] == sequence), None)
        if stop is None:
            raise HTTPException(status_code=404, detail="There is no such stop on that day's route.")
        if stop["completed_at"]:
            raise HTTPException(status_code=409, detail="That job is already done.")
        if sequence != min(s["sequence"] for s in route["stops"] if not s["completed_at"]):
            raise HTTPException(status_code=409, detail="That isn't the next stop on the route.")
        eta = _as_dt(stop.get("eta"), settings)
        if eta is not None and now < eta - timedelta(minutes=EARLY_MINUTES):
            raise HTTPException(status_code=409, detail=f"Too early: the crew isn't due there until about "
                                f"{eta.strftime('%I:%M %p').lstrip('0')}. Try again within {EARLY_MINUTES} minutes of that.")
        result = notify_stop(r, settings, r.get_stop(stop["stop_id"]), request.app.state.sms, None, text=True)
        # Only safe facts go back to the agent: never the message text, the name or the phone number.
        return {"notified": bool(result.get("notified") or result.get("pushed")), "texted": bool(result.get("notified")),
                "pushed": result.get("pushed", 0), "reason": result.get("reason")}

    @app.post("/api/agent/routes/{day}/build")
    def build_route(day: date, role: str = ops, request: Request = None):
        not_paused()
        r = repo(request)
        if day < local_now(settings).date():
            raise HTTPException(status_code=409, detail="That day has already passed.")
        existing = r.get_route(day)
        if existing and any(s["completed_at"] for s in existing["stops"]):
            raise HTTPException(status_code=409, detail="Some stops on this route are already finished, so it can't be rebuilt.")
        if not r.list_routable_jobs(day):
            raise HTTPException(status_code=409, detail="There are no bookings to route for that day.")
        summary = run_nightly(r, settings, day)
        return {"built": True, "date": day.isoformat(), "stops": summary.get("stops")}
