"""Local service-area pages for search engines.

    GET /local                    "Areas we serve": a link to every area page
    GET /local/{area}             one page per area we mow (spring, klein, new-caney, cleveland, colony-ridge)
    GET /local/{area}/{anything}  301 to /local/{area}: street-level links fold into the area page
    GET /sitemap.xml              the public pages as absolute URLs (robots.txt points here)

Rendered on the server so crawlers see everything without JavaScript. Prices, tax, add-ons,
causes and the next open day are read live from the price list and settings, so the pages
change as soon as they do.

Privacy and search policy: these pages NEVER contain customer names, addresses, street names
from bookings, phone numbers or anything about a single job. They are built only from the
hand-written AREAS table below, the price list and settings. The only thing they read from the
database is how many jobs are booked on a day (so "next day you can book" skips full days).
We also do NOT make a page per street from bookings: that would publish where customers live,
and Google treats mass-produced, near-duplicate location pages as doorway pages (scaled
content abuse). One real page per area we actually serve.
"""

import html
import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from xml.sax.saxutils import escape as xml_escape

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .booking import earliest_bookable_day, local_now
from .charity import causes
from .config import Settings, site_url
from .pricing import (ADD_ONS, BRACKET_PROFILES, MAX_SQFT, PACKAGES, PRICE_BRACKETS, bracket_label, bracket_price,
                      bracket_profile, season_text)
from .zones import zone_by_key

esc = html.escape


@dataclass(frozen=True)
class Area:
    slug: str
    zone_key: str               # the service zone in app/zones.py
    city: str
    county: str
    zips: tuple[str, ...]       # only ZIPs named in that zone's comments
    places: tuple[str, ...]     # neighborhoods and roads named in that zone's comments
    intro: str                  # written for this page only: plain facts, no superlatives


AREAS: tuple[Area, ...] = (
    Area("spring", "SPRING_LUXURY_LOOP", "Spring", "Montgomery County", (),
         ("Woodson's Reserve", "SH-99", "Rayford Rd"),
         "We mow in Woodson's Reserve and the developments along SH-99 and Rayford Rd in Spring. "
         "These neighborhoods are on a set rotation, and every visit is booked and priced on its own."),
    Area("klein", "KLEIN_CORE", "Klein", "Harris County", ("77379", "77388"),
         ("FM 1960", "Champion Forest"),
         "Our Klein route covers the 77379 and 77388 ZIP codes, from FM 1960 north and from Champion Forest Dr "
         "east toward I-45. Stops are grouped by neighborhood, so the crew's time goes into lawns, not driving."),
    Area("new-caney", "I69_HIGH_DENSITY_SPINE", "New Caney", "Montgomery County", (),
         ("The Canopies", "Gemini", "Porters Mill", "Splendora"),
         "We mow in The Canopies, Gemini and Porters Mill in New Caney, and in Splendora to the north along I-69. "
         "Homes in these developments sit close together, so the crew can finish several lawns on a street "
         "before moving on."),
    Area("cleveland", "CLEVELAND_HUB", "Cleveland", "Liberty County", (),
         ("Grand Oaks Reserve", "Plum Grove", "FM 1010", "SH-105"),
         "Our Cleveland route covers Grand Oaks Reserve, the new construction off FM 1010 and SH-105, and "
         "Plum Grove in Liberty County. Lots here often run larger, so check the price table for your lawn "
         "size before you book."),
    Area("colony-ridge", "COLONY_RIDGE", "Colony Ridge", "Liberty County", (),
         ("Santa Fe", "Grand San Jacinto", "Montebello", "Camino Real", "Bella Vista"),
         "We mow in Colony Ridge in Liberty County, east of Plum Grove off FM 1010 and FM 2100, including the "
         "Santa Fe, Grand San Jacinto, Montebello, Camino Real and Bella Vista sections. When you book you can "
         "pick yard only or the full property, and that price is locked in."),
)
AREA_BY_SLUG = {a.slug: a for a in AREAS}
# Other names people search for, folded into the area page that covers them.
ALIASES = {"splendora": "new-caney", "plum-grove": "cleveland"}

