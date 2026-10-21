"""Local service-area pages for search engines.

    GET /local                    "Areas we serve": a link to every area page
    GET /local/{area}             one page per area we mow (spring, klein, new-caney, cleveland, colony-ridge)
    GET /local/{area}/{hood}      one page per neighborhood we mow in that area (hand-written, see HOODS)
    GET /local/{hood}             301 to /local/{area}/{hood}
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
content abuse). One real page per area we actually serve, plus a page for each named neighborhood
in HOODS: a short hand-written list of subdivisions inside the zone boxes, each with its own text.
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
from .pricing import (ADD_ONS, MAX_SQFT, YARD_TYPES, YIELD_GIVING_RATE, YIELD_INCLUDED_SQFT, bracket_profile,
                      density_pct, season_text, yield_mow_fee)
from .zones import WEEKDAY_NAMES, zone_by_key

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


@dataclass(frozen=True)
class Hood:
    slug: str
    area: str                   # the Area slug it belongs to
    name: str                   # must also be listed in that Area's places
    intro: str                  # written for this page only: where it is and what a visit there looks like


# Only subdivisions named in the zone boxes of app/zones.py. No streets, nothing from bookings.
HOODS: tuple[Hood, ...] = (
    Hood("woodsons-reserve", "spring", "Woodson's Reserve",
         "Woodson's Reserve is the center of our Spring route, near SH-99 and Rayford Rd. Monday is Spring day, so "
         "every lawn we mow here is cut the same day, one street after the next, by a crew that stays in the area."),
    Hood("the-canopies", "new-caney", "The Canopies",
         "The Canopies sits on the west side of our New Caney route. The homes are newer and close together, which keeps "
         "the drive between lawns short and the crew's time on mowing."),
    Hood("porters-mill", "new-caney", "Porters Mill",
         "Porters Mill is one of the New Caney developments on our Wednesday route, along with The Canopies and "
         "Splendora. Book once for a single mow, or keep booking on Wednesdays; there is no contract either way."),
    Hood("grand-oaks-reserve", "cleveland", "Grand Oaks Reserve",
         "Grand Oaks Reserve is on our Friday Cleveland route with the new construction off FM 1010 and SH-105. "
         "New-build yards often have fresh sod and bare edges, so tell us in the booking notes if anything needs extra care."),
    Hood("santa-fe", "colony-ridge", "Santa Fe",
         "Santa Fe is the southern end of our Colony Ridge route. Colony Ridge lots often run large, so the booking form lets you "
         "choose yard only or the full property, and the price you see is locked in."),
    Hood("grand-san-jacinto", "colony-ridge", "Grand San Jacinto",
         "Grand San Jacinto sits between Santa Fe and Montebello on our Thursday Colony Ridge route. Pick yard only "
         "to keep the area around the house mowed, or full property for the whole lot."),
    Hood("montebello", "colony-ridge", "Montebello",
         "Montebello is in the middle of our Colony Ridge route. Thursday is Colony Ridge day, so the "
         "crew works through Montebello and the sections around it without driving back and forth."),
    Hood("camino-real", "colony-ridge", "Camino Real",
         "Camino Real is on the north side of our Colony Ridge route. With neighbors booked close by, "
         "the mowing price drops automatically; the booking form shows the discount before you book."),
    Hood("bella-vista", "colony-ridge", "Bella Vista",
         "Bella Vista is the farthest north section on our Colony Ridge route. It is still mowed on Thursdays with "
         "the rest of Colony Ridge, so you get the same price and the same day as everyone else in the area."),
)
HOOD_BY_SLUG = {h.slug: h for h in HOODS}

for _h in HOODS:  # fail fast on a neighborhood that isn't on its area's list
    if _h.area not in AREA_BY_SLUG or _h.name not in AREA_BY_SLUG[_h.area].places:
        raise ValueError(f"{_h.slug}: not one of {_h.area}'s places")


def hoods_in(area: Area) -> list[Hood]:
    return [h for h in HOODS if h.area == area.slug]


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


SAMPLE_SIZES = (5_000, 7_500, 10_000, 15_000, 20_000)   # rows of the price table


def price_rows() -> list[tuple[str, int, dict[str, Decimal]]]:
    """(lawn size in words, sq ft, {yard type: price before tax}) from the yield engine the booking form charges."""
    return [(f"Up to {n:,} sq ft" if n == YIELD_INCLUDED_SQFT else f"{n:,} sq ft", n,
             {k: yield_mow_fee(n, k) for k in YARD_TYPES}) for n in SAMPLE_SIZES]


def next_open_day(settings: Settings, repo, zone=None) -> date:
    """The first day after the 5 PM cutoff that still has room (for one area: its next area day, a week apart).
    Reads only how many jobs a day has."""
    now = local_now(settings)
    day = earliest_bookable_day(now, settings.freeze_hour)
    if zone is not None:
        day += timedelta(days=(zone.service_weekday - day.weekday()) % 7)
    step = timedelta(days=7 if zone is not None else 1)
    last = now.date() + timedelta(days=settings.booking_horizon_days)
    try:
        while day < last and repo.count_active_jobs(day) >= settings.daily_job_quota:
            day += step
    except Exception:          # never fail the page over this
        pass
    return day


def cause_names(settings: Settings) -> list[str]:
    """The causes by name. A real organization is named only once the owner has set its name;
    until then it gets a plain description (these pages are public and indexed)."""
    generic = {"vfw": "Local veterans and their families"}
    return [generic[c["key"]] if c["key"] in generic and c["name"] == Settings.model_fields[f"charity_{c['key']}_name"].default
            else c["name"] for c in causes(settings)]


def price_table() -> str:
    """The mowing price table (lawn size × yard type, before tax), shared by the area and service pages."""
    tiers = list(YARD_TYPES.items())
    head = "".join(f'<th scope="col">{esc(y["label"])}</th>' for _, y in tiers)
    rows = "".join(f'\n              <tr><th scope="row">{esc(size)}<small>{esc(bracket_profile(n))}</small></th>'
                   + "".join(f'<td data-label="{esc(y["label"])}">{dollars(prices[k])}</td>' for k, y in tiers)
                   + "</tr>" for size, n, prices in price_rows())
    return f"""<div class="card price-card">
          <table class="price-table">
            <caption class="visually-hidden">Mowing price per visit by lawn size and yard type, before tax</caption>
            <thead><tr><th scope="col">Lawn size</th>{head}</tr></thead>
            <tbody>{rows}
            </tbody>
          </table>
        </div>"""


def price_range() -> tuple[Decimal, Decimal]:
    """Cheapest and most expensive mow we book online, before tax and before any route discount."""
    return yield_mow_fee(1, "STANDARD"), yield_mow_fee(MAX_SQFT, "STEEP_SLOPES")


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


def e164(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    return "+1" + digits if len(digits) == 10 else ("+" + digits if digits else "")


def business_node(settings: Settings, site: str) -> dict:
    """The business itself (home page and every area page share this @id). No street address or exact location:
    we're a service-area business and don't publish where the crew starts from."""
    low, high = price_range()
    node = {"@type": "HomeAndConstructionBusiness", "@id": f"{site}/#business", "name": settings.business_name,
            "legalName": settings.legal_name, "url": f"{site}/",
            "description": "Veteran-owned lawn mowing with bin and gutter cleaning add-ons, booked online, "
                           "on planned neighborhood routes north and northeast of Houston.",
            "image": f"{site}/static/icons/post-one-share.jpg",
            "address": {"@type": "PostalAddress", "addressLocality": "Spring", "addressRegion": "TX",
                        "postalCode": "77373", "addressCountry": "US"},
            "areaServed": [{"@type": "AdministrativeArea", "name": f"{a.city}, TX"} for a in AREAS],
            "priceRange": f"{dollars(low)}-{dollars(high)}",
            "openingHoursSpecification": [{"@type": "OpeningHoursSpecification",
                                           "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"],
                                           "opens": "07:00", "closes": "17:00"}],
            "knowsAbout": ["Lawn Mowing", "Gutter Cleaning", "Trash Bin Sanitization", "Holiday Lighting Installation"]}
    if settings.business_phone:
        node["telephone"] = e164(settings.business_phone)
    if settings.business_email:
        node["email"] = settings.business_email
    return node


def home_structured_data(settings: Settings, site: str) -> str:
    return f'<script type="application/ld+json">{script_json({"@context": "https://schema.org", **business_node(settings, site)})}</script>'


def structured_data(settings: Settings, area: Area, site: str) -> dict:
    """LocalBusiness + this area's mowing Service with every price + breadcrumbs. No street address,
    phone or ratings: we don't publish an address, have no business phone setting, and Google
    forbids self-serving review markup."""
    business_id = f"{site}/#business"
    page_url = f"{site}/local/{area.slug}"
    offers = [{"@type": "Offer", "name": f"{y['label']}: {size}", "price": f"{prices[k]:.2f}", "priceCurrency": "USD"}
              for size, _, prices in price_rows() for k, y in YARD_TYPES.items()]
    return {"@context": "https://schema.org", "@graph": [
        business_node(settings, site),
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
# Logo A's small mark (shield and "1", no mow lines). Decorative: the name is always right next to it.
BRAND_MARK = ('<svg class="brand-mark" viewBox="0 0 200 220" width="30" height="33" aria-hidden="true" focusable="false">'
              '<path d="M100 10 L182 40 V110 C182 160 148 192 100 210 C52 192 18 160 18 110 V40 Z" fill="#0F2B22" '
              'stroke="#C9A227" stroke-width="9" stroke-linejoin="round"/>'
              '<path d="M92 166 V82 C84 88 74 92 62 94 V78 C80 74 94 62 101 46 H113 V166 Z" fill="#9BD15A"/></svg>')


def brand_lines(name: str) -> tuple[str, str]:
    """The wordmark's two lines: "Post One Lawn Co." -> ("Post One", "Lawn Co."). A name without "Lawn" stays on one line."""
    name = " ".join(name.split())
    head, sep, tail = name.rpartition(" Lawn ")
    if head and sep:
        return head, f"Lawn {tail}"
    if name.endswith(" Lawn"):
        return name[:-5], "Lawn"
    return name, ""


