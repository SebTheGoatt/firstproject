"""HTTP API + static pages.

    GET  /                          public website (home)
    GET  /book                      customer booking form
    GET  /crew                      field-crew dispatch dashboard
    GET  /sw.js, /*.webmanifest     installable app (PWA) support
    GET  /api/booking-info          earliest bookable date, services
    POST /api/jobs                  intake: validate → geocode → store
    GET  /api/routes/{date}         crew: optimized route with map links
    POST /api/stops/{id}/complete   crew: mark done → text next customer
    POST /webhooks/job-completed    external systems: same as above
    POST /internal/nightly          HTTP trigger for the 8 PM run
    GET  /healthz
"""

import hashlib
import hmac
import html
import logging
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import deeplinks
from .booking import BookingRejected, earliest_bookable_day, local_now, next_service_day, validate_booking
from .config import Settings, get_settings
from .db import Repository, make_repository
from .geocode import GeocoderUnavailable, GeocodingError, NominatimGeocoder
from .models import SERVICE_LABELS, SERVICE_MINUTES, JobCreated, JobRequest, RouteView, Service, StopView
from .nightly import run_nightly
from .notify import TwilioClient, notify_next_customer
from .zones import SERVICE_ZONES, find_zone

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def static_version(directory: Path = STATIC_DIR) -> str:
    """Short hash of every static file; changes on each deploy that edits them."""
    h = hashlib.sha256()
    for f in sorted(p for p in directory.rglob("*") if p.is_file()):
        h.update(f.relative_to(directory).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:12]


def _check_secret(provided: str | None, expected: str) -> None:
    if not provided or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")


def build_route_view(route: dict, settings: Settings) -> RouteView:
    start = (route["start_lat"], route["start_lng"])
    end = (route["end_lat"], route["end_lng"])
    stops = []
    for s in route["stops"]:
        dest = (s["lat"], s["lng"])
        stops.append(StopView(
            stop_id=s["stop_id"], job_id=s["job_id"], sequence=s["sequence"],
            customer_name=s["customer_name"], phone=s["phone"], address=s["address"],
            lat=s["lat"], lng=s["lng"], service=s["service"],
            service_label=SERVICE_LABELS[Service(s["service"])],
            eta=s["eta"], leg_distance_m=s["leg_distance_m"], leg_duration_s=s["leg_duration_s"],
            completed_at=s["completed_at"],
            # Origin omitted → navigation starts from the phone's live location.
            google_maps_url=deeplinks.google_directions(dest),
            apple_maps_url=deeplinks.apple_directions(dest),
        ))
    remaining = [(s.lat, s.lng) for s in stops if s.completed_at is None]
    # Before the first stop is done the crew is at the base; afterwards use live location.
    origin = start if all(s.completed_at is None for s in stops) else None
    return RouteView(
        route_date=route["route_date"],
        timezone=settings.business_timezone,
        total_distance_m=route["total_distance_m"],
        total_duration_s=route["total_duration_s"],
        matrix_source=route["matrix_source"],
        optimized_at=route.get("optimized_at"),
        stops=stops,
        full_route_google_urls=deeplinks.google_full_route(origin, remaining, end) if remaining else [],
    )


