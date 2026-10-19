"""Data access layer.

`SupabaseRepository` talks to Supabase PostgreSQL through PostgREST using the
service-role key. `MemoryRepository` implements the same interface in-process
for local demos (DATA_BACKEND=memory) and the test suite.

Stop records returned by `get_route` / `next_open_stop` are flat dicts:
    stop_id, route_id, job_id, sequence, leg_distance_m, leg_duration_s, eta,
    completed_at, notified_at, completed_by, completed_by_name,
    customer_name, phone, address, lat, lng, service,
    payment_method, payment_status, amount_due, donation, amount_paid, pay_token

Crew member records never include `passcode_hash` or `photo` unless a method
says so; photos are served separately so lists stay small.
"""

import secrets
import threading
import uuid
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any, Protocol

from .models import GeoPoint, Job, Service
from .pricing import scope_of

ACTIVE_STATUSES = ("pending", "scheduled")
DELETED_NAME, DELETED_ADDRESS = "Deleted customer", "Deleted at the customer's request"


def _anonymous_phone() -> str:
    """A placeholder that passes the E.164 check but can't be anyone's number (+999 is not a country code)."""
    return "+999" + "".join(secrets.choice("0123456789") for _ in range(10))
CREW_PUBLIC_FIELDS = ("id", "slug", "display_name", "role_title", "bio", "years_experience", "specialties",
                      "service_branch", "accent_color", "photo_updated_at", "active", "created_at")
PORTFOLIO_FIELDS = ("id", "member_id", "job_id", "service", "caption", "created_at")
PAYMENT_FIELDS = ("payment_method", "payment_status", "amount_due", "donation", "amount_paid", "pay_token",
                  "donation_split")
PRICE_FIELDS = ("subtotal", "tax_rate", "tax_amount", "lawn_sqft", "zone_key", "sqft_rate",
                "package", "charity_rate", "charity_amount", "giving_split", "add_ons", "add_on_total", "lang")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _money(v: Any) -> float | None:
    return None if v is None else round(float(v), 2)


def _price(j: dict) -> dict:
    """Price breakdown of a booking: amount_due (the total) = subtotal + tax_amount."""
    rate, per_sqft, giving = j.get("tax_rate"), j.get("sqft_rate"), j.get("charity_rate")
    return {"subtotal": _money(j.get("subtotal")), "tax_rate": float(rate) if rate is not None else None,
            "tax_amount": _money(j.get("tax_amount")), "lawn_sqft": j.get("lawn_sqft"), "zone_key": j.get("zone_key"),
            "sqft_rate": float(per_sqft) if per_sqft is not None else None,
            "package": j.get("package"), "charity_rate": float(giving) if giving is not None else None,
            "charity_amount": _money(j.get("charity_amount")), "giving_split": j.get("giving_split") or None,
            "add_ons": [{**a, "price": _money(a.get("price"))} for a in (j.get("add_ons") or [])],
            "add_on_total": _money(j.get("add_on_total")) or 0.0,
            "lang": j.get("lang") or "en",   # the customer's language, for their texts
            "donation_split": j.get("donation_split") or None}


def _owner_job(j: dict, cust: dict, stop: dict | None, crew_name: str | None) -> dict:
    """One booking as the owner dashboard shows it."""
    return {
        "job_id": j["id"], "customer_name": cust["name"], "phone": cust["phone"], "address": j["address"],
        "service": j["service"], "status": j["status"], "zone_key": j.get("zone_key"),
        "scheduled_date": str(j["scheduled_date"]), "created_at": j.get("created_at"),
        "payment_method": j["payment_method"], "payment_status": j["payment_status"],
        "amount_due": _money(j.get("amount_due")), "amount_paid": _money(j.get("amount_paid")),
        "donation": _money(j.get("donation")) or 0.0, "access_code": j.get("access_code"),
        "sequence": stop.get("sequence") if stop else None, "eta": stop.get("eta") if stop else None,
        "completed_at": stop.get("completed_at") if stop else None, "completed_by_name": crew_name,
        **_price(j),
    }


def _visit(j: dict, cust: dict, stop: dict | None, member: dict | None, photos: list[dict]) -> dict:
    """What a customer sees with their access code."""
    return {
        "job_id": j["id"], "first_name": cust["name"].split()[0], "address": j["address"],
        "service": j["service"], "status": j["status"], "scheduled_date": str(j["scheduled_date"]),
        "payment_method": j["payment_method"], "payment_status": j["payment_status"],
        "amount_due": _money(j.get("amount_due")), "amount_paid": _money(j.get("amount_paid")),
        "donation": _money(j.get("donation")) or 0.0, "pay_token": j.get("pay_token"),
        "eta": stop.get("eta") if stop else None, "on_the_way_at": stop.get("notified_at") if stop else None,
        "completed_at": stop.get("completed_at") if stop else None,
        "crew_member": member, "photos": photos,
        **_price(j),
    }