def brand_html(name: str) -> str:
    """Mark + two-line wordmark for the header and footer links (and {{BRAND}} in the static pages).

    Built from BUSINESS_NAME, so a new name still renders sensibly. The stylized lines are aria-hidden;
    screen readers read the full name once from the visually hidden span."""
    top, sub = brand_lines(name)
    sub_html = f'<span class="wm-sub">{esc(sub)}</span>' if sub else ""
    return (f'{BRAND_MARK}<span class="wordmark" aria-hidden="true" data-no-i18n>'
            f'<span class="wm-top">{esc(top)}</span>{sub_html}</span>'
            f'<span class="visually-hidden">{esc(name)}</span>')


def layout(settings: Settings, version: str, *, title: str, description: str, body: str,
           canonical: str | None = None, og_image: str | None = None, head_extra: str = "", page: str = "") -> str:
    """The page shell for every server-rendered page. `page` adds a body class (sp-about, sp-legal, ...)."""
    brand = brand_html(settings.business_name)
    body_class = "site local page-server-pages" + (f" sp-{page}" if page else "")
    meta = ""
    if canonical:
        meta += f"""
  <link rel="canonical" href="{esc(canonical)}">
  <meta property="og:url" content="{esc(canonical)}">"""
    if og_image:
        meta += f'''
  <meta property="og:image" content="{esc(og_image)}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">'''
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
  <meta name="theme-color" content="#0F2B22">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="icon" href="/favicon.ico" sizes="any">
  <link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
  <link rel="preload" href="/static/fonts/big-shoulders-display-800.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="preload" href="/static/fonts/public-sans-400.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="stylesheet" href="/static/styles.css?v={esc(version)}">
  <script src="/static/i18n.js?v={esc(version)}"></script>{head_extra}
