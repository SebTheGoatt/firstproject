"""Marketing hub: know which flyer, sign or post brings bookings, and have this week's posts written for you.

    GET /owner/marketing                     the hub (owner sign-in from the crew app)
    GET /api/owner/marketing                 scoreboard, this week's posts, link targets, channel list
    GET /marketing/qr.svg?path=&ref=         QR code for one of our own pages with a ?ref= tag (public: it's for print)
    GET /owner/marketing/print?kind=&path=&ref=   print-ready yard sign, door hanger or flyer with that QR code

Everything is built from the real data: prices from app/pricing.py, areas and days from app/zones.py, open spots
from the bookings. Tracking is a short ?ref= label on the link (e.g. "yard-sign-klein"), carried into the booking
by static/site.js. No personal data is collected, and nothing here claims more than the business does.
"""

import html
import io
import re
from collections import defaultdict
from datetime import date, timedelta

import segno
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from .booking import cached_count, earliest_bookable_day, local_now
from .config import Settings, site_url
from .local_pages import AREA_BY_SLUG, AREAS, HOODS, dollars, layout, percent, price_range
from .pricing import density_pct
from .reviews import review_link
from .service_pages import SERVICES
from .zones import SERVICE_ZONES, WEEKDAY_NAMES, short_name, zone_by_key

esc = html.escape

# Where a link or QR code is used. The key starts the ?ref= label; the area slug is added after it.
CHANNELS = {
    "yard-sign": "Yard sign", "door-hanger": "Door hanger", "flyer": "Flyer", "truck": "Truck or trailer magnet",
    "business-card": "Business card", "google-business": "Google Business post", "facebook": "Facebook",
    "nextdoor": "Nextdoor", "instagram": "Instagram", "tiktok": "TikTok", "email": "Email", "text": "Text message",
}
# Labels the site sets on its own from where a visitor came from (static/site.js).
AUTO_SOURCES = {"google": "Google search", "bing": "Bing search", "yelp": "Yelp", "ai-chatgpt": "ChatGPT",
                "ai-perplexity": "Perplexity", "ai-assistant": "Other AI assistant"}
PRINTS = {"yard-sign": "Yard sign (18×24 in)", "door-hanger": "Door hanger (4.25×11 in)", "flyer": "Flyer (letter)"}
REF = re.compile(r"^[a-z0-9-]{1,48}$")


def targets() -> list[dict]:
    """Pages a link or QR code can point at: home, booking, each area and neighborhood page, each service."""
    out = [{"path": "/", "label": "Home page"}, {"path": "/book", "label": "Booking form"}]
    out += [{"path": f"/local/{a.slug}", "label": f"{a.city} area page", "area": a.slug} for a in AREAS]
    out += [{"path": f"/local/{h.area}/{h.slug}", "label": f"{h.name} ({AREA_BY_SLUG[h.area].city})", "area": h.area} for h in HOODS]
    out += [{"path": f"/services/{s.slug}", "label": f"{s.name} page"} for s in SERVICES]
    return out


TARGET_PATHS = {t["path"] for t in targets()}


def tagged(site: str, path: str, ref: str) -> str:
    return f"{site}{path}?ref={ref}"


def qr_svg(url: str, dark: str = "#0F2B22") -> bytes:
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=10, dark=dark, light="#ffffff", border=2, xmldecl=False)
    return buf.getvalue()


def channel_of(source: str | None) -> str:
    if not source:
        return "Not tracked (typed the address or no tag)"
    if source in AUTO_SOURCES:
        return AUTO_SOURCES[source]
    for key, label in CHANNELS.items():
        if source == key or source.startswith(key + "-"):
            return label
    return source


