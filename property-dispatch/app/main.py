"""HTTP API + static pages.

    GET  /                          public website (home)
    GET  /book                      customer booking form
    GET  /crew                      field-crew dispatch dashboard
    GET  /sw.js, /*.webmanifest     installable app (PWA) support
    GET  /team, /team/{slug}        public "Meet the crew" pages
    GET  /pay/{token}               customer payment page
    (crew sign-in/profiles: app/crew_routes.py · payments: app/pay_routes.py)
    GET  /local, /local/{area}      service-area pages + /sitemap.xml (app/local_pages.py)
    GET  /privacy, /terms, /refunds policies (app/legal_pages.py)
    GET  /api/booking-info          earliest bookable date, services
    POST /api/jobs                  intake: validate → geocode → store
    GET  /api/routes/{date}         crew: optimized route with map links
    POST /api/stops/{id}/complete   crew: mark done → text next customer
    POST /webhooks/job-completed    external systems: same as above
    POST /internal/nightly          HTTP trigger for the 5 PM route build
    POST /internal/review-requests  send any Google review requests that are due (also runs on its own)
    GET  /healthz
"""

import asyncio
import hashlib
import hmac
import html
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import deeplinks, push, reviews
from .booking import BookingRejected, earliest_bookable_day, local_now, next_service_day, validate_booking
from .config import Settings, get_settings, site_url
from .db import Repository, make_repository
from .geocode import GeocodingError, GeocoderUnavailable, NominatimGeocoder
from .agent import register_agent_routes
from .agent_api import register_agent_api
from .live_feed import record_booking, register_live_routes
from .legal_pages import SMS_CONSENT, legal_footer_html, register_legal_pages
from .local_pages import register_local_pages
from .crew_auth import CrewIdentity
from .crew_routes import register_crew_routes
from .models import (SERVICE_LABELS, order_label, AddressCheck, CompleteStopRequest, GeoPoint, JobCreated,
                     JobRequest, OptimizeRouteRequest, QuoteRequest, RouteView, Service, StopNote, StopView)
from .charity import causes as charity_causes, chosen_cause, charity_names, describe as describe_charities, route_donation
from .pricing import (ADD_ONS, BRACKET_PROFILES, FEATURED_PACKAGE, PRICE_BRACKETS, mow_minutes, scope_of, MAX_SQFT, MIN_SQFT, PACKAGES, LawnSizeError, check_sqft, in_season, package_for_rate,
                      quote, season_text)
from .routing.matrix import haversine_m
from .nightly import run_nightly
from .dispatch import reoptimize_remaining
from .lawn_estimate import estimate_lawn, scope_sqft
from .directions import DirectionsUnavailable, get_directions
from .notify import (TwilioClient, booking_message, day_words, notify_next_customer, notify_stop, send_pay_link, send_text,
                     service_words)
from .pay_routes import register_pay_routes
from .visit_routes import format_code, new_access_code, register_visit_routes
from .payments import StripeClient
from .zones import SERVICE_ZONES, find_zone, zone_by_key

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def static_version(directory: Path = STATIC_DIR) -> str:
    """Short hash of every static file; changes on each deploy that edits them."""
    h = hashlib.sha256()
    for f in sorted(p for p in directory.rglob("*") if p.is_file()):
        h.update(f.relative_to(directory).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:12]


# Coordinates a customer's browser sends (from the Google dropdown) are only a hint:
# they're used when our own lookups find just the street, or nothing, and only if
# they're in Texas and, when we have a street point, within this distance of it.
HINT_MAX_DISTANCE_M = 1500
TEXAS_BOUNDS = (25.8, -106.7, 36.6, -93.5)  # south, west, north, east


def _in_texas(lat: float, lng: float) -> bool:
    s, w, n, e = TEXAS_BOUNDS
    return s <= lat <= n and w <= lng <= e


class RateLimiter:
    """Small per-IP limiter for public endpoints that call the free geocoders."""

    def __init__(self, limit: int, window_s: int):
        self.limit, self.window_s = limit, window_s
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        import time

        now = time.time()
        hits = [t for t in self._hits.get(key, []) if now - t < self.window_s]
        if len(hits) >= self.limit:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True