</head>
<body class="{body_class}">
  <a class="skip-link" href="#main">Skip to content</a>
  <header class="site-header">
    <div class="site-wrap header-row">
      <a class="brand" href="/">{brand}</a>
      <nav class="site-nav" aria-label="Main">
        <a href="/services">Services</a>
        <a href="/local">Service areas</a>
        <a href="/team">Meet the crew</a>
        <a href="/about">About</a>
      </nav>
      <a class="btn btn-primary btn-sm header-cta" href="/book">Book now</a>
    </div>
  </header>

  <main id="main">{body}
  </main>

  <footer class="site-footer">
    <div class="site-wrap footer-grid">
      <div>
        <a class="brand footer-brand" href="/">{brand}</a>
        <p class="footer-tagline">On post. On time.</p>
        <p>Veteran-owned · Spring, TX</p>
        <p class="footer-trust">Clean lawns. Stronger communities.</p>
      </div>
      <nav aria-label="Footer">
        <a href="/book">Book a service</a>
        <a href="/services">Services</a>
        <a href="/local">Service areas</a>
        <a href="/team">Meet the crew</a>
        <a href="/about">About</a>
        <a href="/visit">View my visit</a>
      </nav>
      <nav class="footer-areas" aria-label="Areas we serve">
        <a class="footer-areas-title" href="/local">Areas we serve</a>
{areas}
      </nav>
      <p class="footer-copy">© {local_now(settings).year} {esc(settings.business_name)}</p>
      {legal_footer_html(settings)}
    </div>
  </footer>

  <script src="/static/site.js?v={esc(version)}"></script>
  <script src="/static/tracker.js?v={esc(version)}" defer></script>