def scoreboard(rows: list[dict], since: date) -> dict:
    """Bookings and booked revenue per channel and per exact tag since a date. Cancelled bookings don't count."""
    by_channel, by_tag = defaultdict(lambda: [0, 0.0]), defaultdict(lambda: [0, 0.0])
    for r in rows:
        if r.get("status") == "cancelled" or str(r.get("created_at", ""))[:10] < since.isoformat():
            continue
        amt = float(r.get("amount_due") or 0)
        for bucket, key in ((by_channel, channel_of(r.get("source"))), (by_tag, r.get("source") or "")):
            bucket[key][0] += 1
            bucket[key][1] += amt
    fmt = lambda d: sorted(({"name": k, "bookings": v[0], "booked": round(v[1], 2)} for k, v in d.items() if k),
                           key=lambda x: (-x["bookings"], x["name"]))
    return {"channels": fmt(by_channel), "tags": fmt(by_tag),
            "total": sum(v[0] for v in by_channel.values()), "booked": round(sum(v[1] for v in by_channel.values()), 2)}


def week_posts(settings: Settings, repo, site: str, today: date) -> list[dict]:
    """Ready-to-post copy for each area day in the next week that can still be booked: Facebook / Nextdoor,
    Instagram / TikTok and Google Business, in English and Spanish, each with its own tracking link."""
    low = dollars(price_range()[0])
    first = earliest_bookable_day(local_now(settings), settings.freeze_hour)
    out = []
    for i in range(1, 8):
        day = today + timedelta(days=i)
        zone = next((z for z in SERVICE_ZONES if z.service_weekday == day.weekday()), None)
        if zone is None or day < first:
            continue
        area = next((a for a in AREAS if a.zone_key == zone.key), None)
        if area is None:
            continue
        try:
            spots = max(0, settings.daily_job_quota - cached_count(repo, day))
        except Exception:
            spots = None
        name, wd = short_name(zone), WEEKDAY_NAMES[day.weekday()]
        when = f"{wd}, {day:%b} {day.day}"
        few = spots is not None and 0 < spots <= 8          # only mention the count when it's genuinely short
        open_en = f"only {spots} openings left" if few else "booking now"
        open_es = f"solo quedan {spots} lugares" if few else "reservando ahora"
        wd_es = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"][day.weekday()]
        link = lambda ch: tagged(site, f"/local/{area.slug}", f"{ch}-{area.slug}")
        tag = re.sub(r"[^A-Za-z]", "", area.city)
        save = f"Neighbors booked nearby save {percent(density_pct(2))}% ({percent(density_pct(5))}% with 5 or more)."
        save_es = f"Si sus vecinos ya reservaron cerca, ahorra {percent(density_pct(2))}% ({percent(density_pct(5))}% con 5 o más)."
        posts = [
            {"channel": "facebook", "label": "Facebook / Nextdoor", "en":
                f"{wd} is {name} day. Post One Lawn Co. is mowing in {name} on {when}, {open_en}. Lawn mowing from {low} "
                f"a visit, with the full price (tax included) shown before you book. {save} Veteran-owned, based in Spring. "
                f"Book in about a minute: {link('facebook')}",
             "es": f"El {wd_es} es día de {name}. Post One Lawn Co. corta céspedes en {name} el {wd_es} {day.day}, {open_es}. "
                   f"Desde {low} por visita, con el precio total (impuestos incluidos) antes de reservar. {save_es} "
                   f"Reserve en un minuto: {link('facebook')}"},
            {"channel": "instagram", "label": "Instagram / TikTok caption", "en":
                f"{name} lawns, {when}. {open_en.capitalize()}. From {low} a visit, price shown before you book. "
                f"Book at the link in our bio.\n#{tag}TX #LawnCare #LawnMowing #VeteranOwned #HoustonLawnCare",
             "es": f"Céspedes de {name}, {wd_es} {day.day}. {open_es.capitalize()}. Desde {low} por visita, precio antes de "
                   f"reservar. Reserve en el enlace de nuestro perfil.\n#{tag}TX #CorteDeCesped #LawnCare #Houston"},
            {"channel": "google-business", "label": "Google Business post (add the Book button)", "en":
                f"Mowing in {name} on {when}, {open_en}. Flat price from {low} per visit, shown with tax before you book. "
                f"No contract. Book online: {link('google-business')}",
             "es": f"Cortamos en {name} el {wd_es} {day.day}, {open_es}. Precio fijo desde {low} por visita, con impuestos, "
                   f"antes de reservar. Sin contrato. Reserve en línea: {link('google-business')}"},
        ]
        out.append({"date": day.isoformat(), "area": name, "slug": area.slug, "spots": spots, "posts": posts,
                    "instagram_link": link("instagram")})
    return out