for _a in AREAS:  # fail fast on a typo'd zone key
    if zone_by_key(_a.zone_key) is None:
        raise ValueError(f"{_a.slug}: unknown zone {_a.zone_key}")


def resolve(slug: str) -> str | None:
    """The area slug a URL points at (aliases and capitals folded in), or None if we don't serve it."""
    key = ALIASES.get(slug.lower(), slug.lower())
    return key if key in AREA_BY_SLUG else None


# ---------- Prices, read live from app/pricing.py ----------------------
def dollars(amount: Decimal) -> str:
    """$75 or $75.50: whole dollars drop the cents."""
    return f"${amount:,.0f}" if amount == amount.to_integral_value() else f"${amount:,.2f}"


def percent(rate) -> str:
    """0.0825 → "8.25", 0.02 → "2"."""
    text = f"{Decimal(str(rate)) * 100:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def price_rows() -> list[tuple[str, dict[str, Decimal]]]:
    """(lawn size in words, {tier: price before tax}) for each row of PRICE_BRACKETS."""
    rows, low = [], 0
    for limit, prices in PRICE_BRACKETS:
        rows.append((bracket_label(limit if limit is not None else low + 1), prices))
        low = limit if limit is not None else low
    return rows


def next_open_day(settings: Settings, repo) -> date:
    """The first day after the 5 PM cutoff that still has room. Reads only how many jobs a day has."""
    now = local_now(settings)
    day = earliest_bookable_day(now, settings.freeze_hour)
    last = now.date() + timedelta(days=settings.booking_horizon_days)
    try:
        while day < last and repo.count_active_jobs(day) >= settings.daily_job_quota:
            day += timedelta(days=1)
    except Exception:          # never fail the page over this
        pass
    return day


def cause_names(settings: Settings) -> list[str]:
    """The causes by name. A real organization is named only once the owner has set its name;
    until then it gets a plain description (these pages are public and indexed)."""
    generic = {"vfw": "Local veterans and their families"}
    return [generic[c["key"]] if c["key"] in generic and c["name"] == Settings.model_fields[f"charity_{c['key']}_name"].default
            else c["name"] for c in causes(settings)]


def price_range() -> tuple[Decimal, Decimal]:
    every = [p for _, prices in PRICE_BRACKETS for p in prices.values()]
    return min(every), max(every)


def add_on_rows() -> list[tuple[str, str]]:
    """(label, price in words) for add-ons with a price or a free quote. Yard / full property are not add-ons."""
    rows = []
    for key, a in ADD_ONS.items():
        if a.get("scope"):
            continue
        if a.get("quote"):
            season = season_text(key)
            rows.append((a["label"], "Free quote" + (f" · {season}" if season else "")))
        elif a["price"] and a["price"] > 0:
            rows.append((a["label"], f"+{dollars(a['price'])} per visit"))
    return rows


def hour_words(h: int) -> str:
    return f"{(h + 11) % 12 + 1} {'AM' if h < 12 else 'PM'}"


def joined(words) -> str:
    """"a, b and c"."""
    words = list(words)
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