</body>
</html>
"""


def with_share_tags(text: str, site: str, path: str) -> str:
    """Adds what a page's <head> is missing of: canonical link, og:url and the share image (absolute URLs).
    Pages that already set one keep theirs."""
    url = f"{site}{path}"
    tags = []
    if 'rel="canonical"' not in text:
        tags.append(f'<link rel="canonical" href="{esc(url)}">')
    if 'property="og:url"' not in text:
        tags.append(f'<meta property="og:url" content="{esc(url)}">')
    if 'property="og:image"' not in text:
        img = esc(f"{site}/static/icons/post-one-share.jpg")
        tags += [f'<meta property="og:image" content="{img}">', '<meta property="og:image:width" content="1200">',
                 '<meta property="og:image:height" content="630">', '<meta name="twitter:card" content="summary_large_image">']
    return text.replace("</head>", "".join(f"  {t}\n" for t in tags) + "</head>", 1) if tags else text


def contact_line(settings: Settings) -> str:
    """" · email · phone" for the footer (the phone only once the owner sets it)."""
    out = ""
    if settings.business_email:
        out += f' · <a href="mailto:{esc(settings.business_email)}">{esc(settings.business_email)}</a>'
    if settings.business_phone:
        digits = "".join(c for c in settings.business_phone if c.isdigit() or c == "+")
        out += f' · <a href="tel:{esc(digits)}">{esc(settings.business_phone)}</a>'
    return out


def legal_footer_html(settings: Settings) -> str:
    """The footer line every customer page carries: who we are, how to reach us, the policies."""
    # The brand first; the LLC is still named, as the law requires for a d/b/a.
    return (f'<p class="legal-line">{esc(settings.business_name)} is operated by {esc(settings.legal_name)}'
            f'{contact_line(settings)} · '
            '<a href="/privacy">Privacy</a> · <a href="/terms">Terms</a> · <a href="/refunds">Refunds</a></p>')


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


# Line icons for the "Why book with us" row (24px grid, drawn with the stroke color from the stylesheet).
ICONS = {"shield": "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
         "pin": "M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11zM12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
         "chat": "M21 12a8 8 0 0 1-12 7l-5 1 1-4a8 8 0 1 1 16-4z",
         "check": "M9 12l2 2 4-4M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
         "covered": "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM9 12l2 2 4-4"}


def icon(name: str) -> str:
    return f'<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="{ICONS[name]}"/></svg>'


def trust_items(settings: Settings) -> list[tuple[str, str, str]]:
    """Why book with us, as (icon, title, text). Insurance and background checks are listed ONLY when the owner has set them."""
    items = [("shield", "Veteran-owned", "A local business owned and led by a veteran."),
             ("pin", "Planned daily routes", "Each day's route is planned the evening before, stop by stop."),
             ("chat", "Live visit page", "An alert when the crew is on the way, and a live page for every visit.")]
    if settings.crew_background_checked:
        items.append(("check", "Background-checked crew", "Every crew member has passed a background check."))
    if coverage := settings.liability_coverage.strip():
        items.append(("covered", f"{coverage} liability coverage", "Commercial liability coverage while we're on your property."))
    return items


# ---------- Pages ------------------------------------------------------
def area_html(settings: Settings, version: str, area: Area, site: str, day: date) -> str:
    zone = zone_by_key(area.zone_key)
    city = esc(area.city)
    page_url = f"{site}/local/{area.slug}"
    low, _ = price_range()

    add_ons = "".join(f"<li><strong>{esc(label)}</strong><span>{esc(price)}</span></li>" for label, price in add_on_rows())
    cause_list = "".join(f"<li>{esc(name)}</li>" for name in cause_names(settings))
    # Facts that really differ by area: the size "Full property" is priced at, county, ZIPs, tax.
    full = zone.full_property_sqft
    full_prices = " / ".join(dollars(yield_mow_fee(full, k)) for k in YARD_TYPES)
    facts = "".join(f"<li><strong>{esc(k)}</strong><span>{esc(v)}</span></li>" for k, v in (
        ("County", area.county),
        *((("ZIP codes", ", ".join(area.zips)),) if area.zips else ()),
        ("“Full property” is priced at", f"about {full:,} sq ft ({bracket_profile(full)}): {full_prices} before tax"),
        ("“Yard only” is priced at", "the typical yard size here; the booking form shows it for your address"),
        ("Sales tax", f"{percent(zone.tax_rate)}%")))
    hood_for = {h.name: h for h in hoods_in(area)}
    places = "".join(f'<li><a href="/local/{area.slug}/{hood_for[p].slug}">{esc(p)}</a></li>' if p in hood_for
                     else f"<li>{esc(p)}</li>" for p in area.places)
    trust = "".join(f"<li>{icon(i)}<div><strong>{esc(t)}</strong><span>{esc(d)}</span></div></li>"
                    for i, t, d in trust_items(settings))
    others = area_links(a for a in AREAS if a is not area)
    acres = f"{MAX_SQFT / 43_560:g}"

    body = f"""
    <section class="sp-hero" aria-labelledby="area-title">
      <div class="site-wrap sp-hero-grid">
        <div class="sp-hero-copy">
          {crumbs([("Home", "/"), ("Areas we serve", "/local"), (area.city, None)])}
          <p class="eyebrow">Veteran-owned · Based in Spring, TX · Serving {city}</p>
          <h1 id="area-title">Lawn mowing in {city}, TX</h1>
          <p class="lede">{esc(area.intro)}</p>
          <div class="hero-actions">
            <a class="btn btn-lg sp-btn-fresh" href="/book">Book online</a>
            <a class="btn btn-lg sp-btn-line" href="#prices">See prices</a>
          </div>
        </div>
        <div class="sp-card next-open" role="group" aria-label="Next service day you can book">
          <p class="sp-kicker">Next day you can book</p>
          <p class="next-day">{day:%A, %B} {day.day}</p>
          <p class="hint">We mow {city} every {WEEKDAY_NAMES[zone.service_weekday]}, so the crew stays in your area all day.
            Booking closes at {hour_words(settings.freeze_hour)} the day before.</p>
          <a class="btn btn-primary btn-block" href="/book">Book this day</a>
        </div>
      </div>
    </section>

    <section class="sp-overlap" aria-labelledby="why-title">
      <div class="site-wrap">
        <div class="sp-trust">
          <h2 class="sp-kicker" id="why-title">Why book with us</h2>
          <ul class="sp-trust-list">{trust}</ul>
        </div>
      </div>
    </section>

    <section class="section" aria-labelledby="where-title">
      <div class="site-wrap">
        <h2 id="where-title">Where we mow</h2>
        <ul class="spec-list">{places}</ul>
        <h3>{city} at a glance</h3>
        <ul class="local-list local-facts">{facts}</ul>
        <p class="section-lede local-check">Not sure you're on our route? The booking form checks your address before
          you book, or you can <a href="/#area-checker">check your address</a> on the home page.</p>
      </div>
    </section>

    <section class="section" id="prices" aria-labelledby="prices-title">
      <div class="site-wrap">
        <h2 id="prices-title">Mowing prices (the same in every area we serve)</h2>
        <p class="section-lede">A price per visit, set by your lawn size and your yard type. Prices are before tax.</p>
        {price_table()}
        <p class="tax-note">{percent(zone.tax_rate)}% Texas sales tax added.</p>
        <p class="hint">Sizes in between are priced the same way; the booking form shows your exact price before you book.
          Neighbors already on the route save you money: with 2 or more of our customers booked within half a mile,
          you get {percent(density_pct(2))}% off the mowing ({percent(density_pct(5))}% with 5 or more).
          Lawns over {MAX_SQFT:,} sq ft ({acres} acres) are quoted in person.</p>
        <h3>Add to any mowing visit</h3>
        <ul class="local-list">{add_ons}</ul>
        <p class="hint">Add-on prices are before tax too.</p>
      </div>
    </section>

    <section class="section" aria-labelledby="giving-title">
      <div class="site-wrap">
        <h2 id="giving-title">Giving back</h2>
        <p class="section-lede">{percent(YIELD_GIVING_RATE)}% of every visit's price goes to the cause you pick when you book.
          It's included in the price shown, not added on top.</p>
        <ul class="spec-list">{cause_list}</ul>
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
                  og_image=f"{site}/static/icons/post-one-share.jpg", head_extra=ld, page="area")