def print_html(settings: Settings, version: str, site: str, kind: str, path: str, ref: str) -> str:
    """A print-ready yard sign, door hanger or flyer with the QR code, in the site's look."""
    target = next(t for t in targets() if t["path"] == path)
    area = AREA_BY_SLUG.get(target.get("area", ""))
    zone = zone_by_key(area.zone_key) if area else None
    url = tagged(site, path, ref)
    qr = qr_svg(url).decode()
    low = dollars(price_range()[0])
    day_line = f"We mow {area.city} every {WEEKDAY_NAMES[zone.service_weekday]}." if zone else "One area a day, north and northeast of Houston."
    save = f"Neighbors booked within half a mile save {percent(density_pct(2))}% ({percent(density_pct(5))}% with 5 or more)."
    short_url = url.split("://", 1)[-1]
    size = {"yard-sign": "18in 24in", "door-hanger": "4.25in 11in", "flyer": "letter"}[kind]
    if kind == "yard-sign":
        body = f"""<div class="pr pr-sign"><p class="pr-k">Lawn mowed by</p><p class="pr-brand">Post One<span>Lawn Co.</span></p>
          <p class="pr-line">{esc(day_line)}</p><div class="pr-qr">{qr}</div><p class="pr-cta">Scan for your price</p></div>"""
    elif kind == "door-hanger":
        body = f"""<div class="pr pr-hang"><div class="pr-hole"></div><p class="pr-k">Your neighbor's lawn was just mowed by</p>
          <p class="pr-brand">Post One<span>Lawn Co.</span></p><p class="pr-line">{esc(day_line)}</p>
          <p class="pr-sm">{esc(save)} Lawn mowing from {low} a visit, price shown with tax before you book.</p>
          <div class="pr-qr">{qr}</div><p class="pr-cta">Scan to book</p><p class="pr-url">{esc(short_url)}</p></div>"""
    else:
        body = f"""<div class="pr pr-flyer"><p class="pr-brand">Post One<span>Lawn Co.</span></p>
          <h1 class="pr-h">Lawn mowing{(' in ' + esc(area.city)) if area else ''}, from {low} a visit</h1>
          <ul class="pr-list"><li>{esc(day_line)}</li><li>Your full price, tax included, before you book. No contract.</li>
          <li>{esc(save)}</li><li>A text when the crew is on the way. Veteran-owned, based in Spring.</li></ul>
          <div class="pr-qr">{qr}</div><p class="pr-cta">Scan to see your price</p><p class="pr-url">{esc(short_url)}</p></div>"""
    style = f"""<style>
  @page {{ size: {size}; margin: 0; }}
  body {{ background: #fff; }}
  .site-header, .site-footer, .skip-link {{ display: none !important; }}
  .pr {{ margin: 0 auto; padding: 0.5in; text-align: center; color: #0F2B22; font-family: var(--font-body); }}
  .pr-brand {{ margin: 0.1in 0; font: 800 1in/0.9 var(--font-display); text-transform: uppercase; }}
  .pr-brand span {{ display: block; font-size: 0.42em; letter-spacing: 0.3em; color: #2E7D4F; }}
  .pr-k {{ margin: 0; font: 700 0.3in/1.2 var(--font-body); text-transform: uppercase; letter-spacing: 0.06em; }}
  .pr-line {{ font: 700 0.3in/1.25 var(--font-body); }}
  .pr-sm {{ font-size: 0.16in; line-height: 1.4; }}
  .pr-qr svg {{ width: 3in; height: 3in; }}
  .pr-cta {{ font: 800 0.4in/1 var(--font-display); text-transform: uppercase; }}
  .pr-url {{ font-size: 0.14in; color: #4A5650; }}
  .pr-sign {{ width: 18in; min-height: 24in; padding: 1in; border: 0.4in solid #0F2B22; }}
  .pr-sign .pr-brand {{ font-size: 3in; }} .pr-sign .pr-k, .pr-sign .pr-line {{ font-size: 0.8in; }}
  .pr-sign .pr-qr svg {{ width: 8in; height: 8in; }} .pr-sign .pr-cta {{ font-size: 1.2in; }}
  .pr-hang {{ width: 4.25in; min-height: 11in; padding: 0.3in; }}
  .pr-hang .pr-hole {{ width: 1.4in; height: 1.4in; margin: 0 auto 0.2in; border: 2px dashed #B9C2BC; border-radius: 50%; }}
  .pr-hang .pr-brand {{ font-size: 0.7in; }} .pr-hang .pr-line {{ font-size: 0.2in; }} .pr-hang .pr-qr svg {{ width: 2.2in; height: 2.2in; }}
  .pr-flyer {{ width: 8.5in; min-height: 11in; }}
  .pr-h {{ font: 800 0.6in/1 var(--font-display); text-transform: uppercase; margin: 0.2in 0; }}
  .pr-list {{ text-align: left; font-size: 0.2in; line-height: 1.5; max-width: 6in; margin: 0 auto 0.2in; }}
  .no-print {{ text-align: center; padding: 16px; }}
  @media print {{ .no-print {{ display: none; }} }}
</style>"""
    bar = '<p class="no-print"><button class="btn btn-primary" onclick="print()">Print</button></p>'
    return layout(settings, version, title=f"Print: {PRINTS[kind]} | {settings.business_name}", description="Print-ready marketing piece.",
                  body=bar + body, head_extra=style + '\n  <meta name="robots" content="noindex">', page="print")


