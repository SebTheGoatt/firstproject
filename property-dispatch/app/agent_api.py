"""A safe door for your AI agents (StarNet) to watch and help run the site.

Agents never get your owner code. They get their own keys, which you can change or turn off in Render at any time:

    AGENT_KEY_READ   can look: site health, a day's numbers, the week ahead, the audit log
    AGENT_KEY_OPS    can look, and also build/rebuild a day's route (the same safe action the owner button does)

Endpoints (header  X-Agent-Key: <key>):
    GET  /api/agent/health
    GET  /api/agent/day/{date}                 counts, money totals, route status, bookings without names/phones/codes
    GET  /api/agent/outlook?days=7
    GET  /api/agent/audit                      the last 100 things any agent did
    POST /api/agent/routes/{date}/build        (ops key only)

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

from .booking import local_now
from .config import Settings
from .models import order_label
from .nightly import run_nightly

log = logging.getLogger("agent_api")

RATE_LIMIT = 120          # calls per minute per key
AUDIT_SIZE = 200


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


def register_agent_api(app: FastAPI, settings: Settings):
    gate = Gate(settings)
    read, ops = Depends(gate.require("read")), Depends(gate.require("ops"))

    def repo(request: Request):
        return request.app.state.repo

    @app.get("/api/agent/health")
    def health(role: str = read, request: Request = None):
        s = request.app.state
        return {"ok": True, "now": local_now(settings).isoformat(), "business": settings.business_name,
                "features": {"card_payments": s.stripe is not None, "texting": s.sms is not None,
                             "visit_notifications": settings.push_enabled, "dispatch_assistant": settings.agent_enabled},
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

    @app.get("/api/agent/audit")
    def audit(role: str = read):
        return {"entries": list(gate.audit)[-100:], "rate_limit_per_minute": RATE_LIMIT}

    @app.post("/api/agent/routes/{day}/build")
    def build_route(day: date, role: str = ops, request: Request = None):
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