def hood_structured_data(settings: Settings, area: Area, hood: Hood, site: str) -> dict:
    """The business + this neighborhood's mowing Service + breadcrumbs (no prices list: the area page carries it)."""
    page_url = f"{site}/local/{area.slug}/{hood.slug}"
    low, high = price_range()
    return {"@context": "https://schema.org", "@graph": [
        business_node(settings, site),
        {"@type": "Service", "@id": f"{page_url}#service", "serviceType": "Lawn mowing",
         "name": f"Lawn mowing in {hood.name}, {area.city}, TX", "url": page_url, "provider": {"@id": f"{site}/#business"},
         "areaServed": {"@type": "Place", "name": f"{hood.name}, {area.city}, TX",
                        "containedInPlace": {"@type": "City", "name": f"{area.city}, TX"}},
         "offers": {"@type": "AggregateOffer", "priceCurrency": "USD", "lowPrice": f"{low:.2f}", "highPrice": f"{high:.2f}"}},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{site}/"},
            {"@type": "ListItem", "position": 2, "name": "Areas we serve", "item": f"{site}/local"},
            {"@type": "ListItem", "position": 3, "name": f"{area.city}, TX", "item": f"{site}/local/{area.slug}"},
            {"@type": "ListItem", "position": 4, "name": hood.name, "item": page_url}]},
    ]}


