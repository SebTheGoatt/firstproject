"""Data access layer.

`SupabaseRepository` talks to Supabase PostgreSQL through PostgREST using the
service-role key. `MemoryRepository` implements the same interface in-process
for local demos (DATA_BACKEND=memory) and the test suite.

Stop records returned by `get_route` / `next_open_stop` are flat dicts:
    stop_id, route_id, job_id, sequence, leg_distance_m, leg_duration_s, eta,
    completed_at, notified_at, customer_name, phone, address, lat, lng, service
"""

import threading
import uuid
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any, Protocol

from .models import GeoPoint, Job, Service

ACTIVE_STATUSES = ("pending", "scheduled")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository(Protocol):
    def count_active_jobs(self, day: date) -> int: ...
    def create_job(self, *, name: str, phone: str, address: str, geo: GeoPoint, service: Service,
                   scheduled_date: date, service_minutes: int, zone_key: str,
                   quoted_price: float | None) -> dict: ...
    def list_routable_jobs(self, day: date) -> list[Job]: ...
    def save_route(self, *, day: date, start: tuple[float, float], end: tuple[float, float],
                   total_distance_m: int, total_duration_s: int, matrix_source: str,
                   stops: list[dict]) -> str: ...
    def get_route(self, day: date) -> dict | None: ...
    def complete_stop(self, stop_id: str) -> tuple[dict, bool] | None: ...
    def stop_id_for_job(self, job_id: str) -> str | None: ...
    def next_open_stop(self, route_id: str, after_sequence: int) -> dict | None: ...
    def claim_notification(self, stop_id: str) -> bool: ...
    def release_notification(self, stop_id: str) -> None: ...


# ======================================================================
#  Supabase
# ======================================================================
class SupabaseRepository:
    STOP_SELECT = (
        "id, route_id, job_id, sequence, leg_distance_m, leg_duration_s, eta, completed_at, notified_at,"
        " jobs(address, formatted_address, lat, lng, service, customers(name, phone))"
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
            "customer_name": cust["name"],
            "phone": cust["phone"],
            "address": job["address"],
            "lat": job["lat"],
            "lng": job["lng"],
            "service": job["service"],
        }

    def count_active_jobs(self, day: date) -> int:
        res = (
            self.sb.table("jobs").select("id", count="exact", head=True)
            .eq("scheduled_date", day.isoformat()).in_("status", list(ACTIVE_STATUSES)).execute()
        )
        return res.count or 0

    def create_job(self, *, name, phone, address, geo, service, scheduled_date, service_minutes,
                   zone_key, quoted_price) -> dict:
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
            "service": service.value,
            "scheduled_date": scheduled_date.isoformat(),
            "service_minutes": service_minutes,
            "zone_key": zone_key,
            "quoted_price": quoted_price,
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
                address=r["formatted_address"] or r["address"], lat=r["lat"], lng=r["lng"],
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

    def complete_stop(self, stop_id: str) -> tuple[dict, bool] | None:
        now = _now_iso()
        # Conditional update → only the first caller "wins"; retries are no-ops.
        updated = (
            self.sb.table("route_stops").update({"completed_at": now})
            .eq("id", stop_id).is_("completed_at", "null").execute()
        ).data
        newly = bool(updated)
        rows = self.sb.table("route_stops").select(self.STOP_SELECT).eq("id", stop_id).limit(1).execute().data
        if not rows:
            return None
        stop = self._flatten_stop(rows[0])
        if newly:
            self.sb.table("jobs").update({"status": "completed", "completed_at": now}).eq("id", stop["job_id"]).execute()
        return stop, newly

    def stop_id_for_job(self, job_id: str) -> str | None:
        rows = self.sb.table("route_stops").select("id").eq("job_id", job_id).limit(1).execute().data
        return rows[0]["id"] if rows else None

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

    def release_notification(self, stop_id: str) -> None:
        self.sb.table("route_stops").update({"notified_at": None}).eq("id", stop_id).execute()


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

    def count_active_jobs(self, day: date) -> int:
        return sum(1 for j in self.jobs.values() if j["scheduled_date"] == day and j["status"] in ACTIVE_STATUSES)

    def create_job(self, *, name, phone, address, geo, service, scheduled_date, service_minutes,
                   zone_key, quoted_price) -> dict:
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
                "frozen_at": None, "completed_at": None, "created_at": _now_iso(),
            }
            self.jobs[job["id"]] = job
            return deepcopy(job)

    def list_routable_jobs(self, day: date) -> list[Job]:
        out = []
        for j in sorted(self.jobs.values(), key=lambda j: j["created_at"]):
            if j["scheduled_date"] == day and j["status"] in ACTIVE_STATUSES:
                c = self.customers[j["customer_id"]]
                out.append(Job(id=j["id"], customer_name=c["name"], phone=c["phone"],
                               address=j["formatted_address"] or j["address"], lat=j["lat"], lng=j["lng"],
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
                self.stops[sid] = {"id": sid, "route_id": rid, "completed_at": None, "notified_at": None, **s}
                job = self.jobs[s["job_id"]]
                if job["status"] == "pending":
                    job["status"] = "scheduled"
                    job["frozen_at"] = _now_iso()
            return rid

    def _flat(self, s: dict) -> dict:
        j = self.jobs[s["job_id"]]
        c = self.customers[j["customer_id"]]
        return {
            "stop_id": s["id"], "route_id": s["route_id"], "job_id": s["job_id"], "sequence": s["sequence"],
            "leg_distance_m": s["leg_distance_m"], "leg_duration_s": s["leg_duration_s"], "eta": s["eta"],
            "completed_at": s["completed_at"], "notified_at": s["notified_at"],
            "customer_name": c["name"], "phone": c["phone"], "address": j["address"],
            "lat": j["lat"], "lng": j["lng"], "service": j["service"],
        }

    def get_route(self, day: date) -> dict | None:
        route = next((r for r in self.routes.values() if r["route_date"] == day), None)
        if route is None:
            return None
        route = deepcopy(route)
        stops = sorted((s for s in self.stops.values() if s["route_id"] == route["id"]), key=lambda s: s["sequence"])
        route["stops"] = [self._flat(s) for s in stops]
        return route

    def complete_stop(self, stop_id: str) -> tuple[dict, bool] | None:
        with self._lock:
            s = self.stops.get(stop_id)
            if s is None:
                return None
            newly = s["completed_at"] is None
            if newly:
                now = _now_iso()
                s["completed_at"] = now
                job = self.jobs[s["job_id"]]
                job["status"], job["completed_at"] = "completed", now
            return self._flat(s), newly

    def stop_id_for_job(self, job_id: str) -> str | None:
        return next((sid for sid, s in self.stops.items() if s["job_id"] == job_id), None)

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

    def release_notification(self, stop_id: str) -> None:
        self.stops[stop_id]["notified_at"] = None


def make_repository(settings: Any) -> Repository:
    if settings.data_backend == "memory":
        return MemoryRepository()
    return SupabaseRepository(settings.supabase_url, settings.supabase_service_role_key)