class Repository(Protocol):
    # Jobs & routes
    def count_active_jobs(self, day: date) -> int: ...
    def active_job_points(self, since: date) -> list[tuple[float, float]]: ...   # (lat, lng) of upcoming bookings
    def create_job(self, *, name: str, phone: str, address: str, geo: GeoPoint, service: Service,
                   scheduled_date: date, service_minutes: int, zone_key: str, quoted_price: float | None,
                   payment_method: str = "cash", pay_token: str | None = None,
                   access_code: str | None = None, amount_due: float | None = None,
                   lawn_sqft: int | None = None, subtotal: float | None = None,
                   tax_rate: float | None = None, tax_amount: float | None = None,
                   sqft_rate: float | None = None, package: str | None = None,
                   charity_rate: float | None = None, charity_amount: float | None = None,
                   giving_split: dict | None = None, add_ons: list | None = None,
                   add_on_total: float | None = None, lang: str = "en") -> dict: ...
    def list_routable_jobs(self, day: date) -> list[Job]: ...
    def save_route(self, *, day: date, start: tuple[float, float], end: tuple[float, float],
                   total_distance_m: int, total_duration_s: int, matrix_source: str,
                   stops: list[dict]) -> str: ...
    def get_route(self, day: date) -> dict | None: ...
    def get_stop(self, stop_id: str) -> dict | None: ...
    def complete_stop(self, stop_id: str, member_id: str | None = None) -> tuple[dict, bool] | None: ...
    def stop_id_for_job(self, job_id: str) -> str | None: ...
    def next_open_stop(self, route_id: str, after_sequence: int) -> dict | None: ...
    def resequence_stops(self, route_id: str, updates: list[dict]) -> None: ...
    def recent_lawn_sizes(self, zone_key: str, limit: int = 50) -> list[int]: ...
    def set_stop_note(self, stop_id: str, note: str | None) -> None: ...
    def stop_notes(self, route_id: str) -> dict[str, str]: ...
    def claim_notification(self, stop_id: str) -> bool: ...
    # Google review follow-up (app/reviews.py)
    def jobs_due_review(self, since: datetime, until: datetime) -> list[dict]: ...
    def mark_review_requested(self, job_id: str) -> bool: ...
    def jobs_completed_between(self, since: datetime, until: datetime) -> list[dict]: ...
    def release_notification(self, stop_id: str) -> None: ...
    # Payments
    def get_payment(self, pay_token: str) -> dict | None: ...
    def set_price(self, job_id: str, *, subtotal: float, tax_amount: float, total: float,
                  lawn_sqft: int | None = None, charity_amount: float | None = None,
                  giving_split: dict | None = None) -> None: ...
    def record_checkout(self, job_id: str, session_id: str) -> None: ...
    def mark_paid(self, job_id: str, *, method: str, amount_paid: float, donation: float,
                  donation_split: dict | None = None) -> bool: ...
    # Crew
    def list_crew(self, include_inactive: bool = False) -> list[dict]: ...
    def get_crew(self, member_id: str, *, with_secret: bool = False) -> dict | None: ...
    def get_crew_by_slug(self, slug: str) -> dict | None: ...
    def create_crew(self, fields: dict) -> dict: ...
    def update_crew(self, member_id: str, fields: dict) -> dict | None: ...
    def crew_photo(self, member_id: str) -> str | None: ...
    def crew_stats(self, member_id: str, since: datetime) -> dict: ...
    def add_portfolio(self, member_id: str, *, photo: str, caption: str | None, service: str | None,
                      job_id: str | None) -> dict: ...
    def list_portfolio(self, member_id: str, limit: int = 60) -> list[dict]: ...
    def portfolio_photo(self, item_id: str) -> str | None: ...
    def delete_portfolio(self, item_id: str, member_id: str) -> bool: ...
    # Owner dashboard + customer visit page
    def list_jobs(self, day: date) -> list[dict]: ...
    def list_jobs_between(self, start: date, end: date) -> list[dict]: ...
    def get_visit(self, access_code: str) -> dict | None: ...
    def forget_customer(self, access_code: str) -> str: ...   # "deleted" | "upcoming" | "not_found"
    def count_customers_named(self, prefix: str) -> int: ...  # test data check before going live
    # Changes to a booking: cancel, move to another day (rain days). Both take it off any built route.
    def job_brief(self, job_id: str) -> dict | None: ...
    def cancel_job(self, job_id: str) -> bool: ...
    def move_job(self, job_id: str, day: date) -> bool: ...
    def add_job_photo(self, job_id: str, member_id: str | None, kind: str, photo: str) -> dict: ...
    def list_job_photos(self, job_id: str) -> list[dict]: ...
    def job_photo(self, photo_id: str) -> dict | None: ...
    # Push notification subscriptions (one per phone/browser that opted in on a visit page)
    def save_push_subscription(self, job_id: str, endpoint: str, p256dh: str, auth: str,
                               lang: str, visit_path: str) -> None: ...
    def list_push_subscriptions(self, job_id: str) -> list[dict]: ...
    def delete_push_subscription(self, endpoint: str) -> None: ...