def hood_html(settings: Settings, version: str, hood: Hood, site: str, day: date) -> str:
    area = AREA_BY_SLUG[hood.area]
    zone = zone_by_key(area.zone_key)
    name, city = esc(hood.name), esc(area.city)
    weekday = WEEKDAY_NAMES[zone.service_weekday]
    page_url = f"{site}/local/{area.slug}/{hood.slug}"
    low, _ = price_range()
    full = zone.full_property_sqft
    sizes = "".join(f"<li><strong>{esc(size)}</strong><span>{dollars(prices['STANDARD'])} before tax</span></li>"
                    for size, _, prices in price_rows()[:3])
    neighbors = [h for h in hoods_in(area) if h is not hood]
    nearby = "".join(f'<li><a href="/local/{area.slug}/{h.slug}">Lawn mowing in {esc(h.name)}</a></li>' for h in neighbors)
    nearby_block = f"""
        <h3>Also on the {city} route</h3>
        <ul class="area-links">{nearby}</ul>""" if neighbors else ""

    body = f"""
    <section class="sp-hero" aria-labelledby="hood-title">
      <div class="site-wrap sp-hero-grid">
        <div class="sp-hero-copy">
          {crumbs([("Home", "/"), ("Areas we serve", "/local"), (area.city, f"/local/{area.slug}"), (hood.name, None)])}
          <p class="eyebrow">Veteran-owned · {city}, TX · {weekday}s</p>
          <h1 id="hood-title">Lawn mowing in {name}</h1>
          <p class="lede">{esc(hood.intro)}</p>
          <div class="hero-actions">
            <a class="btn btn-lg sp-btn-fresh" href="/book">Book online</a>
            <a class="btn btn-lg sp-btn-line" href="/local/{area.slug}#prices">See all prices</a>
          </div>
        </div>
        <div class="sp-card next-open" role="group" aria-label="Next service day you can book">
          <p class="sp-kicker">Next day you can book</p>
          <p class="next-day">{day:%A, %B} {day.day}</p>
          <p class="hint">{name} is mowed every {weekday} with the rest of {city}.
            Booking closes at {hour_words(settings.freeze_hour)} the day before.</p>
          <a class="btn btn-primary btn-block" href="/book">Book this day</a>
        </div>
      </div>
    </section>

    <section class="section" aria-labelledby="cost-title">
      <div class="site-wrap">
        <h2 id="cost-title">What a mow costs in {name}</h2>
        <p class="section-lede">A flat price per visit from {dollars(low)}, set by your lawn size and yard type. You see the
          full price with tax before you book.</p>
        <ul class="local-list">{sizes}
          <li><strong>“Full property” here</strong><span>priced at about {full:,} sq ft ({esc(bracket_profile(full))})</span></li>
        </ul>
        <p class="hint">Standard yards shown. Neighbors in {name} already on the route lower your price: {percent(density_pct(2))}% off
          with 2 or more booked within half a mile, {percent(density_pct(5))}% with 5 or more.
          <a href="/local/{area.slug}#prices">Full price table and add-ons</a>.</p>
      </div>
    </section>

    <section class="section" aria-labelledby="hood-more-title">
      <div class="site-wrap">
        <h2 id="hood-more-title">More about our {city} route</h2>
        <p class="section-lede">{esc(area.intro)}</p>
        <p><a class="btn btn-outline" href="/local/{area.slug}">Lawn mowing in {city}, TX</a></p>{nearby_block}
      </div>
    </section>
{cta_band(f"Put your {hood.name} lawn on the route.")}"""

    title = f"Lawn Mowing in {hood.name}, {area.city} TX | {settings.business_name}"
    description = (f"Lawn mowing in {hood.name}, {area.city}, TX, every {weekday}. "
                   f"Flat prices from {dollars(low)} a visit before tax. Veteran-owned. Book online.")
    ld = f'\n  <script type="application/ld+json">{script_json(hood_structured_data(settings, area, hood, site))}</script>'
    return layout(settings, version, title=title, description=description, body=body, canonical=page_url,
                  og_image=f"{site}/static/icons/post-one-share.jpg", head_extra=ld, page="area")


