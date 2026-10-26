"""Marketing hub: know which flyer, sign or post brings bookings, and have this week's posts written for you.

    GET /owner/marketing                     the hub (owner sign-in from the crew app)
    GET /api/owner/marketing                 scoreboard, this week's posts, link targets, channel list
    GET /marketing/qr.svg?path=&ref=         QR code for one of our own pages with a ?ref= tag (public: it's for print)
    GET /owner/marketing/print?kind=&path=&ref=   print-ready yard sign, door hanger or flyer with that QR code

Everything is built from the real data: prices from app/pricing.py, areas and days from app/zones.py, open spots
from the bookings. Tracking is a short ?ref= label on the link (e.g. "yard-sign-klein"), carried into the booking
by static/site.js. No personal data is collected, and nothing here claims more than the business does.
"""

import hashlib
import html
import io
import re
from collections import defaultdict
from datetime import date, timedelta

import segno
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from .booking import cached_count, earliest_bookable_day, local_now, preorder_count, preorders_open, service_floor
from .config import Settings, site_url
from .local_pages import AREA_BY_SLUG, AREAS, HOODS, area_card_path, dollars, layout, percent, price_range
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
    "poster": "Service map poster",
}
# Labels the site sets on its own from where a visitor came from (static/site.js).
AUTO_SOURCES = {"google": "Google search", "bing": "Bing search", "yelp": "Yelp", "ai-chatgpt": "ChatGPT",
                "ai-perplexity": "Perplexity", "ai-assistant": "Other AI assistant",
                "rebook": "Repeat customer (Book your next mow)"}
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


def business_facts(settings: Settings, site: str) -> str:
    """What an AI assistant may say about Post One, from live data and the owner's settings. Every prompt in the
    pack carries it, so drafts quote the real areas, days, prices and policy instead of inventing them."""
    low, high = (dollars(x) for x in price_range())
    days = "; ".join(f"{WEEKDAY_NAMES[z.service_weekday]}: {short_name(z)}"
                     for z in sorted(SERVICE_ZONES, key=lambda z: z.service_weekday))
    pay = ("Customers pay by card, Apple Pay or Google Pay when they book; the crew only goes to paid visits."
           if settings.prepay_required and settings.stripe_enabled else "Payment is taken by card or cash.")
    contact = ", ".join(x for x in (settings.business_email, settings.business_phone) if x) or "reply to any of our texts"
    lines = [
        f"- Business: {settings.business_name} (operated by {settings.legal_name}), veteran-owned lawn mowing based in "
        f"Spring, TX. Website: {site}",
        "- Service: residential lawn mowing. Bin cleaning and gutter cleaning are add-ons to a mowing visit. "
        "Holiday lighting is by quote only, in season.",
        f"- One area a day: {days}. Saturday is for weather make-ups only. Sunday off.",
        f"- Price: {low} to {high} a visit before tax, set by lawn size and yard type. The full price with tax is shown "
        "before booking. No contract or subscription. The price is locked: we never charge more on site without the "
        "customer's OK.",
        f"- Neighbor discount: {percent(density_pct(2))}% off the mowing with 2-4 customers booked within half a mile, "
        f"{percent(density_pct(5))}% with 5 or more.",
        f"- {pay}",
        "- Cancel free, with a full refund, until we text that the crew is on the way; after that text, no refund.",
        "- Weather: we mow through light rain. Lightning, heavy rain or soft ground moves the visit to a make-up day "
        "(usually Saturday), or a full refund if that day doesn't work.",
        "- Locked out (locked gate, loose pet, blocked lawn): the parts we couldn't reach are not refunded.",
        "- Not happy: tell us within 48 hours; we come back and fix it at no charge; if it's still not right, a full "
        "refund for that visit.",
        f"- Insurance: {settings.liability_coverage} in general liability." if settings.liability_coverage.strip()
        else "- Insurance: never mention it.",
        "- Crew background checks: every crew member has passed one." if settings.crew_background_checked
        else "- Background checks: never mention them.",
        f"- How customers reach us: {contact}.",
    ]
    rules = ("Rules: plain, short, friendly sentences. Write as \"we\" to \"you\". No military jargon or role-play. "
             "No emoji unless I ask. Never invent reviews, ratings, numbers, prices, discounts or promises: use only "
             "the facts above, and if something isn't covered, say we'll check and get back to them. "
             "In Spanish use \"usted\".")
    return "Facts about the business (use only these):\n" + "\n".join(lines) + "\n\n" + rules