# ======================================================================
#  Supabase
# ======================================================================
class SupabaseRepository:
    STOP_SELECT = (
        "id, route_id, job_id, sequence, leg_distance_m, leg_duration_s, eta, completed_at, notified_at,"
        " completed_by, crew_members(display_name),"
        " jobs(address, formatted_address, lat, lng, service, service_minutes, " + ", ".join(PAYMENT_FIELDS + PRICE_FIELDS) + ","
        " customers(name, phone))"
    )

    def __init__(self, url: str, key: str):
        from supabase import create_client  # imported lazily so tests don't need credentials

        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        self.sb = create_client(url, key)

    @staticmethod
    def _flatten_stop(row: dict) -> dict:
        job = row["jobs"]
        cust = job["customers"]
        member = row.get("crew_members") or {}
        return {
            "stop_id": row["id"],
            "route_id": row["route_id"],
            "job_id": row["job_id"],
            "sequence": row["sequence"],
            "leg_distance_m": row["leg_distance_m"],
            "leg_duration_s": row["leg_duration_s"],
            "eta": row["eta"],
            "completed_at": row["completed_at"],
            "notified_at": row["notified_at"],
            "completed_by": row.get("completed_by"),
            "completed_by_name": member.get("display_name"),
            "customer_name": cust["name"],
            "phone": cust["phone"],
            "address": job["address"],
            "lat": job["lat"],
            "lng": job["lng"],
            "service": job["service"],
            "service_minutes": job.get("service_minutes"),
            "payment_method": job["payment_method"],
            "payment_status": job["payment_status"],
            "amount_due": _money(job["amount_due"]),
            "donation": _money(job["donation"]) or 0.0,
            "amount_paid": _money(job["amount_paid"]),
            "pay_token": job["pay_token"],
            **_price(job),
        }

    def count_active_jobs(self, day: date) -> int:
        res = (
            self.sb.table("jobs").select("id", count="exact", head=True)
            .eq("scheduled_date", day.isoformat()).in_("status", list(ACTIVE_STATUSES)).execute()
        )
        return res.count or 0

    def active_job_points(self, since: date) -> list[tuple[float, float]]:
        rows = (self.sb.table("jobs").select("lat, lng").gte("scheduled_date", since.isoformat())
                .in_("status", list(ACTIVE_STATUSES)).execute()).data
        return [(r["lat"], r["lng"]) for r in rows]

    def create_job(self, *, name, phone, address, geo, service, scheduled_date, service_minutes,
                   zone_key, quoted_price, payment_method="cash", pay_token=None, access_code=None,
                   amount_due=None, lawn_sqft=None, subtotal=None, tax_rate=None, tax_amount=None,
                   sqft_rate=None, package=None, charity_rate=None, charity_amount=None,
                   giving_split=None, add_ons=None, add_on_total=None, lang="en") -> dict:
        cust = (
            self.sb.table("customers")
            .upsert({"name": name, "phone": phone}, on_conflict="phone").execute()
        ).data[0]
        job = self.sb.table("jobs").insert({
            "customer_id": cust["id"],
            "address": address,
            "formatted_address": geo.formatted_address,
            "lat": geo.lat,
            "lng": geo.lng,
            "service": Service(service).value,
            "scheduled_date": scheduled_date.isoformat(),
            "service_minutes": service_minutes,
            "zone_key": zone_key,
            "quoted_price": quoted_price,
            "amount_due": amount_due if amount_due is not None else quoted_price,
            "lawn_sqft": lawn_sqft, "subtotal": subtotal, "tax_rate": tax_rate, "tax_amount": tax_amount,
            "sqft_rate": sqft_rate, "package": package, "charity_rate": charity_rate,
            "charity_amount": charity_amount, "giving_split": giving_split or None,
            "add_ons": add_ons or [], "add_on_total": add_on_total or 0, "lang": lang,
            "payment_method": payment_method,
            "pay_token": pay_token,
            "access_code": access_code,
        }).execute().data[0]
        return job

    def list_routable_jobs(self, day: date) -> list[Job]:
        rows = (
            self.sb.table("jobs")
            .select("id, address, formatted_address, lat, lng, service, service_minutes, status, customers(name, phone)")
            .eq("scheduled_date", day.isoformat()).in_("status", list(ACTIVE_STATUSES))
            .order("created_at").execute()
        ).data
        return [
            Job(id=r["id"], customer_name=r["customers"]["name"], phone=r["customers"]["phone"],
                address=r["address"], lat=r["lat"], lng=r["lng"],
                service=r["service"], service_minutes=r["service_minutes"], status=r["status"])
            for r in rows
        ]

    def save_route(self, *, day, start, end, total_distance_m, total_duration_s, matrix_source, stops) -> str:
        res = self.sb.rpc("save_route", {
            "p_route_date": day.isoformat(),
            "p_start_lat": start[0], "p_start_lng": start[1],
            "p_end_lat": end[0], "p_end_lng": end[1],
            "p_total_distance_m": total_distance_m,
            "p_total_duration_s": total_duration_s,
            "p_matrix_source": matrix_source,
            "p_stops": stops,
        }).execute()
        return res.data

    def get_route(self, day: date) -> dict | None:
        routes = self.sb.table("routes").select("*").eq("route_date", day.isoformat()).limit(1).execute().data
        if not routes:
            return None
        route = routes[0]
        rows = (
            self.sb.table("route_stops").select(self.STOP_SELECT)
            .eq("route_id", route["id"]).order("sequence").execute()
        ).data
        route["stops"] = [self._flatten_stop(r) for r in rows]
        return route

    def get_stop(self, stop_id: str) -> dict | None:
        rows = self.sb.table("route_stops").select(self.STOP_SELECT).eq("id", stop_id).limit(1).execute().data
        return self._flatten_stop(rows[0]) if rows else None

    def complete_stop(self, stop_id: str, member_id: str | None = None) -> tuple[dict, bool] | None:
        now = _now_iso()
        # Conditional update → only the first caller "wins"; retries are no-ops.
        updated = (
            self.sb.table("route_stops").update({"completed_at": now, "completed_by": member_id})
            .eq("id", stop_id).is_("completed_at", "null").execute()
        ).data
        newly = bool(updated)
        stop = self.get_stop(stop_id)
        if stop is None:
            return None
        if newly:
            self.sb.table("jobs").update({"status": "completed", "completed_at": now}).eq("id", stop["job_id"]).execute()
        return stop, newly

    def stop_id_for_job(self, job_id: str) -> str | None:
        rows = self.sb.table("route_stops").select("id").eq("job_id", job_id).limit(1).execute().data
        return rows[0]["id"] if rows else None

    def resequence_stops(self, route_id: str, updates: list[dict]) -> None:
        # (route_id, sequence) is unique, so park every stop on a high number first, then set the new order.
        for u in updates:
            self.sb.table("route_stops").update({"sequence": u["sequence"] + 10_000}) \
                .eq("id", u["stop_id"]).eq("route_id", route_id).execute()
        for u in updates:
            self.sb.table("route_stops").update({
                "sequence": u["sequence"], "leg_distance_m": u["leg_distance_m"],
                "leg_duration_s": u["leg_duration_s"], "eta": u["eta"],
            }).eq("id", u["stop_id"]).eq("route_id", route_id).execute()
        self.sb.table("routes").update({"optimized_at": _now_iso()}).eq("id", route_id).execute()

    def recent_lawn_sizes(self, zone_key: str, limit: int = 50) -> list[int]:
        """Crew-measured lawn sizes of finished jobs in an area, newest first (for the booking estimate).
        Price-locked bookings (yard / full property) are left out: their size was set at booking, not measured."""
        rows = (self.sb.table("jobs").select("lawn_sqft, add_ons").eq("zone_key", zone_key).eq("status", "completed")
                .not_.is_("lawn_sqft", "null").order("completed_at", desc=True).limit(limit * 2).execute().data)
        return [r["lawn_sqft"] for r in rows if not scope_of(r.get("add_ons"))][:limit]

    def set_stop_note(self, stop_id: str, note: str | None) -> None:
        # Needs supabase/migrations/20261026000000_crew_notes.sql (route_stops.crew_note).
        self.sb.table("route_stops").update({"crew_note": note}).eq("id", stop_id).execute()

    def stop_notes(self, route_id: str) -> dict[str, str]:
        rows = self.sb.table("route_stops").select("id, crew_note").eq("route_id", route_id).execute().data
        return {r["id"]: r["crew_note"] for r in rows if r.get("crew_note")}

    def next_open_stop(self, route_id: str, after_sequence: int) -> dict | None:
        rows = (
            self.sb.table("route_stops").select(self.STOP_SELECT)
            .eq("route_id", route_id).gt("sequence", after_sequence).is_("completed_at", "null")
            .order("sequence").limit(1).execute()
        ).data
        return self._flatten_stop(rows[0]) if rows else None

    def claim_notification(self, stop_id: str) -> bool:
        rows = (
            self.sb.table("route_stops").update({"notified_at": _now_iso()})
            .eq("id", stop_id).is_("notified_at", "null").execute()
        ).data
        return bool(rows)

    REVIEW_SELECT = "id, access_code, lang, completed_at, customers(name, phone)"

    @staticmethod
    def _review_rows(rows: list[dict]) -> list[dict]:
        return [{"id": r["id"], "access_code": r.get("access_code"), "lang": r.get("lang") or "en",
                 "completed_at": r.get("completed_at"), "customer_name": r["customers"]["name"],
                 "phone": r["customers"]["phone"]} for r in rows]

    def _completed(self, since: datetime, until: datetime):
        return (self.sb.table("jobs").select(self.REVIEW_SELECT).eq("status", "completed")
                .gte("completed_at", since.isoformat()).lte("completed_at", until.isoformat()))

    def jobs_due_review(self, since: datetime, until: datetime) -> list[dict]:
        # Fails if the review_requested_at column hasn't been added yet; app/reviews.py falls back.
        return self._review_rows(self._completed(since, until).is_("review_requested_at", "null").execute().data)

    def mark_review_requested(self, job_id: str) -> bool:
        rows = (self.sb.table("jobs").update({"review_requested_at": _now_iso()})
                .eq("id", job_id).is_("review_requested_at", "null").execute()).data
        return bool(rows)

    def jobs_completed_between(self, since: datetime, until: datetime) -> list[dict]:
        return self._review_rows(self._completed(since, until).execute().data)

    def release_notification(self, stop_id: str) -> None:
        self.sb.table("route_stops").update({"notified_at": None}).eq("id", stop_id).execute()

    # ---------- Payments ----------
    def get_payment(self, pay_token: str) -> dict | None:
        rows = (
            self.sb.table("jobs")
            .select("id, service, scheduled_date, address, status, paid_at, stripe_session_id, "
                    + ", ".join(PAYMENT_FIELDS + PRICE_FIELDS) + ", customers(name)")
            .eq("pay_token", pay_token).limit(1).execute()
        ).data
        if not rows:
            return None
        r = rows[0]
        return {
            "job_id": r["id"], "service": r["service"], "scheduled_date": r["scheduled_date"],
            "address": r["address"], "status": r["status"], "customer_name": r["customers"]["name"],
            "payment_method": r["payment_method"], "payment_status": r["payment_status"],
            "amount_due": _money(r["amount_due"]), "donation": _money(r["donation"]) or 0.0,
            "amount_paid": _money(r["amount_paid"]), "paid_at": r["paid_at"],
            "stripe_session_id": r["stripe_session_id"],
            **_price(r),
        }

    def set_price(self, job_id, *, subtotal, tax_amount, total, lawn_sqft=None,
                  charity_amount=None, giving_split=None) -> None:
        fields = {"subtotal": subtotal, "tax_amount": tax_amount, "amount_due": total}
        if lawn_sqft is not None:
            fields["lawn_sqft"] = lawn_sqft
        if charity_amount is not None:
            fields.update(charity_amount=charity_amount, giving_split=giving_split or None)
        self.sb.table("jobs").update(fields).eq("id", job_id).eq("payment_status", "unpaid").execute()

    def record_checkout(self, job_id: str, session_id: str) -> None:
        self.sb.table("jobs").update({"stripe_session_id": session_id}).eq("id", job_id).execute()

    def mark_paid(self, job_id: str, *, method: str, amount_paid: float, donation: float,
                  donation_split: dict | None = None) -> bool:
        rows = (
            self.sb.table("jobs").update({
                "payment_status": "paid", "payment_method": method, "amount_paid": amount_paid,
                "donation": donation, "donation_split": donation_split or None, "paid_at": _now_iso(),
            }).eq("id", job_id).eq("payment_status", "unpaid").execute()
        ).data
        return bool(rows)

    # ---------- Crew ----------
    def list_crew(self, include_inactive: bool = False) -> list[dict]:
        q = self.sb.table("crew_members").select(", ".join(CREW_PUBLIC_FIELDS)).order("created_at")
        if not include_inactive:
            q = q.eq("active", True)
        return q.execute().data

    def get_crew(self, member_id: str, *, with_secret: bool = False) -> dict | None:
        cols = ", ".join(CREW_PUBLIC_FIELDS) + (", passcode_hash" if with_secret else "")
        rows = self.sb.table("crew_members").select(cols).eq("id", member_id).limit(1).execute().data
        return rows[0] if rows else None

    def get_crew_by_slug(self, slug: str) -> dict | None:
        rows = (self.sb.table("crew_members").select(", ".join(CREW_PUBLIC_FIELDS))
                .eq("slug", slug).eq("active", True).limit(1).execute().data)
        return rows[0] if rows else None

    def create_crew(self, fields: dict) -> dict:
        row = self.sb.table("crew_members").insert(fields).execute().data[0]
        return {k: row.get(k) for k in CREW_PUBLIC_FIELDS}

    def update_crew(self, member_id: str, fields: dict) -> dict | None:
        rows = self.sb.table("crew_members").update(fields).eq("id", member_id).execute().data
        return {k: rows[0].get(k) for k in CREW_PUBLIC_FIELDS} if rows else None

    def crew_photo(self, member_id: str) -> str | None:
        rows = self.sb.table("crew_members").select("photo").eq("id", member_id).limit(1).execute().data
        return rows[0]["photo"] if rows else None

    def crew_stats(self, member_id: str, since: datetime) -> dict:
        def count(q):
            return q.execute().count or 0

        base = lambda: self.sb.table("route_stops").select("id", count="exact", head=True).eq("completed_by", member_id)  # noqa: E731
        return {
            "jobs_total": count(base()),
            "jobs_week": count(base().gte("completed_at", since.isoformat())),
            "photos": count(self.sb.table("portfolio_items").select("id", count="exact", head=True)
                            .eq("member_id", member_id)),
        }

    def add_portfolio(self, member_id, *, photo, caption, service, job_id) -> dict:
        row = self.sb.table("portfolio_items").insert({
            "member_id": member_id, "photo": photo, "caption": caption, "service": service, "job_id": job_id,
        }).execute().data[0]
        return {k: row.get(k) for k in PORTFOLIO_FIELDS}

    def list_portfolio(self, member_id: str, limit: int = 60) -> list[dict]:
        return (self.sb.table("portfolio_items").select(", ".join(PORTFOLIO_FIELDS))
                .eq("member_id", member_id).order("created_at", desc=True).limit(limit).execute().data)

    def portfolio_photo(self, item_id: str) -> str | None:
        rows = self.sb.table("portfolio_items").select("photo").eq("id", item_id).limit(1).execute().data
        return rows[0]["photo"] if rows else None

    def delete_portfolio(self, item_id: str, member_id: str) -> bool:
        rows = self.sb.table("portfolio_items").delete().eq("id", item_id).eq("member_id", member_id).execute().data
        return bool(rows)

    # ---------- Owner dashboard + customer visit ----------
    JOB_COLS = ("id, address, service, status, zone_key, scheduled_date, created_at, payment_method, payment_status,"
                " amount_due, amount_paid, donation, access_code, pay_token, subtotal, tax_rate, tax_amount, lawn_sqft,"
                " sqft_rate, donation_split, package, charity_rate, charity_amount, giving_split, add_ons, add_on_total, lang")

    @staticmethod
    def _one(v):
        return (v[0] if v else None) if isinstance(v, list) else v

    def list_jobs(self, day: date) -> list[dict]:
        rows = (
            self.sb.table("jobs")
            .select(self.JOB_COLS + ", customers(name, phone),"
                    " route_stops(sequence, eta, completed_at, notified_at, crew_members(display_name))")
            .eq("scheduled_date", day.isoformat()).neq("status", "cancelled").order("created_at").execute()
        ).data
        out = []
        for r in rows:
            stop = self._one(r.get("route_stops"))
            member = self._one(stop.get("crew_members")) if stop else None
            out.append(_owner_job(r, r["customers"], stop, member["display_name"] if member else None))
        return sorted(out, key=lambda j: (j["sequence"] is None, j["sequence"] or 0, j["created_at"] or ""))

    def list_jobs_between(self, start: date, end: date) -> list[dict]:
        return (
            self.sb.table("jobs")
            .select("scheduled_date, status, payment_status, amount_due, amount_paid, donation, tax_amount")
            .gte("scheduled_date", start.isoformat()).lte("scheduled_date", end.isoformat())
            .neq("status", "cancelled").execute()
        ).data

    def count_customers_named(self, prefix: str) -> int:
        res = self.sb.table("customers").select("id", count="exact", head=True).like("name", f"{prefix}%").execute()
        return res.count or 0

    def forget_customer(self, access_code: str) -> str:
        """Erase a customer's personal details on request. Amounts, dates and services stay (tax records),
        with no name, phone, street address, photos, notes or links attached. Refused while a visit is still ahead."""
        rows = self.sb.table("jobs").select("customer_id").eq("access_code", access_code).limit(1).execute().data
        if not rows:
            return "not_found"
        cid = rows[0]["customer_id"]
        jobs = self.sb.table("jobs").select("id, status, lat, lng").eq("customer_id", cid).execute().data
        if any(j["status"] in ACTIVE_STATUSES for j in jobs):
            return "upcoming"
        ids = [j["id"] for j in jobs]
        self.sb.table("job_photos").delete().in_("job_id", ids).execute()
        self.sb.table("push_subscriptions").delete().in_("job_id", ids).execute()
        try:
            self.sb.table("route_stops").update({"crew_note": None}).in_("job_id", ids).execute()
        except Exception:      # crew_note column not added yet: nothing to clear
            pass
        for j in jobs:         # keep only the area (about a kilometer), never the house
            self.sb.table("jobs").update({"address": DELETED_ADDRESS, "formatted_address": None, "access_code": None,
                                          "pay_token": None, "lat": round(j["lat"], 2), "lng": round(j["lng"], 2)}
                                         ).eq("id", j["id"]).execute()
        self.sb.table("customers").update({"name": DELETED_NAME, "phone": _anonymous_phone()}).eq("id", cid).execute()
        return "deleted"

    BRIEF_SELECT = ("id, status, scheduled_date, zone_key, service, add_ons, payment_method, payment_status, amount_paid, amount_due, "
                    "stripe_session_id, access_code, lang, customers(name, phone), route_stops(id, notified_at, completed_at)")

    def job_brief(self, job_id: str) -> dict | None:
        rows = self.sb.table("jobs").select(self.BRIEF_SELECT).eq("id", job_id).limit(1).execute().data
        if not rows:
            return None
        r = rows[0]
        stop = self._one(r.pop("route_stops", None)) or {}
        cust = r.pop("customers")
        return {**r, "scheduled_date": date.fromisoformat(str(r["scheduled_date"])), "customer_name": cust["name"],
                "phone": cust["phone"], "notified_at": stop.get("notified_at"), "stop_completed_at": stop.get("completed_at")}

    def _drop_stop(self, job_id: str) -> None:
        """Take a job off its (unstarted) route and close the gap in the stop numbers."""
        for r in self.sb.table("route_stops").select("id, route_id").eq("job_id", job_id).execute().data:
            self.sb.table("route_stops").delete().eq("id", r["id"]).execute()
            rest = (self.sb.table("route_stops").select("id, leg_distance_m, leg_duration_s, eta")
                    .eq("route_id", r["route_id"]).order("sequence").execute().data)
            self.resequence_stops(r["route_id"], [{"stop_id": s["id"], "sequence": i, "leg_distance_m": s["leg_distance_m"],
                                                    "leg_duration_s": s["leg_duration_s"], "eta": s["eta"]}
                                                   for i, s in enumerate(rest, start=1)])

    def cancel_job(self, job_id: str) -> bool:
        rows = (self.sb.table("jobs").update({"status": "cancelled"}).eq("id", job_id)
                .in_("status", list(ACTIVE_STATUSES)).execute()).data
        if rows:
            self._drop_stop(job_id)
        return bool(rows)

    def move_job(self, job_id: str, day: date) -> bool:
        rows = (self.sb.table("jobs").update({"scheduled_date": day.isoformat(), "status": "pending", "frozen_at": None})
                .eq("id", job_id).in_("status", list(ACTIVE_STATUSES)).execute()).data
        if rows:
            self._drop_stop(job_id)
        return bool(rows)

    def get_visit(self, access_code: str) -> dict | None:
        rows = (
            self.sb.table("jobs")
            .select(self.JOB_COLS + ", customers(name),"
                    " route_stops(eta, completed_at, notified_at, completed_by)")
            .eq("access_code", access_code).limit(1).execute()
        ).data
        if not rows:
            return None
        r = rows[0]
        stop = self._one(r.get("route_stops"))
        member = self.get_crew(stop["completed_by"]) if stop and stop.get("completed_by") else None
        return _visit(r, r["customers"], stop, member, self.list_job_photos(r["id"]))

    def add_job_photo(self, job_id, member_id, kind, photo) -> dict:
        row = self.sb.table("job_photos").insert(
            {"job_id": job_id, "member_id": member_id, "kind": kind, "photo": photo}).execute().data[0]
        return {k: row[k] for k in ("id", "job_id", "kind", "created_at")}

    def list_job_photos(self, job_id: str) -> list[dict]:
        return (self.sb.table("job_photos").select("id, kind, created_at, member_id")
                .eq("job_id", job_id).order("created_at").execute().data)

    def job_photo(self, photo_id: str) -> dict | None:
        rows = self.sb.table("job_photos").select("id, job_id, photo").eq("id", photo_id).limit(1).execute().data
        return rows[0] if rows else None

    def save_push_subscription(self, job_id, endpoint, p256dh, auth, lang, visit_path) -> None:
        self.sb.table("push_subscriptions").upsert(
            {"job_id": job_id, "endpoint": endpoint, "p256dh": p256dh, "auth": auth, "lang": lang,
             "visit_path": visit_path}, on_conflict="endpoint").execute()

    def list_push_subscriptions(self, job_id: str) -> list[dict]:
        return (self.sb.table("push_subscriptions").select("endpoint, p256dh, auth, lang, visit_path")
                .eq("job_id", job_id).execute().data)

    def delete_push_subscription(self, endpoint: str) -> None:
        self.sb.table("push_subscriptions").delete().eq("endpoint", endpoint).execute()