def area_links(areas) -> str:
    return "".join(f'<li><a href="/local/{a.slug}">Lawn mowing in {esc(a.city)}, TX</a></li>' for a in areas)


def index_html(settings: Settings, version: str, site: str) -> str:
    low, _ = price_range()
    cards = "".join(f"""
          <li><a class="card local-card" href="/local/{a.slug}">
            <strong>Lawn mowing in {esc(a.city)}, TX</strong>
            <span>{esc(" · ".join(a.places))}</span>
            <span class="local-card-cta">See prices and the next open day</span>
          </a></li>""" for a in AREAS) + """
          <li class="sp-check-card"><p>Not sure you're on our route? The booking form checks your address before
            you book, or you can <a href="/#area-checker">check your address</a> on the home page.</p></li>"""
    body = f"""
    <section class="sp-hero local-index" aria-labelledby="areas-title">
      <div class="site-wrap sp-hero-copy">
        {crumbs([("Home", "/"), ("Areas we serve", None)])}
        <p class="eyebrow">Veteran-owned · Spring, TX area</p>
        <h1 class="page-title" id="areas-title">Areas we serve</h1>
        <p class="lede">We mow on set neighborhood routes north and northeast of Houston. Pick your area to see
          the neighborhoods we cover, flat prices from {dollars(low)} per visit before tax, and the next day you can book.</p>
      </div>
    </section>

    <div class="sp-overlap">
      <div class="site-wrap">
        <ul class="local-grid" aria-labelledby="areas-title">{cards}
        </ul>
      </div>
    </div>
{cta_band("Put your lawn on the route.")}"""
    cities = joined(f"{a.city}" for a in AREAS)
    return layout(settings, version, title=f"Areas We Serve | {settings.business_name}",
                  description=f"Lawn mowing in {cities}, TX: the neighborhoods we cover and flat per-visit prices for each area.",
                  body=body, canonical=f"{site}/local", og_image=f"{site}/static/icons/post-one-share.jpg", page="index")