PROMPTS = (
    ("review", "Reply to a Google review", "Someone left a review, good or bad.",
     "Write a short public reply (2 to 4 sentences) to this Google review of our lawn mowing business. Thank them by "
     "first name. If it's negative, own the specific problem, say what we'll do about it within the policy below, and "
     "ask them to reply to our texts so we can fix it. Don't offer a discount or a free mow unless I add one here: "
     "[OPTIONAL: what I'm offering].\n\nThe review:\n[PASTE THE REVIEW]"),
    ("customer", "Answer a customer", "A text or email asking about price, a day, rain, a refund or a problem.",
     "Draft my reply to this customer message, as a text under 320 characters (or a short email if they emailed). "
     "Answer exactly what they asked, using only the policy below. If they want something the policy doesn't allow, "
     "say no kindly and offer what it does allow.\n\nTheir message:\n[PASTE THEIR MESSAGE]"),
    ("partner", "Email a property manager or HOA", "Reaching out to a business that manages homes in our areas.",
     "Write a cold email (under 120 words) to this property manager or HOA management company. Open with one specific "
     "detail from their website, then explain how a set mowing day for their homes in our areas, the price shown up "
     "front and before/after photos make their job easier. Ask for a 10-minute call. Don't claim we already work with "
     "anyone. Leave a line at the end for our postal address and an unsubscribe sentence (required by law before "
     "sending).\n\nTheir company and what their website says:\n[PASTE NAME, AREA AND A DETAIL FROM THEIR SITE]"),
    ("video", "Caption a before & after video", "Posting a Reel, TikTok or Short from a job.",
     "Write a caption for a short before & after mowing video: a hook first line under 8 words, one line on what we "
     "did, the area and its mowing day, \"book at the link in our bio\", and 5 hashtags. Then the same caption in "
     "Spanish. Never name the customer or show their address.\n\nWhat's in the video:\n[DESCRIBE THE VIDEO AND THE AREA]"),
    ("spanish", "Translate into Spanish", "Any message, post or sign for Spanish-speaking customers.",
     "Translate this into natural Spanish as spoken in the Houston area, using \"usted\". Keep prices, dates, links "
     "and our name exactly as they are. Make it sound written in Spanish, not translated.\n\nThe text:\n[PASTE THE TEXT]"),
    ("week", "Plan next week from the scoreboard", "Once a week, after checking where bookings came from.",
     "Here are my booking numbers by channel from my marketing scoreboard. Give me 3 specific things to do next week, "
     "most important first, each one sentence, based only on these numbers and the facts below. If the numbers are "
     "too small to tell, say so.\n\nMy numbers:\n[PASTE \"WHERE BOOKINGS COME FROM\" AND \"BEST LINKS AND SIGNS\"]"),
)


def prompt_pack(settings: Settings, site: str) -> list[dict]:
    """Copy-ready prompts for ChatGPT, Claude or any assistant: the owner's recurring writing jobs, each with the live
    facts and rules attached. Fill in the [BRACKETS] and send."""
    facts = business_facts(settings, site)
    return [{"key": k, "title": t, "when": w, "prompt": f"{task}\n\n{facts}"} for k, t, w, task in PROMPTS]


def poster_path(ext: str = "jpg") -> str:
    """The service map poster (tools/make_area_poster.py). Its name carries a fingerprint of the areas, boxes and days,
    so a schedule change can't keep offering an old poster: tests/test_area_cards.py fails until it is made again."""
    plan = repr(sorted((z.key, z.service_weekday, z.boxes) for z in SERVICE_ZONES)).encode()
    return f"/static/img/service-map-{hashlib.sha256(plan).hexdigest()[:8]}.{ext}"


def preorder_info(settings: Settings, repo) -> dict:
    """For the owner: are pre-orders open (LAUNCH_DATE), and how many are booked (the real count, however small)."""
    now = local_now(settings)
    if not preorders_open(now, settings):
        return {"open": False}
    try:
        count = preorder_count(repo, now, settings)
    except Exception:
        count = None
    return {"open": True, "launch_date": settings.launch_date.isoformat(), "count": count}


def target_data_path() -> str:
    """Where to knock first (tools/make_target_map.py): Census block groups in our areas, ranked. Fingerprinted on
    the areas, boxes and days like the poster, so tests/test_target_map.py fails until it is made again."""
    plan = repr(sorted((z.key, z.service_weekday, z.boxes) for z in SERVICE_ZONES)).encode()
    return f"/static/data/targets-{hashlib.sha256(plan).hexdigest()[:8]}.json"


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
    first = earliest_bookable_day(local_now(settings), settings.freeze_hour, service_floor(local_now(settings), settings))
    start = max(today, first - timedelta(days=1))      # while pre-orders are open: the opening week's area days
    preorder = preorders_open(local_now(settings), settings)
    out = []
    for i in range(1, 8):
        day = start + timedelta(days=i)
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
        open_en = (f"only {spots} openings left" if few else
                   "pre-orders open for our first week (cancel free until we're on the way)" if preorder else "booking now")
        open_es = (f"solo quedan {spots} lugares" if few else
                   "reservas abiertas para nuestra primera semana (cancele gratis hasta que vayamos en camino)"
                   if preorder else "reservando ahora")
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
            "map_cards": [{"area": short_name(zone_by_key(a.zone_key)),
                           "day": WEEKDAY_NAMES[zone_by_key(a.zone_key).service_weekday],
                           "square": area_card_path(a, square=True), "wide": area_card_path(a)} for a in AREAS],
            "poster": {"jpg": poster_path("jpg"), "pdf": poster_path("pdf")},
            "preorders": preorder_info(settings, app.state.repo),
            "prompts": prompt_pack(settings, site),
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

    @app.get("/api/owner/targets", dependencies=[Depends(owner)])
    def target_data():
        return {"data_url": target_data_path()}

    @app.get("/owner/targets", include_in_schema=False)
    def targets_page():
        resp = page("targets.html")
        resp.headers["X-Robots-Tag"] = "noindex"
        return resp

    @app.get("/owner/marketing", include_in_schema=False)
    def marketing_page():
        resp = page("marketing.html")
        resp.headers["X-Robots-Tag"] = "noindex"
        return resp
