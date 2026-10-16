"""Customer visit page (access code) and the owner's dashboard.

Customer, with the access code from their booking confirmation:
    GET  /api/visit/{code}                 status, arrival time, crew, payment, photos
    GET  /media/visit/{photo_id}?code=...  a before/after photo (only with that visit's code)

Crew:
    POST /api/stops/{stop_id}/photos       add a before or after photo to a job

Owner:
    GET  /api/owner/day/{date}             every booking that day (before or after the route
                                           is built), money totals, route status
    GET  /api/owner/outlook?days=7         bookings and expected revenue per day
    POST /api/owner/routes/{date}/build    build (or rebuild) that day's route now
"""

import re
import secrets
from datetime import date, timedelta
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .booking import local_now
from .charity import describe as describe_charities, ledger
from .pricing import PACKAGES
from .config import Settings
from .crew_auth import CrewIdentity
from .crew_routes import photo_url
from .media import MediaError, normalize_photo, parse_photo
from .models import SERVICE_LABELS, Service, order_label
from .nightly import run_nightly

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L look-alikes
CODE_LEN = 8


def new_access_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))


def normalize_code(raw: str) -> str | None:
    """'k7mx-3qpa' → 'K7MX3QPA'. Returns None if it can't be a code."""
    code = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
    return code if len(code) == CODE_LEN and all(c in CODE_ALPHABET for c in code) else None


def format_code(code: str | None) -> str | None:
    return f"{code[:4]}-{code[4:]}" if code else None


class JobPhotoBody(BaseModel):
    kind: Literal["before", "after"]
    photo: str = Field(max_length=1_000_000)


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200, pattern=r"^[A-Za-z0-9_\-=+/]+$")
    auth: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_\-=+/]+$")


class PushSubscriptionBody(BaseModel):
    """What the browser gives us from pushManager.subscribe(), plus the visitor's language."""
    endpoint: str = Field(min_length=20, max_length=1000, pattern=r"^https://")
    keys: PushKeys
    lang: Literal["en", "es"] = "en"


class Throttle:
    """Per-IP request budget, to make guessing access codes impractical."""

    def __init__(self, limit: int, window_s: int):
        import time

        self._time = time.time
        self.limit, self.window_s = limit, window_s
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = self._time()
        hits = [t for t in self._hits.get(key, []) if now - t < self.window_s]
        ok = len(hits) < self.limit
        if ok:
            hits.append(now)
        self._hits[key] = hits
        return ok