# ---------- Structured data (JSON-LD) ----------------------------------
def script_json(data: dict) -> str:
    """JSON that is safe inside <script>: <, > and & are escaped, so no value (a business name) can end the tag."""
    return json.dumps(data).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def structured_data(settings: Settings, area: Area, site: str) -> dict:
    """LocalBusiness + this area's mowing Service with every price + breadcrumbs. No street address,
    phone or ratings: we don't publish an address, have no business phone setting, and Google
    forbids self-serving review markup."""
    business_id = f"{site}/#business"
    page_url = f"{site}/local/{area.slug}"
    low, high = price_range()
    offers = [{"@type": "Offer", "name": f"{p['label']}: {size}", "price": f"{prices[k]:.2f}", "priceCurrency": "USD"}
              for size, prices in price_rows() for k, p in PACKAGES.items()]
    return {"@context": "https://schema.org", "@graph": [
        {"@type": "LocalBusiness", "@id": business_id, "name": settings.business_name, "url": f"{site}/",
         "description": "Veteran-owned lawn mowing with bin and gutter cleaning add-ons, booked online, "
                        "on planned neighborhood routes north and northeast of Houston.",
         "image": f"{site}/static/icons/social.jpg",
         "address": {"@type": "PostalAddress", "addressLocality": "Spring", "addressRegion": "TX", "addressCountry": "US"},
         "areaServed": [{"@type": "City", "name": f"{a.city}, TX"} for a in AREAS],
         "priceRange": f"{dollars(low)}-{dollars(high)}"},
        {"@type": "Service", "@id": f"{page_url}#service", "serviceType": "Lawn mowing",
         "name": f"Lawn mowing in {area.city}, TX", "url": page_url, "provider": {"@id": business_id},
         "areaServed": {"@type": "City", "name": f"{area.city}, TX"},
         "hasOfferCatalog": {"@type": "OfferCatalog", "name": "Mowing price per visit, before tax",
                             "itemListElement": offers}},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{site}/"},
            {"@type": "ListItem", "position": 2, "name": "Areas we serve", "item": f"{site}/local"},
            {"@type": "ListItem", "position": 3, "name": f"{area.city}, TX", "item": page_url}]},
    ]}


# ---------- Page pieces (same header, footer and styles as the rest of the site) ----------
def layout(settings: Settings, version: str, *, title: str, description: str, body: str,
           canonical: str | None = None, og_image: str | None = None, head_extra: str = "") -> str:
    name = esc(settings.business_name)
    meta = ""
    if canonical:
        meta += f"""
  <link rel="canonical" href="{esc(canonical)}">
  <meta property="og:url" content="{esc(canonical)}">"""
    if og_image:
        meta += f'\n  <meta property="og:image" content="{esc(og_image)}">'
    areas = "\n".join(f'        <a href="/local/{a.slug}">{esc(a.city)}</a>' for a in AREAS)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(description)}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:type" content="website">{meta}
  <meta name="theme-color" content="#0b3d2e">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="icon" href="/favicon.ico" sizes="any">
  <link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
  <link rel="stylesheet" href="/static/styles.css?v={esc(version)}">
  <script src="/static/i18n.js?v={esc(version)}"></script>{head_extra}
</head>
<body class="site local">
  <a class="skip-link" href="#main">Skip to content</a>
  <header class="site-header">
    <div class="site-wrap header-row">
      <a class="brand" href="/">
        <img src="/static/icons/logo-64.png" alt="" width="32" height="32">
        <span>{name}</span>
      </a>
      <nav class="site-nav" aria-label="Main">
        <a href="/#services">Services</a>
        <a href="/local">Service areas</a>
        <a href="/team">Meet the crew</a>
      </nav>
      <a class="btn btn-primary btn-sm header-cta" href="/book">Book now</a>
    </div>
  </header>

  <main id="main">{body}
  </main>

  <footer class="site-footer">
    <div class="site-wrap footer-grid">
      <div>
        <a class="brand footer-brand" href="/">
          <img src="/static/icons/logo-64.png" alt="" width="28" height="28">
          <span>{name}</span>
        </a>
        <p class="footer-tagline">Clean lawns. Stronger communities.</p>
        <p>Veteran-owned · Spring, TX</p>
      </div>
      <nav aria-label="Footer">
        <a href="/book">Book a service</a>
        <a href="/#services">Services</a>
        <a href="/local">Service areas</a>
        <a href="/team">Meet the crew</a>
        <a href="/visit">View my visit</a>
      </nav>
      <nav class="footer-areas" aria-label="Areas we serve">
        <a class="footer-areas-title" href="/local">Areas we serve</a>
{areas}
      </nav>
      <p class="footer-copy">© {local_now(settings).year} {name}</p>
    </div>
  </footer>

  <script src="/static/site.js?v={esc(version)}"></script>
  <script src="/static/tracker.js?v={esc(version)}" defer></script>