def _check_secret(provided: str | None, expected: str) -> None:
    if not provided or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")


def build_route_view(route: dict, settings: Settings) -> RouteView:
    start = (route["start_lat"], route["start_lng"])
    end = (route["end_lat"], route["end_lng"])
    stops = []
    for s in route["stops"]:
        # Navigate by the customer's full address so Maps goes to the house,
        # not to the geocoder's point (which may only be the street).
        dest = s["address"] or (s["lat"], s["lng"])
        stops.append(StopView(
            stop_id=s["stop_id"], job_id=s["job_id"], sequence=s["sequence"],
            customer_name=s["customer_name"], phone=s["phone"], address=s["address"],
            lat=s["lat"], lng=s["lng"], service=s["service"],
            service_label=order_label(s["service"], s.get("add_ons")), service_minutes=s.get("service_minutes"),
            scope=scope_of(s.get("add_ons")),
            charity_choice_name=(charity_names(settings)[c] if (c := chosen_cause(s.get("giving_split"))) else None),
            add_ons=s.get("add_ons") or [], add_on_total=s.get("add_on_total") or 0.0,
            eta=s["eta"], leg_distance_m=s["leg_distance_m"], leg_duration_s=s["leg_duration_s"],
            completed_at=s["completed_at"], completed_by_name=s.get("completed_by_name"),
            notified_at=s.get("notified_at"),
            payment_method=s.get("payment_method") or "cash", payment_status=s.get("payment_status") or "unpaid",
            amount_due=s.get("amount_due"), amount_paid=s.get("amount_paid"), donation=s.get("donation") or 0.0,
            subtotal=s.get("subtotal"), tax_rate=s.get("tax_rate"), tax_amount=s.get("tax_amount"),
            lawn_sqft=s.get("lawn_sqft"), sqft_rate=s.get("sqft_rate"), package=s.get("package"),
            charity_rate=s.get("charity_rate"), charity_amount=s.get("charity_amount"),
            flat_fee=(z.mow_rate if (z := zone_by_key(s.get("zone_key"))) and s["service"] == "mowing" else None),
            # Origin omitted → navigation starts from the phone's live location.
            google_maps_url=deeplinks.google_directions(dest),
            apple_maps_url=deeplinks.apple_directions(dest),
        ))
    remaining = [s.address or (s.lat, s.lng) for s in stops if s.completed_at is None]
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


def send_review_requests(app: FastAPI, base_url: str) -> dict:
    s = app.state.settings
    return reviews.send_due_review_requests(app.state.repo, s, app.state.sms, datetime.now(timezone.utc), base_url,
                                            app.state.reviews_asked)


async def review_loop(app: FastAPI) -> None:
    """Every few minutes, off the request path: ask for Google reviews ~20 min after each job is done."""
    s = app.state.settings
    base_url = (s.public_base_url or os.environ.get("RENDER_EXTERNAL_URL", "")).rstrip("/")
    while True:
        await asyncio.sleep(s.review_requests_every_min * 60)
        try:
            await asyncio.to_thread(send_review_requests, app, base_url)   # database + texts run in a worker thread
        except Exception:
            log.exception("Review request run failed")