def register_marketing(app: FastAPI, settings: Settings, owner, page, version: str = "") -> None:
    @app.get("/api/owner/marketing", dependencies=[Depends(owner)])
    def hub(request: Request):
        site = site_url(settings, request)
        today = local_now(settings).date()
        try:
            rows = app.state.repo.bookings_by_source(local_now(settings) - timedelta(days=90))
            tracked = True
        except Exception:                     # the source column needs the 2026-10-28 database update
            rows, tracked = [], False
        return {
            "tracking_ready": tracked,
            "last_30": scoreboard(rows, today - timedelta(days=30)),
            "last_90": scoreboard(rows, today - timedelta(days=90)),
            "posts": week_posts(settings, app.state.repo, site, today),
            "targets": targets(), "channels": CHANNELS, "prints": PRINTS, "site": site,
            "review_link": bool(review_link(settings)),
        }

    @app.get("/marketing/qr.svg", include_in_schema=False)
    def qr(request: Request, path: str = "/", ref: str = ""):
        if path not in TARGET_PATHS or (ref and not REF.match(ref)):
            raise HTTPException(status_code=404, detail="Unknown page")
        url = tagged(site_url(settings, request), path, ref) if ref else site_url(settings, request) + path
        return Response(qr_svg(url), media_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=86400", "Content-Disposition": f'inline; filename="post-one-{ref or "qr"}.svg"'})

    @app.get("/owner/marketing/print", include_in_schema=False)
    def printable(request: Request, kind: str = "flyer", path: str = "/", ref: str = "flyer"):
        if kind not in PRINTS or path not in TARGET_PATHS or not REF.match(ref):
            raise HTTPException(status_code=404, detail="Unknown print")
        return HTMLResponse(print_html(settings, version, site_url(settings, request), kind, path, ref),
                            headers={"Cache-Control": "no-cache", "X-Robots-Tag": "noindex"})

    @app.get("/owner/marketing", include_in_schema=False)
    def marketing_page():
        resp = page("marketing.html")
        resp.headers["X-Robots-Tag"] = "noindex"
        return resp