# ======================================================================
#  In-memory (local demo + tests)
# ======================================================================
class MemoryRepository:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.customers: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self.routes: dict[str, dict] = {}
        self.stops: dict[str, dict] = {}
        self.crew: dict[str, dict] = {}
        self.portfolio: dict[str, dict] = {}
        self.job_photos: dict[str, dict] = {}
        self.push_subs: dict[str, dict] = {}     # endpoint → subscription

    def count_active_jobs(self, day: date) -> int:
        return sum(1 for j in self.jobs.values() if j["scheduled_date"] == day and j["status"] in ACTIVE_STATUSES)

    def active_job_points(self, since: date) -> list[tuple[float, float]]:
        return [(j["lat"], j["lng"]) for j in self.jobs.values()
                if j["status"] in ACTIVE_STATUSES and j["scheduled_date"] >= since]

    def create_job(self, *, name, phone, address, geo, service, scheduled_date, service_minutes,
                   zone_key, quoted_price, payment_method="cash", pay_token=None, access_code=None,
                   amount_due=None, lawn_sqft=None, subtotal=None, tax_rate=None, tax_amount=None,
                   sqft_rate=None, package=None, charity_rate=None, charity_amount=None,
                   giving_split=None, add_ons=None, add_on_total=None, lang="en") -> dict:
        with self._lock:
            cust = next((c for c in self.customers.values() if c["phone"] == phone), None)
            if cust is None:
                cust = {"id": str(uuid.uuid4()), "phone": phone}
                self.customers[cust["id"]] = cust
            cust["name"] = name
            job = {
                "id": str(uuid.uuid4()), "customer_id": cust["id"], "address": address,
                "formatted_address": geo.formatted_address, "lat": geo.lat, "lng": geo.lng,
                "service": Service(service).value, "scheduled_date": scheduled_date,
                "service_minutes": service_minutes, "status": "pending",
                "zone_key": zone_key, "quoted_price": quoted_price,
                "payment_method": payment_method, "payment_status": "unpaid",
                "amount_due": amount_due if amount_due is not None else quoted_price,
                "lawn_sqft": lawn_sqft, "subtotal": subtotal, "tax_rate": tax_rate, "tax_amount": tax_amount,
                "sqft_rate": sqft_rate, "donation_split": None, "package": package,
                "charity_rate": charity_rate, "charity_amount": charity_amount, "giving_split": giving_split or None,
                "add_ons": add_ons or [], "add_on_total": add_on_total or 0, "lang": lang,
                "donation": 0.0, "amount_paid": None, "paid_at": None, "pay_token": pay_token,
                "access_code": access_code,
                "stripe_session_id": None,
                "frozen_at": None, "completed_at": None, "review_requested_at": None, "created_at": _now_iso(),
            }
            self.jobs[job["id"]] = job
            return deepcopy(job)

    def list_routable_jobs(self, day: date) -> list[Job]:
        out = []
        for j in sorted(self.jobs.values(), key=lambda j: j["created_at"]):
            if j["scheduled_date"] == day and j["status"] in ACTIVE_STATUSES:
                c = self.customers[j["customer_id"]]
                out.append(Job(id=j["id"], customer_name=c["name"], phone=c["phone"],
                               address=j["address"], lat=j["lat"], lng=j["lng"],
                               service=j["service"], service_minutes=j["service_minutes"], status=j["status"]))
        return out

    def save_route(self, *, day, start, end, total_distance_m, total_duration_s, matrix_source, stops) -> str:
        with self._lock:
            for rid in [rid for rid, r in self.routes.items() if r["route_date"] == day]:
                del self.routes[rid]
                for sid in [sid for sid, s in self.stops.items() if s["route_id"] == rid]:
                    del self.stops[sid]
            rid = str(uuid.uuid4())
            self.routes[rid] = {
                "id": rid, "route_date": day, "start_lat": start[0], "start_lng": start[1],
                "end_lat": end[0], "end_lng": end[1], "total_distance_m": total_distance_m,
                "total_duration_s": total_duration_s, "matrix_source": matrix_source,
                "optimized_at": _now_iso(),
            }
            for s in stops:
                sid = str(uuid.uuid4())
                self.stops[sid] = {"id": sid, "route_id": rid, "completed_at": None, "notified_at": None,
                                   "completed_by": None, **s}
                job = self.jobs[s["job_id"]]
                if job["status"] == "pending":
                    job["status"] = "scheduled"
                    job["frozen_at"] = _now_iso()
            return rid

    def _flat(self, s: dict) -> dict:
        j = self.jobs[s["job_id"]]
        c = self.customers[j["customer_id"]]
        member = self.crew.get(s.get("completed_by") or "")
        return {
            "stop_id": s["id"], "route_id": s["route_id"], "job_id": s["job_id"], "sequence": s["sequence"],
            "leg_distance_m": s["leg_distance_m"], "leg_duration_s": s["leg_duration_s"], "eta": s["eta"],
            "completed_at": s["completed_at"], "notified_at": s["notified_at"],
            "completed_by": s.get("completed_by"), "completed_by_name": member["display_name"] if member else None,
            "customer_name": c["name"], "phone": c["phone"], "address": j["address"],
            "lat": j["lat"], "lng": j["lng"], "service": j["service"], "service_minutes": j.get("service_minutes"),
            **{k: j[k] for k in PAYMENT_FIELDS},
            **_price(j),
        }

    def get_route(self, day: date) -> dict | None:
        route = next((r for r in self.routes.values() if r["route_date"] == day), None)
        if route is None:
            return None
        route = deepcopy(route)
        stops = sorted((s for s in self.stops.values() if s["route_id"] == route["id"]), key=lambda s: s["sequence"])
        route["stops"] = [self._flat(s) for s in stops]
        return route

    def get_stop(self, stop_id: str) -> dict | None:
        s = self.stops.get(stop_id)
        return self._flat(s) if s else None

    def complete_stop(self, stop_id: str, member_id: str | None = None) -> tuple[dict, bool] | None:
        with self._lock:
            s = self.stops.get(stop_id)
            if s is None:
                return None
            newly = s["completed_at"] is None
            if newly:
                now = _now_iso()
                s["completed_at"], s["completed_by"] = now, member_id
                job = self.jobs[s["job_id"]]
                job["status"], job["completed_at"] = "completed", now
            return self._flat(s), newly

    def stop_id_for_job(self, job_id: str) -> str | None:
        return next((sid for sid, s in self.stops.items() if s["job_id"] == job_id), None)

    def resequence_stops(self, route_id: str, updates: list[dict]) -> None:
        with self._lock:
            for u in updates:
                st = self.stops[u["stop_id"]]
                assert st["route_id"] == route_id
                st.update(sequence=u["sequence"], leg_distance_m=u["leg_distance_m"],
                          leg_duration_s=u["leg_duration_s"], eta=u["eta"])
            self.routes[route_id]["optimized_at"] = _now_iso()

    def recent_lawn_sizes(self, zone_key: str, limit: int = 50) -> list[int]:
        done = [j for j in self.jobs.values() if j.get("zone_key") == zone_key and j["status"] == "completed" and j.get("lawn_sqft")
                and not scope_of(j.get("add_ons"))]
        done.sort(key=lambda j: str(j.get("completed_at") or ""), reverse=True)
        return [j["lawn_sqft"] for j in done[:limit]]

    def set_stop_note(self, stop_id: str, note: str | None) -> None:
        with self._lock:
            self.stops[stop_id]["crew_note"] = note

    def stop_notes(self, route_id: str) -> dict[str, str]:
        return {sid: st["crew_note"] for sid, st in self.stops.items()
                if st["route_id"] == route_id and st.get("crew_note")}

    def next_open_stop(self, route_id: str, after_sequence: int) -> dict | None:
        cands = [s for s in self.stops.values()
                 if s["route_id"] == route_id and s["sequence"] > after_sequence and s["completed_at"] is None]
        return self._flat(min(cands, key=lambda s: s["sequence"])) if cands else None

    def claim_notification(self, stop_id: str) -> bool:
        with self._lock:
            s = self.stops[stop_id]
            if s["notified_at"] is not None:
                return False
            s["notified_at"] = _now_iso()
            return True

    def _completed(self, since: datetime, until: datetime, unasked: bool = False) -> list[dict]:
        out = []
        for j in self.jobs.values():
            done = datetime.fromisoformat(j["completed_at"]) if j.get("completed_at") else None
            if j["status"] != "completed" or done is None or not since <= done <= until:
                continue
            if unasked and j.get("review_requested_at"):
                continue
            cust = self.customers[j["customer_id"]]
            out.append({"id": j["id"], "access_code": j.get("access_code"), "lang": j.get("lang") or "en",
                        "completed_at": j["completed_at"], "customer_name": cust["name"], "phone": cust["phone"]})
        return out

    def jobs_due_review(self, since: datetime, until: datetime) -> list[dict]:
        return self._completed(since, until, unasked=True)

    def mark_review_requested(self, job_id: str) -> bool:
        with self._lock:
            j = self.jobs[job_id]
            if j.get("review_requested_at"):
                return False
            j["review_requested_at"] = _now_iso()
            return True

    def jobs_completed_between(self, since: datetime, until: datetime) -> list[dict]:
        return self._completed(since, until)

    def release_notification(self, stop_id: str) -> None:
        self.stops[stop_id]["notified_at"] = None

    # ---------- Payments ----------
    def get_payment(self, pay_token: str) -> dict | None:
        j = next((j for j in self.jobs.values() if pay_token and j["pay_token"] == pay_token), None)
        if j is None:
            return None
        return {
            "job_id": j["id"], "service": j["service"], "scheduled_date": j["scheduled_date"],
            "address": j["address"], "status": j["status"], "customer_name": self.customers[j["customer_id"]]["name"],
            "paid_at": j["paid_at"], "stripe_session_id": j["stripe_session_id"],
            **{k: j.get(k) for k in PAYMENT_FIELDS if k != "pay_token"},
            **_price(j),
        }

    def set_price(self, job_id, *, subtotal, tax_amount, total, lawn_sqft=None,
                  charity_amount=None, giving_split=None) -> None:
        j = self.jobs[job_id]
        if j["payment_status"] == "unpaid":
            j.update(subtotal=subtotal, tax_amount=tax_amount, amount_due=total)
            if lawn_sqft is not None:
                j["lawn_sqft"] = lawn_sqft
            if charity_amount is not None:
                j.update(charity_amount=charity_amount, giving_split=giving_split or None)

    def record_checkout(self, job_id: str, session_id: str) -> None:
        self.jobs[job_id]["stripe_session_id"] = session_id

    def mark_paid(self, job_id: str, *, method: str, amount_paid: float, donation: float,
                  donation_split: dict | None = None) -> bool:
        with self._lock:
            j = self.jobs[job_id]
            if j["payment_status"] != "unpaid":
                return False
            j.update(payment_status="paid", payment_method=method, amount_paid=amount_paid,
                     donation=donation, donation_split=donation_split or None, paid_at=_now_iso())
            return True

    # ---------- Crew ----------
    def _public(self, m: dict) -> dict:
        return deepcopy({k: m.get(k) for k in CREW_PUBLIC_FIELDS})

    def list_crew(self, include_inactive: bool = False) -> list[dict]:
        ms = sorted(self.crew.values(), key=lambda m: m["created_at"])
        return [self._public(m) for m in ms if include_inactive or m["active"]]

    def get_crew(self, member_id: str, *, with_secret: bool = False) -> dict | None:
        m = self.crew.get(member_id)
        if m is None:
            return None
        out = self._public(m)
        if with_secret:
            out["passcode_hash"] = m["passcode_hash"]
        return out

    def get_crew_by_slug(self, slug: str) -> dict | None:
        m = next((m for m in self.crew.values() if m["slug"] == slug and m["active"]), None)
        return self._public(m) if m else None

    def create_crew(self, fields: dict) -> dict:
        with self._lock:
            if any(m["slug"] == fields["slug"] for m in self.crew.values()):
                raise ValueError("duplicate slug")
            m = {"id": str(uuid.uuid4()), "role_title": None, "bio": None, "years_experience": None,
                 "specialties": [], "service_branch": None, "accent_color": "#2f7d4f", "photo": None,
                 "photo_updated_at": None, "active": True, "created_at": _now_iso(), **fields}
            self.crew[m["id"]] = m
            return self._public(m)

    def update_crew(self, member_id: str, fields: dict) -> dict | None:
        m = self.crew.get(member_id)
        if m is None:
            return None
        m.update(fields)
        return self._public(m)

    def crew_photo(self, member_id: str) -> str | None:
        m = self.crew.get(member_id)
        return m["photo"] if m else None

    def crew_stats(self, member_id: str, since: datetime) -> dict:
        done = [s for s in self.stops.values() if s.get("completed_by") == member_id and s["completed_at"]]
        return {
            "jobs_total": len(done),
            "jobs_week": sum(1 for s in done if datetime.fromisoformat(s["completed_at"]) >= since),
            "photos": sum(1 for p in self.portfolio.values() if p["member_id"] == member_id),
        }

    def add_portfolio(self, member_id, *, photo, caption, service, job_id) -> dict:
        item = {"id": str(uuid.uuid4()), "member_id": member_id, "job_id": job_id, "service": service,
                "caption": caption, "photo": photo, "created_at": _now_iso()}
        self.portfolio[item["id"]] = item
        return {k: item[k] for k in PORTFOLIO_FIELDS}

    def list_portfolio(self, member_id: str, limit: int = 60) -> list[dict]:
        items = sorted((p for p in self.portfolio.values() if p["member_id"] == member_id),
                       key=lambda p: p["created_at"], reverse=True)[:limit]
        return [{k: p[k] for k in PORTFOLIO_FIELDS} for p in items]

    def portfolio_photo(self, item_id: str) -> str | None:
        p = self.portfolio.get(item_id)
        return p["photo"] if p else None

    def delete_portfolio(self, item_id: str, member_id: str) -> bool:
        p = self.portfolio.get(item_id)
        if p is None or p["member_id"] != member_id:
            return False
        del self.portfolio[item_id]
        return True

    # ---------- Owner dashboard + customer visit ----------
    def _stop_for(self, job_id: str) -> dict | None:
        return next((st for st in self.stops.values() if st["job_id"] == job_id), None)

    def list_jobs(self, day: date) -> list[dict]:
        out = []
        for j in self.jobs.values():
            if j["scheduled_date"] != day or j["status"] == "cancelled":
                continue
            st = self._stop_for(j["id"])
            m = self.crew.get((st or {}).get("completed_by") or "")
            out.append(_owner_job(j, self.customers[j["customer_id"]], st, m["display_name"] if m else None))
        return sorted(out, key=lambda j: (j["sequence"] is None, j["sequence"] or 0, j["created_at"] or ""))

    def list_jobs_between(self, start: date, end: date) -> list[dict]:
        return [{k: j.get(k) for k in ("scheduled_date", "status", "payment_status", "amount_due", "amount_paid", "donation", "tax_amount")}
                for j in self.jobs.values() if start <= j["scheduled_date"] <= end and j["status"] != "cancelled"]

    def count_customers_named(self, prefix: str) -> int:
        return sum(1 for c in self.customers.values() if c["name"].startswith(prefix))

    def forget_customer(self, access_code: str) -> str:
        with self._lock:
            j = next((j for j in self.jobs.values() if access_code and j.get("access_code") == access_code), None)
            if j is None:
                return "not_found"
            jobs = [x for x in self.jobs.values() if x["customer_id"] == j["customer_id"]]
            if any(x["status"] in ACTIVE_STATUSES for x in jobs):
                return "upcoming"
            ids = {x["id"] for x in jobs}
            self.job_photos = {k: p for k, p in self.job_photos.items() if p["job_id"] not in ids}
            self.push_subs = {k: p for k, p in self.push_subs.items() if p["job_id"] not in ids}
            for st in self.stops.values():
                if st["job_id"] in ids:
                    st["crew_note"] = None
            for x in jobs:
                x.update(address=DELETED_ADDRESS, formatted_address=None, access_code=None, pay_token=None,
                         lat=round(x["lat"], 2), lng=round(x["lng"], 2))
            self.customers[j["customer_id"]].update(name=DELETED_NAME, phone=_anonymous_phone())
            return "deleted"

    def job_brief(self, job_id: str) -> dict | None:
        j = self.jobs.get(job_id)
        if j is None:
            return None
        c, st = self.customers[j["customer_id"]], self._stop_for(job_id) or {}
        return {**{k: j.get(k) for k in ("id", "status", "scheduled_date", "zone_key", "service", "add_ons", "payment_method",
                                          "payment_status", "amount_paid", "amount_due", "stripe_session_id",
                                          "access_code", "lang")},
                "customer_name": c["name"], "phone": c["phone"], "notified_at": st.get("notified_at"),
                "stop_completed_at": st.get("completed_at")}

    def _drop_stop(self, job_id: str) -> None:
        st = self._stop_for(job_id)
        if st is None:
            return
        del self.stops[st["id"]]
        rest = sorted((s for s in self.stops.values() if s["route_id"] == st["route_id"]), key=lambda s: s["sequence"])
        for i, s in enumerate(rest, start=1):
            s["sequence"] = i

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            j = self.jobs.get(job_id)
            if j is None or j["status"] not in ACTIVE_STATUSES:
                return False
            j["status"] = "cancelled"
            self._drop_stop(job_id)
            return True

    def move_job(self, job_id: str, day: date) -> bool:
        with self._lock:
            j = self.jobs.get(job_id)
            if j is None or j["status"] not in ACTIVE_STATUSES:
                return False
            j.update(scheduled_date=day, status="pending", frozen_at=None)
            self._drop_stop(job_id)
            return True

    def get_visit(self, access_code: str) -> dict | None:
        j = next((j for j in self.jobs.values() if access_code and j.get("access_code") == access_code), None)
        if j is None:
            return None
        st = self._stop_for(j["id"])
        member = self.get_crew(st["completed_by"]) if st and st.get("completed_by") else None
        return _visit(j, self.customers[j["customer_id"]], st, member, self.list_job_photos(j["id"]))

    def add_job_photo(self, job_id, member_id, kind, photo) -> dict:
        p = {"id": str(uuid.uuid4()), "job_id": job_id, "member_id": member_id, "kind": kind, "photo": photo,
             "created_at": _now_iso()}
        self.job_photos[p["id"]] = p
        return {k: p[k] for k in ("id", "job_id", "kind", "created_at")}

    def list_job_photos(self, job_id: str) -> list[dict]:
        photos = sorted((p for p in self.job_photos.values() if p["job_id"] == job_id),
                        key=lambda p: p["created_at"])
        return [{k: p[k] for k in ("id", "kind", "created_at", "member_id")} for p in photos]

    def job_photo(self, photo_id: str) -> dict | None:
        p = self.job_photos.get(photo_id)
        return {k: p[k] for k in ("id", "job_id", "photo")} if p else None

    def save_push_subscription(self, job_id, endpoint, p256dh, auth, lang, visit_path) -> None:
        self.push_subs[endpoint] = {"job_id": job_id, "endpoint": endpoint, "p256dh": p256dh, "auth": auth,
                                    "lang": lang, "visit_path": visit_path}

    def list_push_subscriptions(self, job_id: str) -> list[dict]:
        return [dict(s) for s in self.push_subs.values() if s["job_id"] == job_id]

    def delete_push_subscription(self, endpoint: str) -> None:
        self.push_subs.pop(endpoint, None)


def make_repository(settings: Any) -> Repository:
    if settings.data_backend == "memory":
        return MemoryRepository()
    return SupabaseRepository(settings.supabase_url, settings.supabase_service_role_key)