def create_app(
    settings: Settings | None = None,
    repo: Repository | None = None,
    geocoder: NominatimGeocoder | None = None,
    sms: TwilioClient | None = None,
    stripe: StripeClient | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if settings.data_backend != "memory":
        weak = [n for n in ("crew_access_token", "webhook_secret", "cron_secret") if getattr(settings, n) in ("", "change-me")]
        if weak:
            raise RuntimeError(f"Set real values for: {', '.join(n.upper() for n in weak)}")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(review_loop(app)) if reviews.review_link(settings) and settings.review_requests_every_min > 0 else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Property Dispatch", lifespan=lifespan)
    app.state.settings = settings
    app.state.reviews_asked = set()      # only used until the review_requested_at column exists
    app.state.repo = repo or make_repository(settings)
    app.state.geocoder = geocoder or NominatimGeocoder(settings)
    app.state.sms = sms if sms is not None else (TwilioClient(settings) if settings.twilio_enabled else None)
    app.state.stripe = stripe if stripe is not None else (StripeClient(settings) if settings.stripe_enabled else None)

    def get_repo(request: Request) -> Repository:
        return request.app.state.repo


    # ---------- Website + installable app -----------------------------
    version = static_version()

    def render(name: str) -> str:
        # Static pages are UTF-8 regardless of the host process locale (Windows hosts default to a legacy code page).
        text = (STATIC_DIR / name).read_text(encoding="utf-8")
        return (text.replace("{{BUSINESS_NAME}}", html.escape(settings.business_name)).replace("{{V}}", version)
                .replace("{{LEGAL_FOOTER}}", legal_footer_html(settings))
                .replace("{{SMS_CONSENT}}", html.escape(SMS_CONSENT.format(legal=settings.legal_name))))

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

    @app.get("/crew/dashboard", include_in_schema=False)
    def crew_dashboard_page():
        return page("crew-dashboard.html")

    @app.get("/team", include_in_schema=False)
    @app.get("/team/{slug}", include_in_schema=False)
    def team_page(slug: str | None = None):
        return page("team.html")

    @app.get("/pay/{token}", include_in_schema=False)
    def pay_page(token: str):
        resp = page("pay.html")
        resp.headers["Referrer-Policy"] = "no-referrer"   # keep the private link out of Referer headers
        resp.headers["X-Robots-Tag"] = "noindex"
        return resp

    @app.get("/visit", include_in_schema=False)
    @app.get("/visit/{code}", include_in_schema=False)
    def visit_page(code: str | None = None):
        resp = page("visit.html")
        resp.headers["Referrer-Policy"] = "no-referrer"   # keep the access code out of Referer headers
        resp.headers["X-Robots-Tag"] = "noindex"
        return resp

    crew_auth = register_crew_routes(app, settings)
    register_live_routes(app, settings, crew_auth)   # owner-only live station: /api/track, /api/live/stats (dashboard lives in the crew app's owner tab)
    register_pay_routes(app, settings, app.state.stripe)
    register_visit_routes(app, settings, crew_auth)
    register_agent_api(app, settings, build={"static_version": version, "commit": os.environ.get("RENDER_GIT_COMMIT", "")[:7]})   # scoped, audited keys for StarNet agents (off unless AGENT_KEY_READ / AGENT_KEY_OPS are set)
    register_agent_routes(app, settings, crew_auth)   # owner-only Ollama dispatch assistant (off unless OLLAMA_BASE_URL is set)
    register_local_pages(app, settings, version)      # server-rendered /local area pages + /sitemap.xml for search engines
    register_legal_pages(app, settings, version)      # /privacy, /terms (with the damage policy), /refunds

    @app.get("/push-setup", include_in_schema=False)
    def push_setup_page():
        # Makes the notification key pair inside the owner's browser; nothing is sent anywhere.
        resp = page("push-setup.html")
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Robots-Tag"] = "noindex"
        return resp

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        # Served from the root so its scope covers the whole site.
        body = (STATIC_DIR / "sw.js").read_text(encoding="utf-8").replace("__VERSION__", version)
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
    def robots(request: Request):
        return PlainTextResponse("User-agent: *\nAllow: /\nDisallow: /crew\nDisallow: /api/\n"
                                 f"Sitemap: {site_url(settings, request)}/sitemap.xml\n")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    # ---------- Intake -------------------------------------------------
    @app.get("/api/booking-info")
    def booking_info(request: Request):
        now = local_now(settings)
        earliest = earliest_bookable_day(now, settings.freeze_hour)
        try:  # real openings on the next route (daily_job_quota minus active jobs); never blocks the page
            spots_left = max(0, settings.daily_job_quota - request.app.state.repo.count_active_jobs(earliest))
        except Exception:
            spots_left = None
        return {
            "earliest_date": earliest,
            "spots_left": spots_left,
            "latest_date": now.date() + timedelta(days=settings.booking_horizon_days),
            "freeze_hour": settings.freeze_hour,
            "services": [{"value": s.value, "label": SERVICE_LABELS[s]} for s in Service],
            "zones": [{"key": z.key, "name": z.name, "mow_rate": z.mow_rate, "tax_rate": z.tax_rate,
                       "bbox": list(z.bbox), "boxes": [list(b) for b in z.boxes]}
                      for z in SERVICE_ZONES],
            # Mowing: base fee (per area) + lawn sq ft × the rate tier the customer picks (form pre-selects the featured one).
            "packages": [{"key": k, "label": p["label"], "description": p["description"],
                          "charity_rate": float(p["giving"]),
                          # flat price per visit by lawn size (base included); no per-sq-ft rate is shown
                          "brackets": [{"max_sqft": limit, "price": float(prices[k]), "profile": name}
                                       for (limit, prices), name in zip(PRICE_BRACKETS, BRACKET_PROFILES)]}
                         for k, p in PACKAGES.items()],
            "featured_package": FEATURED_PACKAGE,
            "lawn_sqft_limits": {"min": MIN_SQFT, "max": MAX_SQFT},
            # Owner-confirmed facts for the base-fee note; nothing is claimed unless it's set in Render.
            "assurances": {"liability_coverage": settings.liability_coverage.strip() or None,
                           "background_checked": settings.crew_background_checked},
            # Add-ons to a mow. price None = free quote request. Seasonal ones list their service dates.
            "add_ons": [{"key": k, "label": a["label"], "price": float(a["price"]) if a["price"] is not None else None,
                         "quote": bool(a.get("quote")), "season": season_text(k), "season_range": a.get("season"),
                         "scope": bool(a.get("scope"))}
                        for k, a in ADD_ONS.items()],
            "charities": describe_charities(settings),
            "causes": charity_causes(settings),           # the customer picks one at booking
            "business_name": settings.business_name,
            "card_payments": app.state.stripe is not None,
            "google_maps_key": settings.google_maps_browser_key or None,
        }

    def locate(address: str, lat: float | None, lng: float | None) -> GeoPoint:
        """Our geocoders decide; the browser's Google coordinates only fill gaps (see HINT_MAX_DISTANCE_M)."""
        hint = (lat, lng) if lat is not None and lng is not None and _in_texas(lat, lng) else None

        def from_hint() -> GeoPoint:
            return GeoPoint(lat=hint[0], lng=hint[1], formatted_address=address, precision="address")

        try:
            geo = app.state.geocoder.geocode(address)
        except GeocoderUnavailable as exc:
            if hint:
                return from_hint()
            raise HTTPException(status_code=503, detail=str(exc))
        except GeocodingError as exc:
            if hint:  # e.g. a brand-new subdivision Google knows and the free lookups don't yet
                return from_hint()
            raise HTTPException(status_code=422, detail=str(exc))
        if hint and geo.precision != "address" and haversine_m((geo.lat, geo.lng), hint) <= HINT_MAX_DISTANCE_M:
            return from_hint()
        return geo

    def outside_message() -> str:
        return ("Sorry, that address is outside our current service areas: "
                + "; ".join(z.name for z in SERVICE_ZONES) + ".")

    check_limiter = RateLimiter(limit=30, window_s=600)

    @app.post("/api/check-address")
    def check_address(body: AddressCheck, request: Request, repo: Repository = Depends(get_repo)):
        """Instant 'are you in our area?' answer while the customer fills out the form. Saves nothing."""
        if not check_limiter.allow(request.client.host if request.client else "unknown"):
            raise HTTPException(status_code=429, detail="Too many checks. Please wait a few minutes.")
        geo = locate(body.address.strip(), body.lat, body.lng)
        zone = find_zone(geo.lat, geo.lng)
        return {
            "in_area": zone is not None,
            "zone_name": zone.name if zone else None,
            "mow_rate": zone.mow_rate if zone else None,
            "matched_address": geo.formatted_address if geo.precision == "address" else body.address.strip(),
            "message": (f"Good news: you're in our {zone.name} area. Mowing is a flat price per visit by lawn size, "
                        f"from ${min(min(p.values()) for _, p in PRICE_BRACKETS):,.0f}."
                        if zone else outside_message()),
            # So the customer doesn't have to guess: an estimate for this area (they can change it; the crew confirms on site).
            "lawn_estimate": estimate_lawn(repo, zone) if zone else None,
        }

    def scoped_sqft(add_ons, zone, client_sqft, repo):
        """Yard / full property bookings: the server sets the size for the area (the browser's number is ignored)."""
        scope = scope_of(add_ons)
        return scope_sqft(repo, zone, scope) if scope else client_sqft

    @app.post("/api/quote")
    def price_quote(body: QuoteRequest, request: Request, repo: Repository = Depends(get_repo)):
        """Live price while the customer fills in the form. Saves nothing."""
        if not check_limiter.allow(request.client.host if request.client else "unknown"):
            raise HTTPException(status_code=429, detail="Too many checks. Please wait a few minutes.")
        geo = locate(body.address.strip(), body.lat, body.lng)
        zone = find_zone(geo.lat, geo.lng)
        if zone is None:
            return {"in_area": False, "message": outside_message()}
        add_ons = [k for k in body.add_ons if body.scheduled_date is None or in_season(k, body.scheduled_date)]
        try:
            sqft = (check_sqft(scoped_sqft(add_ons, zone, body.lawn_sqft, repo))
                    if body.service is Service.MOWING else None)
            q = quote(zone, body.service, sqft, package=body.package, add_ons=add_ons)
        except (LawnSizeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"in_area": True, "zone_name": zone.name, "flat_fee": zone.mow_rate,
                "service_label": order_label(body.service.value, list(q.add_ons)), **q.as_dict()}

    @app.post("/api/jobs", response_model=JobCreated, status_code=201)
    def create_job(body: JobRequest, request: Request, repo: Repository = Depends(get_repo)):
        now = local_now(settings)
        try:
            validate_booking(body.scheduled_date, now, repo.count_active_jobs(body.scheduled_date), settings)
        except BookingRejected as exc:
            raise HTTPException(status_code=409, detail=str(exc))

        if body.sms_consent is False:
            raise HTTPException(status_code=422, detail=(
                "Please tick the box agreeing to texts about this booking. We use them to tell you when the crew is on the way."))
        if body.service is not Service.MOWING:
            raise HTTPException(status_code=422, detail=(
                "Bin cleaning and gutters are add-ons to a mowing visit. Book mowing and add them on."))
        if body.package is None:
            raise HTTPException(status_code=422, detail="Choose a rate: Neighborhood Block Lock, Operational Target or Bi-Weekly Demand.")
        if not scope_of(body.add_ons):          # yard / full property: the size comes from the address below
            try:
                check_sqft(body.lawn_sqft)
            except LawnSizeError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
        for k in body.add_ons:
            if not in_season(k, body.scheduled_date):
                raise HTTPException(status_code=422, detail=(
                    f"{ADD_ONS[k]['label']} is offered for service dates {season_text(k)}."))
        geo = locate(body.address, body.lat, body.lng)
        zone = find_zone(geo.lat, geo.lng)
        if zone is None:
            raise HTTPException(status_code=422, detail=outside_message())
        # The server's own price, from the size (set here for yard / full property), tier and add-ons.
        try:
            lawn_sqft = check_sqft(scoped_sqft(body.add_ons, zone, body.lawn_sqft, repo))
            q = quote(zone, body.service, lawn_sqft, package=body.package, add_ons=body.add_ons)
        except (LawnSizeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        add_ons = [{**a, "price": float(a["price"]) if a["price"] is not None else None} for a in q.add_ons]
        sqft = q.lawn_sqft
        price = float(q.subtotal) if q.subtotal is not None else None
        rate = float(q.sqft_rate) if q.sqft_rate is not None else None
        giving = float(q.charity_amount) if q.charity_amount is not None else None
        if body.payment_method == "card" and app.state.stripe is None:
            raise HTTPException(status_code=422, detail="Card payments aren't available yet. Please choose cash.")
        pay_token = secrets.token_urlsafe(18)
        access_code = new_access_code()

        job = repo.create_job(
            name=body.name, phone=body.phone, address=body.address, geo=geo,
            service=body.service, scheduled_date=body.scheduled_date,
            service_minutes=mow_minutes(sqft) + sum(ADD_ONS[a["key"]]["minutes"] for a in add_ons),   # bigger lawn, longer stop
            zone_key=zone.key, quoted_price=price,
            payment_method=body.payment_method, pay_token=pay_token, access_code=access_code,
            amount_due=float(q.total) if q.total is not None else None, lawn_sqft=sqft,
            subtotal=price, tax_rate=float(q.tax_rate), tax_amount=float(q.tax) if q.tax is not None else None,
            sqft_rate=rate, package=q.package,
            charity_rate=float(q.charity_rate) if q.charity_rate is not None else None,
            charity_amount=giving, giving_split=route_donation(giving, body.charity_choice) if giving else None,
            add_ons=add_ons, add_on_total=float(q.add_on_total), lang=body.lang,
        )
        record_booking(job_id=str(job["id"]))   # the only booking counter (idempotent per job)
        if body.sms_consent:   # proof of consent for texting (TCPA): which booking, when, and the exact wording
            log.info("SMS consent: job %s at %s: %s", job["id"], now.isoformat(), SMS_CONSENT.format(legal=settings.legal_name))
        base = site_url(settings, request)
        visit_url = f"{base}/visit/{access_code}"
        send_text(app.state.sms, body.phone, booking_message(
            body.name.split()[0], settings, service_words(body.service.value, add_ons, body.lang),
            day_words(body.scheduled_date, body.lang), format_code(access_code), visit_url, lang=body.lang))
        # Show the customer the house-level match when we have one; otherwise echo
        # their own address back (a street-level match would drop their house number).
        shown = geo.formatted_address if geo.precision == "address" else body.address
        return JobCreated(id=job["id"], scheduled_date=body.scheduled_date, service=body.service,
                          formatted_address=shown, lat=geo.lat, lng=geo.lng,
                          zone_name=zone.name, quoted_price=price, payment_method=body.payment_method,
                          pay_url=f"/pay/{pay_token}" if body.payment_method == "card" else None,
                          access_code=format_code(access_code), visit_url=f"/visit/{access_code}",
                          lawn_sqft=sqft, sqft_rate=rate, package=q.package,
                          charity_rate=float(q.charity_rate) if q.charity_rate is not None else None,
                          charity_amount=giving, charity_choice=body.charity_choice,
                          add_ons=add_ons, add_on_total=float(q.add_on_total),
                          subtotal=price, tax_rate=float(q.tax_rate),
                          tax=float(q.tax) if q.tax is not None else None,
                          total=float(q.total) if q.total is not None else None)

    # ---------- Crew dispatch -----------------------------------------
    @app.get("/api/routes/{day}", response_model=RouteView, dependencies=[Depends(crew_auth)])
    def get_route(day: date, repo: Repository = Depends(get_repo)):
        route = repo.get_route(day)
        if route is None:
            raise HTTPException(status_code=404, detail=f"No route has been built for {day}")
        return build_route_view(route, settings)

    def _complete(stop_id: str, repo: Repository, *, member_id: str | None = None,
                  body: CompleteStopRequest | None = None, base_url: str = "") -> dict:
        body = body or CompleteStopRequest()
        before = repo.get_stop(stop_id)
        if before is None:
            raise HTTPException(status_code=404, detail="Stop not found")

        # Re-price on site before anything is saved: the crew confirms the lawn size
        # (mowing) or sets the price (bins, gutters). Tax is recalculated each time.
        due = before["amount_due"]
        unpaid = before["payment_status"] == "unpaid"
        zone = zone_by_key(before.get("zone_key")) or find_zone(before["lat"], before["lng"])
        new_price = None
        on_site = body.price if body.price is not None else body.amount_due
        if unpaid and zone is not None:
            # Yard / full property bookings are price-locked: the crew mows the area booked, no re-measuring.
            if (before["service"] == Service.MOWING.value and body.lawn_sqft and body.lawn_sqft != before.get("lawn_sqft")
                    and not scope_of(before.get("add_ons"))):
                # Same package the customer chose at booking.
                new_price = quote(zone, Service.MOWING, body.lawn_sqft,
                                  package=before.get("package") or package_for_rate(before.get("sqft_rate")),
                                  add_ons=[a["key"] for a in before.get("add_ons") or []])
            elif before["service"] != Service.MOWING.value and on_site is not None:
                new_price = quote(zone, Service(before["service"]), on_site_price=on_site)
        if new_price is not None:
            due = float(new_price.total)

        # Cash: the crew records what they were handed. Anything over the total is a donation.
        cash = None
        if body.cash_collected is not None and unpaid:
            if due is None:
                raise HTTPException(status_code=422, detail="Enter the job price before recording cash.")
            cash = round(body.cash_collected, 2)
            if cash < due:
                raise HTTPException(status_code=422, detail=f"Cash collected is less than the ${due:,.2f} total.")

        if new_price is not None:
            giving = float(new_price.charity_amount) if new_price.charity_amount is not None else None
            repo.set_price(before["job_id"], subtotal=float(new_price.subtotal), tax_amount=float(new_price.tax),
                           total=float(new_price.total), lawn_sqft=new_price.lawn_sqft,
                           charity_amount=giving,
                           giving_split=route_donation(giving, chosen_cause(before.get("giving_split"))) if giving else None)
        stop, newly = repo.complete_stop(stop_id, member_id)
        done_push = push.send_to_job(repo, settings, stop["job_id"], "done") if newly else None

        payment = {"status": stop["payment_status"], "total": due}
        if cash is not None and stop["payment_status"] == "unpaid":
            donation = round(cash - due, 2)
            split = route_donation(donation, chosen_cause(before.get("giving_split")))   # to the customer's pick
            repo.mark_paid(stop["job_id"], method="cash", amount_paid=cash, donation=donation, donation_split=split)
            payment = {"status": "paid", "method": "cash", "amount_paid": cash, "donation": donation,
                       "donation_split": split, "total": due}
        elif (newly and stop["payment_method"] == "card" and stop["payment_status"] == "unpaid"
              and stop["pay_token"] and stop["amount_due"] is not None and base_url):
            # Card customers who haven't paid yet get their private pay link when the job is done.
            payment["pay_link"] = send_pay_link(settings, stop, f"{base_url}/pay/{stop['pay_token']}", app.state.sms)

        notification = notify_next_customer(repo, settings, stop, app.state.sms) if newly else {
            "notified": False, "reason": "already_completed"}
        out = {"stop_id": stop_id, "completed_at": stop["completed_at"], "notification": notification,
               "payment": payment}
        if done_push and done_push["failed"] and not done_push["sent"]:    # tell the crew why the customer wasn't pinged
            out["done_notification_problem"] = push.PROBLEMS.get(done_push["problem"], "")
        return out

    @app.post("/api/stops/{stop_id}/complete")
    def complete_stop(stop_id: str, request: Request, body: CompleteStopRequest | None = None,
                      who: CrewIdentity = Depends(crew_auth), repo: Repository = Depends(get_repo)):
        return _complete(stop_id, repo, member_id=who.member_id, body=body,
                         base_url=site_url(settings, request))

    @app.post("/api/stops/{stop_id}/on-the-way")
    def on_the_way(stop_id: str, who: CrewIdentity = Depends(crew_auth), repo: Repository = Depends(get_repo)):
        """The crew taps "On my way": the customer gets an app/browser notification (if they turned on visit
        updates) and their visit page shows it. No text message. Completing a job notifies the next stop
        automatically; this covers the first stop of the day."""
        stop = repo.get_stop(stop_id)
        if stop is None:
            raise HTTPException(status_code=404, detail="Stop not found.")
        if stop["completed_at"] is not None:
            raise HTTPException(status_code=409, detail="That job is already done.")
        member = repo.get_crew(who.member_id) if who.member_id else None
        return notify_stop(repo, settings, stop, None, member["display_name"] if member else None, text=False)

    # ---------- Crew dashboard: one-button route -----------------------
    @app.post("/api/crew/optimize-route", dependencies=[Depends(crew_auth)])
    def optimize_route_now(body: OptimizeRouteRequest | None = None, repo: Repository = Depends(get_repo)):
        """Plan the day's open stops from the crew's position (or the last finished stop / the base).
        Builds the route first if it doesn't exist yet and the day is already locked (past the 5 PM cutoff)."""
        body = body or OptimizeRouteRequest()
        now = local_now(settings)
        day = body.day or now.date()
        if day < now.date():
            raise HTTPException(status_code=409, detail="That day has already passed.")
        built = False
        if repo.get_route(day) is None:
            if day >= earliest_bookable_day(now, settings.freeze_hour):
                raise HTTPException(status_code=409, detail="That day isn't locked yet. Routes are built at 5 PM the day before.")
            if not repo.list_routable_jobs(day):
                raise HTTPException(status_code=404, detail="No jobs are booked for that day.")
            run_nightly(repo, settings, day)
            built = True
        origin = (body.lat, body.lng) if body.lat is not None and body.lng is not None else None
        summary = reoptimize_remaining(repo, settings, day, now, origin)
        return {**summary, "built": built, "used_gps": origin is not None,
                "route": build_route_view(repo.get_route(day), settings)}

    @app.get("/api/crew/directions/{stop_id}", dependencies=[Depends(crew_auth)])
    def directions_to_stop(stop_id: str, lat: float | None = None, lng: float | None = None,
                           repo: Repository = Depends(get_repo)):
        """In-app turn-by-turn: the road route from the crew's GPS position to this stop."""
        stop = repo.get_stop(stop_id)
        if stop is None:
            raise HTTPException(status_code=404, detail="Stop not found.")
        if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise HTTPException(status_code=422, detail="Turn on location so the app can guide you.")
        try:
            out = get_directions(settings.osrm_url, (lat, lng), (stop["lat"], stop["lng"]))
        except DirectionsUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        return {**out, "stop_id": stop_id, "destination": [stop["lng"], stop["lat"]], "address": stop["address"]}

    @app.put("/api/stops/{stop_id}/note", dependencies=[Depends(crew_auth)])
    def save_stop_note(stop_id: str, body: StopNote, repo: Repository = Depends(get_repo)):
        """Private crew note on a stop (never shown to the customer)."""
        if repo.get_stop(stop_id) is None:
            raise HTTPException(status_code=404, detail="Stop not found.")
        note = (body.note or "").strip() or None
        try:
            repo.set_stop_note(stop_id, note)
        except Exception:
            log.exception("Saving a crew note failed")
            raise HTTPException(status_code=503, detail="Notes need a one-time database update. Ask the owner to run the "
                                                        "latest Supabase SQL (crew notes).")
        return {"stop_id": stop_id, "note": note}

    @app.get("/api/routes/{day}/notes", dependencies=[Depends(crew_auth)])
    def route_notes(day: date, repo: Repository = Depends(get_repo)):
        route = repo.get_route(day)
        if route is None:
            return {}
        try:
            return repo.stop_notes(route["id"])
        except Exception:      # notes column not added yet: the dashboard still works without notes
            return {}

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
        return _complete(stop_id, repo, base_url=settings.public_base_url)

    # ---------- Nightly (HTTP trigger) --------------------------------
    @app.post("/internal/nightly")
    def nightly(
        day: date | None = None,
        repo: Repository = Depends(get_repo),
        x_cron_secret: str | None = Header(default=None),
    ):
        _check_secret(x_cron_secret, settings.cron_secret)
        return run_nightly(repo, settings, day or next_service_day(local_now(settings)))

    @app.post("/internal/review-requests")
    def review_requests(request: Request, x_cron_secret: str | None = Header(default=None)):
        _check_secret(x_cron_secret, settings.cron_secret)
        return send_review_requests(request.app, site_url(settings, request))

    return app


def get_app() -> FastAPI:
    """uvicorn factory entry point: `uvicorn app.main:get_app --factory`."""
    return create_app()