def register_visit_routes(app: FastAPI, settings: Settings, crew_auth):
    visit_throttle = Throttle(limit=30, window_s=600)

    def repo(request: Request):
        return request.app.state.repo

    def owner(who: CrewIdentity = Depends(crew_auth)) -> CrewIdentity:
        if not who.is_owner:
            raise HTTPException(status_code=403, detail="Only the owner can see the dashboard.")
        return who

    # ---------- Customer visit page ----------
    @app.get("/api/visit/{raw_code}")
    def visit(raw_code: str, request: Request, r=Depends(repo)):
        if not visit_throttle.allow(request.client.host if request.client else "unknown"):
            raise HTTPException(status_code=429, detail="Too many tries. Please wait a few minutes.")
        code = normalize_code(raw_code)
        v = r.get_visit(code) if code else None
        if v is None:
            raise HTTPException(status_code=404, detail="We couldn't find that code. Check it and try again.")
        member = v["crew_member"]
        return {
            "business_name": settings.business_name,
            "access_code": format_code(code),
            "first_name": v["first_name"],
            "address": v["address"],
            "service_label": order_label(v["service"], v.get("add_ons")),
            "scheduled_date": v["scheduled_date"],
            "status": v["status"],                    # pending | scheduled | completed | cancelled
            "eta": v["eta"],
            "on_the_way_at": v["on_the_way_at"],
            "completed_at": v["completed_at"],
            "timezone": settings.business_timezone,
            "payment": {
                "method": v["payment_method"], "status": v["payment_status"],
                "amount_due": v["amount_due"], "amount_paid": v["amount_paid"], "donation": v["donation"],
                "subtotal": v.get("subtotal"), "tax": v.get("tax_amount"), "tax_rate": v.get("tax_rate"),
                "lawn_sqft": v.get("lawn_sqft"), "sqft_rate": v.get("sqft_rate"),
                "package": v.get("package"), "package_label": PACKAGES[v["package"]]["label"] if v.get("package") in PACKAGES else None,
                "charity_rate": v.get("charity_rate"), "charity_amount": v.get("charity_amount"),
                "add_ons": v.get("add_ons") or [], "add_on_total": v.get("add_on_total") or 0.0,
                "giving_ledger": ledger(settings, v.get("giving_split")) if v.get("giving_split") else [],
                "donation_ledger": ledger(settings, v.get("donation_split")) if v.get("donation_split") else [],
                "pay_url": f"/pay/{v['pay_token']}" if v["pay_token"] and v["payment_status"] == "unpaid" else None,
            },
            "crew_member": {
                "display_name": member["display_name"], "role_title": member.get("role_title"),
                "service_branch": member.get("service_branch"), "photo_url": photo_url(member),
                "slug": member["slug"], "accent_color": member.get("accent_color"),
            } if member else None,
            "photos": [{"id": p["id"], "kind": p["kind"], "created_at": p["created_at"],
                        "url": f"/media/visit/{p['id']}?code={code}"} for p in v["photos"]],
        }

    @app.get("/api/push-config")
    def push_config():
        """The public key phones need to subscribe; null while notifications are turned off."""
        return {"public_key": settings.vapid_public_key if settings.push_enabled else None}

    @app.post("/api/visit/{raw_code}/push", status_code=204)
    def save_push(raw_code: str, body: PushSubscriptionBody, request: Request, r=Depends(repo)):
        """This phone wants "on the way" and "done" updates for this one booking (needs its access code)."""
        if not visit_throttle.allow(request.client.host if request.client else "unknown"):
            raise HTTPException(status_code=429, detail="Too many tries. Please wait a few minutes.")
        if not settings.push_enabled:
            raise HTTPException(status_code=503, detail="Notifications aren't turned on yet.")
        code = normalize_code(raw_code)
        v = r.get_visit(code) if code else None
        if v is None:
            raise HTTPException(status_code=404, detail="We couldn't find that code.")
        r.save_push_subscription(v["job_id"], body.endpoint, body.keys.p256dh, body.keys.auth, body.lang,
                                 f"/visit/{code}")
        return Response(status_code=204)

    @app.get("/media/visit/{photo_id}", include_in_schema=False)
    def visit_photo(photo_id: str, code: str = "", r=Depends(repo)):
        norm = normalize_code(code)
        p = r.job_photo(photo_id) if norm else None
        v = r.get_visit(norm) if p else None
        if not p or not v or v["job_id"] != p["job_id"]:
            raise HTTPException(status_code=404, detail="No photo")
        try:
            content_type, raw = parse_photo(p["photo"])
        except MediaError:
            raise HTTPException(status_code=404, detail="No photo")
        return Response(raw, media_type=content_type,
                        headers={"Cache-Control": "private, max-age=86400", "Referrer-Policy": "no-referrer"})

    # ---------- Crew: before/after photos ----------
    @app.post("/api/stops/{stop_id}/photos", status_code=201)
    def add_stop_photo(stop_id: str, body: JobPhotoBody, who: CrewIdentity = Depends(crew_auth), r=Depends(repo)):
        stop = r.get_stop(stop_id)
        if stop is None:
            raise HTTPException(status_code=404, detail="Stop not found")
        try:
            photo = normalize_photo(body.photo)
        except MediaError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return r.add_job_photo(stop["job_id"], who.member_id, body.kind, photo)

    # ---------- Owner dashboard ----------
    def totals(jobs: list[dict]) -> dict:
        paid = [j for j in jobs if j["payment_status"] == "paid"]
        unpaid = [j for j in jobs if j["payment_status"] == "unpaid"]
        return {
            "jobs": len(jobs),
            "done": sum(1 for j in jobs if j["status"] == "completed"),
            "expected": round(sum(j["amount_due"] or 0 for j in jobs), 2),
            "collected": round(sum(j["amount_paid"] or 0 for j in paid), 2),
            "donations": round(sum(j["donation"] or 0 for j in paid), 2),
            "unpaid": round(sum(j["amount_due"] or 0 for j in unpaid), 2),
            "quoted_on_site": sum(1 for j in jobs if j["amount_due"] is None),
            # Sales tax actually collected (paid jobs), for the owner's Texas sales-tax filing.
            "sales_tax": round(sum(j.get("tax_amount") or 0 for j in paid), 2),
            # Package giving (part of each paid price) — owed to charity like donations.
            "charity_giving": round(sum(j.get("charity_amount") or 0 for j in paid), 2),
            # What to pass on, per cause: package giving + voluntary donations, from each job's saved splits.
            "donations_by_charity": [
                {**c, "amount": round(sum(float((j.get("giving_split") or {}).get(c["key"], 0))
                                          + float((j.get("donation_split") or {}).get(c["key"], 0)) for j in paid), 2)}
                for c in describe_charities(settings)],
        }

    @app.get("/api/owner/day/{day}", dependencies=[Depends(owner)])
    def owner_day(day: date, r=Depends(repo)):
        jobs = r.list_jobs(day)
        for j in jobs:
            j["access_code"] = format_code(j["access_code"])
            j["service_label"] = order_label(j["service"], j.get("add_ons"))
        route = r.get_route(day)
        now = local_now(settings)
        build_at = now.replace(hour=settings.freeze_hour, minute=0, second=0, microsecond=0)
        return {
            "date": day.isoformat(),
            "timezone": settings.business_timezone,
            "quota": settings.daily_job_quota,
            "totals": totals(jobs),
            "jobs": jobs,
            "route": {
                "built": route is not None,
                "stops": len(route["stops"]) if route else 0,
                "completed": sum(1 for s in route["stops"] if s["completed_at"]) if route else 0,
                "total_distance_m": route["total_distance_m"] if route else 0,
                "total_duration_s": route["total_duration_s"] if route else 0,
                "optimized_at": route.get("optimized_at") if route else None,
                # Bookings made after the route was built (e.g. added by the owner) aren't on it yet.
                "missing": sum(1 for j in jobs if j["sequence"] is None and j["status"] in ("pending", "scheduled")),
            },
            "auto_build": {"hour": settings.freeze_hour,
                           "at": (build_at - timedelta(days=1)).isoformat() if day > now.date() else None},
        }

    @app.get("/api/owner/outlook", dependencies=[Depends(owner)])
    def owner_outlook(days: int = 7, r=Depends(repo)):
        days = max(1, min(days, 31))
        start = local_now(settings).date()
        rows = r.list_jobs_between(start, start + timedelta(days=days - 1))
        out = []
        for i in range(days):
            d = start + timedelta(days=i)
            day_rows = [x for x in rows if str(x["scheduled_date"]) == d.isoformat()]
            out.append({
                "date": d.isoformat(), "jobs": len(day_rows), "quota": settings.daily_job_quota,
                "expected": round(sum(float(x["amount_due"] or 0) for x in day_rows), 2),
                "collected": round(sum(float(x["amount_paid"] or 0) for x in day_rows if x["payment_status"] == "paid"), 2),
            })
        return out

    @app.post("/api/owner/routes/{day}/build", dependencies=[Depends(owner)])
    def build_route(day: date, r=Depends(repo)):
        today = local_now(settings).date()
        if day < today:
            raise HTTPException(status_code=409, detail="That day has already passed.")
        existing = r.get_route(day)
        if existing and any(s["completed_at"] for s in existing["stops"]):
            raise HTTPException(status_code=409, detail=(
                "Some stops on this route are already finished, so it can't be rebuilt."))
        if not r.list_routable_jobs(day):
            raise HTTPException(status_code=409, detail="There are no bookings to route for that day.")
        return run_nightly(r, settings, day)