def not_found_html(settings: Settings, version: str) -> str:
    # The requested name is never echoed back.
    body = f"""
    <section class="sp-hero sp-hero-short" aria-labelledby="nf-title">
      <div class="site-wrap sp-hero-copy">
        <h1 class="page-title" id="nf-title">We don't have a page for that area</h1>
        <p class="lede">We may still mow there. See the areas we serve, or start a booking: the booking form
          checks your address before you book.</p>
        <div class="hero-actions">
          <a class="btn btn-lg sp-btn-fresh" href="/local">Areas we serve</a>
          <a class="btn btn-lg sp-btn-line" href="/book">Book online</a>
        </div>
      </div>
    </section>

    <section class="section" aria-labelledby="nf-areas-title">
      <div class="site-wrap">
        <h2 id="nf-areas-title">Areas we serve</h2>
        <ul class="area-links">{area_links(AREAS)}</ul>
      </div>
    </section>"""
    return layout(settings, version, title=f"Area not found | {settings.business_name}",
                  description="See the areas we serve.", body=body, page="404")


def not_found_page(settings: Settings, version: str) -> str:
    """Site-wide 404 for a mistyped or old link."""
    body = """
    <section class="sp-hero sp-hero-short" aria-labelledby="nf-title">
      <div class="site-wrap sp-hero-copy">
        <h1 class="page-title" id="nf-title">We couldn't find that page</h1>
        <p class="lede">The link may be old or mistyped. Here's where most people are headed:</p>
      </div>
    </section>

    <div class="section">
      <div class="site-wrap">
        <div class="hero-actions">
          <a class="btn btn-primary btn-lg" href="/book">Book a visit</a>
          <a class="btn btn-lg btn-quiet" href="/visit">View my visit</a>
          <a class="btn btn-lg btn-quiet" href="/">Home</a>
        </div>
      </div>
    </div>"""
    return layout(settings, version, title=f"Page not found | {settings.business_name}", description="Page not found.",
                  body=body, page="404")


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
        if target is None and (hood := HOOD_BY_SLUG.get(slug.lower())):
            return RedirectResponse(f"/local/{hood.area}/{hood.slug}", status_code=301)
        if target is None:
            return html_page(not_found_html(settings, version), 404)
        if target != slug:
            return RedirectResponse(f"/local/{target}", status_code=301)
        return html_page(area_html(settings, version, AREA_BY_SLUG[target], site_url(settings, request),
                                   next_open_day(settings, request.app.state.repo,
                                                 zone_by_key(AREA_BY_SLUG[target].zone_key))))

    @app.get("/local/{slug}/{rest:path}", include_in_schema=False)
    def street_page(slug: str, rest: str, request: Request):
        # A neighborhood we wrote a page for gets that page; any other street-level URL folds into the
        # area page: we never publish streets.
        target = resolve(slug)
        if target is None:
            return html_page(not_found_html(settings, version), 404)
        hood = HOOD_BY_SLUG.get(rest.strip("/").lower())
        if hood and hood.area == target and slug == target and rest == hood.slug:
            return html_page(hood_html(settings, version, hood, site_url(settings, request),
                                       next_open_day(settings, request.app.state.repo, zone_by_key(AREA_BY_SLUG[target].zone_key))))
        if hood:
            return RedirectResponse(f"/local/{hood.area}/{hood.slug}", status_code=301)
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
        from .service_pages import SERVICES   # imported here: service_pages builds on this module
        paths = ["/", "/book", "/services", *(f"/services/{s.slug}" for s in SERVICES),
                 "/team", "/local", *(f"/local/{a.slug}" for a in AREAS),
                 *(f"/local/{h.area}/{h.slug}" for h in HOODS), "/about", "/privacy", "/terms", "/refunds"]
        urls = "".join(f"  <url><loc>{xml_escape(site + p)}</loc></url>\n" for p in paths)
        body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n')
        return Response(body, media_type="application/xml")