def create_app(
    settings: Settings | None = None,
    repo: Repository | None = None,
    geocoder: NominatimGeocoder | None = None,
    sms: TwilioClient | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if settings.data_backend != "memory":
        weak = [n for n in ("crew_access_token", "webhook_secret", "cron_secret") if getattr(settings, n) in ("", "change-me")]
        if weak:
            raise RuntimeError(f"Set real values for: {', '.join(n.upper() for n in weak)}")

    app = FastAPI(title="Property Dispatch")
    app.state.settings = settings
    app.state.repo = repo or make_repository(settings)
    app.state.geocoder = geocoder or NominatimGeocoder(settings)
    app.state.sms = sms if sms is not None else (TwilioClient(settings) if settings.twilio_enabled else None)

    def get_repo(request: Request) -> Repository:
        return request.app.state.repo

    def crew_auth(x_crew_token: str | None = Header(default=None)) -> None:
        _check_secret(x_crew_token, settings.crew_access_token)

    # ---------- Website + installable app -----------------------------
    version = static_version()

    def render(name: str) -> str:
        text = (STATIC_DIR / name).read_text()
        return text.replace("{{BUSINESS_NAME}}", html.escape(settings.business_name)).replace("{{V}}", version)

    def page(name: str) -> HTMLResponse:
        return HTMLResponse(render(name), headers={"Cache-Control": "no-cache"})

    @app.get("/", include_in_schema=False)
    def home_page():
        return page("home.html")

    @app.get("/book", include_in_schema=False)
    def book_page():
        return page("book.html")

    @app.get("/crew", include_in_schema=False)
    def crew_page():
        return page("crew.html")

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        # Served from the root so its scope covers the whole site.
        body = (STATIC_DIR / "sw.js").read_text().replace("__VERSION__", version)
        return Response(body, media_type="application/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return Response(render("manifest.webmanifest"), media_type="application/manifest+json")

    @app.get("/crew.webmanifest", include_in_schema=False)
    def crew_manifest():
        return Response(render("crew.webmanifest"), media_type="application/manifest+json")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(STATIC_DIR / "favicon.ico", media_type="image/x-icon")

    @app.get("/robots.txt", include_in_schema=False)
    def robots():
        return PlainTextResponse("User-agent: *\nAllow: /\nDisallow: /crew\nDisallow: /api/\n")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    # ---------- Intake -------------------------------------------------
    @app.get("/api/booking-info")
    def booking_info():
        now = local_now(settings)
        return {
            "earliest_date": earliest_bookable_day(now, settings.freeze_hour),
            "latest_date": now.date() + timedelta(days=settings.booking_horizon_days),
            "freeze_hour": settings.freeze_hour,
            "services": [{"value": s.value, "label": SERVICE_LABELS[s]} for s in Service],
            "zones": [{"name": z.name, "mow_rate": z.mow_rate} for z in SERVICE_ZONES],
            "business_name": settings.business_name,
        }

    @app.post("/api/jobs", response_model=JobCreated, status_code=201)
    def create_job(body: JobRequest, repo: Repository = Depends(get_repo)):
        now = local_now(settings)
        try:
            validate_booking(body.scheduled_date, now, repo.count_active_jobs(body.scheduled_date), settings)
        except BookingRejected as exc:
            raise HTTPException(status_code=409, detail=str(exc))

        try:
            geo = app.state.geocoder.geocode(body.address)
        except GeocoderUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except GeocodingError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        zone = find_zone(geo.lat, geo.lng)
        if zone is None:
            raise HTTPException(status_code=422, detail=(
                "Sorry, that address is outside our current service areas: "
                + "; ".join(z.name for z in SERVICE_ZONES) + "."))
        price = zone.mow_rate if body.service is Service.MOWING else None

        job = repo.create_job(
            name=body.name, phone=body.phone, address=body.address, geo=geo,
            service=body.service, scheduled_date=body.scheduled_date,
            service_minutes=SERVICE_MINUTES[body.service],
            zone_key=zone.key, quoted_price=price,
        )
        return JobCreated(id=job["id"], scheduled_date=body.scheduled_date, service=body.service,
                          formatted_address=geo.formatted_address, lat=geo.lat, lng=geo.lng,
                          zone_name=zone.name, quoted_price=price)

    # ---------- Crew dispatch -----------------------------------------
    @app.get("/api/routes/{day}", response_model=RouteView, dependencies=[Depends(crew_auth)])
    def get_route(day: date, repo: Repository = Depends(get_repo)):
        route = repo.get_route(day)
        if route is None:
            raise HTTPException(status_code=404, detail=f"No route has been built for {day}")
        return build_route_view(route, settings)

    def _complete(stop_id: str, repo: Repository) -> dict:
        res = repo.complete_stop(stop_id)
        if res is None:
            raise HTTPException(status_code=404, detail="Stop not found")
        stop, newly = res
        notification = notify_next_customer(repo, settings, stop, app.state.sms) if newly else {
            "notified": False, "reason": "already_completed"}
        return {"stop_id": stop_id, "completed_at": stop["completed_at"], "notification": notification}

    @app.post("/api/stops/{stop_id}/complete", dependencies=[Depends(crew_auth)])
    def complete_stop(stop_id: str, repo: Repository = Depends(get_repo)):
        return _complete(stop_id, repo)

    class CompletionHook(BaseModel):
        stop_id: str | None = None
        job_id: str | None = None
        record: dict | None = None  # Supabase Database Webhook payload shape

    @app.post("/webhooks/job-completed")
    def job_completed_webhook(
        body: CompletionHook,
        repo: Repository = Depends(get_repo),
        x_webhook_secret: str | None = Header(default=None),
    ):
        _check_secret(x_webhook_secret, settings.webhook_secret)
        # A Database Webhook fires on every UPDATE to jobs (including the
        # nightly freeze), so only act when the row is actually completed.
        if body.record is not None and body.record.get("status") != "completed":
            return {"ignored": True, "reason": "status is not completed"}
        stop_id = body.stop_id
        job_id = body.job_id or (body.record or {}).get("id")
        if stop_id is None and job_id:
            stop_id = repo.stop_id_for_job(job_id)
        if stop_id is None:
            raise HTTPException(status_code=404, detail="No route stop for that job")
        return _complete(stop_id, repo)

    # ---------- Nightly (HTTP trigger) --------------------------------
    @app.post("/internal/nightly")
    def nightly(
        day: date | None = None,
        repo: Repository = Depends(get_repo),
        x_cron_secret: str | None = Header(default=None),
    ):
        _check_secret(x_cron_secret, settings.cron_secret)
        return run_nightly(repo, settings, day or next_service_day(local_now(settings)))

    return app


def get_app() -> FastAPI:
    """uvicorn factory entry point: `uvicorn app.main:get_app --factory`."""
    return create_app()