</body>
</html>
"""


def crumbs(trail: list[tuple[str, str | None]]) -> str:
    items = "".join(f'<li><a href="{href}">{esc(label)}</a></li>' if href else f'<li aria-current="page">{esc(label)}</li>'
                    for label, href in trail)
    return f'<nav class="crumbs" aria-label="Breadcrumb"><ol>{items}</ol></nav>'


def cta_band(heading: str) -> str:
    return f"""
    <section class="section final-cta" aria-labelledby="cta-title">
      <div class="site-wrap">
        <div class="cta-band">
          <div>
            <h2 id="cta-title">{esc(heading)}</h2>
            <p>Booking takes about a minute, and you'll see your full price with tax before you book.</p>
          </div>
          <a class="btn btn-primary btn-lg" href="/book">Book online</a>
        </div>
      </div>
    </section>"""


def trust_items(settings: Settings) -> list[tuple[str, str]]:
    """Why book with us. Insurance and background checks are listed ONLY when the owner has set them."""
    items = [("Veteran-owned", "A local business owned and led by a veteran."),
             ("Planned daily routes", "Each day's route is planned the evening before, stop by stop."),
             ("Live visit page", "An alert when the crew is on the way, and a live page for every visit.")]
    if settings.crew_background_checked:
        items.append(("Background-checked crew", "Every crew member has passed a background check."))
    if coverage := settings.liability_coverage.strip():
        items.append((f"{coverage} liability coverage", "Commercial liability coverage while we're on your property."))
    return items


# ---------- Pages ------------------------------------------------------
def area_html(settings: Settings, version: str, area: Area, site: str, day: date) -> str:
    zone = zone_by_key(area.zone_key)
    city = esc(area.city)
    page_url = f"{site}/local/{area.slug}"
    low, _ = price_range()

    tiers = list(PACKAGES.items())
    head = "".join(f'<th scope="col">{esc(p["label"])}</th>' for _, p in tiers)
    rows = "".join(f'\n              <tr><th scope="row">{esc(size)}<small>{esc(profile)}</small></th>'
                   + "".join(f'<td data-label="{esc(p["label"])}">{dollars(prices[k])}</td>' for k, p in tiers)
                   + "</tr>" for (size, prices), profile in zip(price_rows(), BRACKET_PROFILES))
    add_ons = "".join(f"<li><strong>{esc(label)}</strong><span>{esc(price)}</span></li>" for label, price in add_on_rows())
    giving = joined(f"{percent(p['giving'])}% on {p['label']}" for p in PACKAGES.values())
    cause_list = "".join(f"<li>{esc(name)}</li>" for name in cause_names(settings))
    # Facts that really differ by area: the size "Full property" is priced at, county, ZIPs, tax.
    full = zone.full_property_sqft
    full_prices = " / ".join(dollars(bracket_price(full, k)) for k in PACKAGES)
    facts = "".join(f"<li><strong>{esc(k)}</strong><span>{esc(v)}</span></li>" for k, v in (
        ("County", area.county),
        *((("ZIP codes", ", ".join(area.zips)),) if area.zips else ()),
        ("“Full property” is priced at", f"about {full:,} sq ft ({bracket_profile(full)}): {full_prices} before tax"),
        ("“Yard only” is priced at", "the typical yard size here; the booking form shows it for your address"),
        ("Sales tax", f"{percent(zone.tax_rate)}%")))
    places = "".join(f"<li>{esc(p)}</li>" for p in area.places)
    trust = "".join(f"<li><div><strong>{esc(t)}</strong><span>{esc(d)}</span></div></li>" for t, d in trust_items(settings))
    others = "".join(f'<li><a href="/local/{a.slug}">Lawn mowing in {esc(a.city)}, TX</a></li>' for a in AREAS if a is not area)
    acres = f"{MAX_SQFT / 43_560:g}"

    body = f"""
    <section class="hero local-hero" aria-labelledby="area-title">
      <div class="site-wrap hero-grid">
        <div class="hero-copy">
          {crumbs([("Home", "/"), ("Areas we serve", "/local"), (area.city, None)])}
          <p class="eyebrow">Veteran-owned · Based in Spring, TX · Serving {city}</p>
          <h1 id="area-title">Lawn mowing in {city}, TX</h1>
          <p class="lede">{esc(area.intro)}</p>
          <div class="hero-actions">
            <a class="btn btn-primary btn-lg" href="/book">Book online</a>
            <a class="btn btn-lg btn-quiet" href="#prices">See prices</a>
          </div>
        </div>
        <aside class="card next-open" aria-label="Next service day you can book">
          <p class="eyebrow">Next day you can book</p>
          <p class="next-day">{day:%A, %B} {day.day}</p>
          <p class="hint">Next-day booking closes at {hour_words(settings.freeze_hour)}.</p>
          <a class="btn btn-primary btn-block" href="/book">Book this day</a>
        </aside>
      </div>
    </section>

    <section class="section" aria-labelledby="where-title">
      <div class="site-wrap">
        <h2 id="where-title">Where we mow</h2>
        <ul class="spec-list">{places}</ul>
        <h3>{city} at a glance</h3>
        <ul class="local-list local-facts">{facts}</ul>
        <p class="section-lede local-check">Not sure you're on our route? The booking form checks your address before
          you book, or you can <a href="/#areas">check your address</a> on the home page.</p>
      </div>
    </section>

    <section class="section" id="prices" aria-labelledby="prices-title">
      <div class="site-wrap">
        <h2 id="prices-title">Mowing prices (the same in every area we serve)</h2>
        <p class="section-lede">A flat price per visit, set by your lawn size and the rate you pick. Prices are before tax.</p>
        <div class="card price-card">
          <table class="price-table">
            <caption class="visually-hidden">Mowing price per visit by lawn size and rate, before tax</caption>
            <thead><tr><th scope="col">Lawn size</th>{head}</tr></thead>
            <tbody>{rows}
            </tbody>
          </table>
        </div>
        <p class="tax-note">{percent(zone.tax_rate)}% Texas sales tax added.</p>
        <p class="hint">The mowing is the same on every rate; they differ in price and in how much goes to charity.
          Lawns over {MAX_SQFT:,} sq ft ({acres} acres) are quoted in person.</p>
        <h3>Add to any mowing visit</h3>
        <ul class="local-list">{add_ons}</ul>
        <p class="hint">Add-on prices are before tax too.</p>
      </div>
    </section>

    <section class="section" aria-labelledby="giving-title">
      <div class="site-wrap">
        <h2 id="giving-title">Giving back</h2>
        <p class="section-lede">Part of every visit's price goes to the cause you pick when you book: {esc(giving)}.
          It's included in the price shown, not added on top. Higher rates cost more and give a bigger share.</p>
        <ul class="spec-list">{cause_list}</ul>
      </div>
    </section>

    <section class="section" aria-labelledby="why-title">
      <div class="site-wrap">
        <h2 id="why-title">Why book with us</h2>
        <ul class="trust-strip local-trust">{trust}</ul>
      </div>
    </section>
{cta_band("Book your mow online.")}

    <section class="section" aria-labelledby="other-title">
      <div class="site-wrap">
        <h2 id="other-title">Other areas we serve</h2>
        <ul class="area-links">{others}</ul>
        <p><a class="btn btn-outline" href="/local">All areas we serve</a></p>
      </div>
    </section>"""

    title = f"Lawn Mowing in {area.city}, TX | {settings.business_name}"
    description = (f"Lawn mowing in {area.city}, TX: {joined(area.places[:3])}. "
                   f"Flat prices from {dollars(low)} a visit before tax. Veteran-owned. Book online.")
    ld = f'\n  <script type="application/ld+json">{script_json(structured_data(settings, area, site))}</script>'
    return layout(settings, version, title=title, description=description, body=body, canonical=page_url,
                  og_image=f"{site}/static/icons/social.jpg", head_extra=ld)


def index_html(settings: Settings, version: str, site: str) -> str:
    low, _ = price_range()
    cards = "".join(f"""
          <li><a class="card local-card" href="/local/{a.slug}">
            <strong>Lawn mowing in {esc(a.city)}, TX</strong>
            <span>{esc(" · ".join(a.places))}</span>
            <span class="local-card-cta">See prices and the next open day</span>
          </a></li>""" for a in AREAS)
    body = f"""
    <section class="section local-index" aria-labelledby="areas-title">
      <div class="site-wrap">
        {crumbs([("Home", "/"), ("Areas we serve", None)])}
        <p class="eyebrow">Veteran-owned · Spring, TX area</p>
        <h1 class="page-title" id="areas-title">Areas we serve</h1>
        <p class="section-lede">We mow on set neighborhood routes north and northeast of Houston. Pick your area to see
          the neighborhoods we cover, flat prices from {dollars(low)} per visit before tax, and the next day you can book.</p>
        <ul class="local-grid">{cards}
        </ul>
      </div>
    </section>
{cta_band("Put your lawn on the route.")}"""
    cities = joined(f"{a.city}" for a in AREAS)
    return layout(settings, version, title=f"Areas We Serve | {settings.business_name}",
                  description=f"Lawn mowing in {cities}, TX: the neighborhoods we cover and flat per-visit prices for each area.",
                  body=body, canonical=f"{site}/local", og_image=f"{site}/static/icons/social.jpg")


def not_found_html(settings: Settings, version: str) -> str:
    # The requested name is never echoed back.
    body = """
    <section class="section" aria-labelledby="nf-title">
      <div class="site-wrap">
        <h1 class="page-title" id="nf-title">We don't have a page for that area</h1>
        <p class="section-lede">We may still mow there. See the areas we serve, or start a booking: the booking form
          checks your address before you book.</p>
        <div class="hero-actions">
          <a class="btn btn-primary btn-lg" href="/local">Areas we serve</a>
          <a class="btn btn-lg btn-quiet" href="/book">Book online</a>
        </div>
      </div>
    </section>"""
    return layout(settings, version, title=f"Area not found | {settings.business_name}",
                  description="See the areas we serve.", body=body)


def register_local_pages(app: FastAPI, settings: Settings, version: str = "") -> None:
    """/local pages and /sitemap.xml. `version` is the static-file hash for the stylesheet link."""

    def html_page(text: str, status_code: int = 200) -> HTMLResponse:
        return HTMLResponse(text, status_code=status_code, headers={"Cache-Control": "no-cache"})

    @app.get("/local", include_in_schema=False)
    def areas_index(request: Request):
        return html_page(index_html(settings, version, site_url(settings, request)))

    @app.get("/local/", include_in_schema=False)
    def areas_index_slash():
        return RedirectResponse("/local", status_code=301)

    @app.get("/local/{slug}", include_in_schema=False)
    def area_page(slug: str, request: Request):
        target = resolve(slug)
        if target is None:
            return html_page(not_found_html(settings, version), 404)
        if target != slug:
            return RedirectResponse(f"/local/{target}", status_code=301)
        return html_page(area_html(settings, version, AREA_BY_SLUG[target], site_url(settings, request),
                                   next_open_day(settings, request.app.state.repo)))

    @app.get("/local/{slug}/{rest:path}", include_in_schema=False)
    def street_page(slug: str, rest: str):
        # Street-level URLs fold into the area page: we never publish streets.
        target = resolve(slug)
        if target is None:
            return html_page(not_found_html(settings, version), 404)
        return RedirectResponse(f"/local/{target}", status_code=301)

    @app.get("/local/{rest:path}", include_in_schema=False)
    def odd_local_path(rest: str):
        # Anything else under /local (e.g. a doubled slash): the area page if one is named, else the friendly 404.
        target = next((resolve(part) for part in rest.split("/") if part), None)
        if target is None:
            return html_page(not_found_html(settings, version), 404)
        return RedirectResponse(f"/local/{target}", status_code=301)

    @app.get("/sitemap.xml", include_in_schema=False)
    def sitemap(request: Request):
        site = site_url(settings, request)
        paths = ["/", "/book", "/team", "/local", *(f"/local/{a.slug}" for a in AREAS)]
        urls = "".join(f"  <url><loc>{xml_escape(site + p)}</loc></url>\n" for p in paths)
        body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n')
        return Response(body, media_type="application/xml")
