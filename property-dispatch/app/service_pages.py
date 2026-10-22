"""Service pages for search engines and customers.

    GET /services          what we do, one card per service
    GET /services/{slug}   lawn-mowing, bin-cleaning, gutter-cleaning, holiday-lighting

Rendered on the server like the /local pages. Every price, time and season is read live from
app/pricing.py, and the area days from app/zones.py, so a page can never quote something the
booking form doesn't charge. Each page states only what the terms and the booking form back.
"""

import html
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .config import Settings, site_url
from .local_pages import (AREAS, area_links, business_node, crumbs, cta_band, dollars, layout, percent, price_range,
                          price_table, script_json)
from .pricing import ADD_ONS, MAX_SQFT, YARD_TYPES, density_pct, season_text
from .zones import SERVICE_ZONES, WEEKDAY_NAMES, short_name

esc = html.escape


@dataclass(frozen=True)
class Service:
    slug: str
    name: str                   # "Lawn mowing"
    add_on: str | None          # key in ADD_ONS, or None for mowing itself
    lede: str
    book: str                   # where "Book" goes (pre-ticks the add-on)


SERVICES: tuple[Service, ...] = (
    Service("lawn-mowing", "Lawn mowing", None,
            "Flat-priced lawn mowing on planned neighborhood routes north and northeast of Houston. Your price is set by "
            "your lawn size and yard type, and you see it with tax before you book.", "/book"),
    Service("bin-cleaning", "Trash bin cleaning", "bin_cleaning",
            "Bin cleaning added to your mowing visit: we clean and sanitize your trash bins while the crew is already "
            "at your home, so there's no extra trip and no separate appointment.", "/book?addon=bin_cleaning#step-where"),
    Service("gutter-cleaning", "Gutter cleaning", "gutters",
            "Gutter cleaning added to your mowing visit: we clear your gutters and downspouts so rain water flows "
            "away from your home again.", "/book?addon=gutters#step-where"),
    Service("holiday-lighting", "Holiday lighting", "holiday_lights",
            "Holiday lights installed to fit your home. Every quote starts with a lighting plan for your roofline, and "
            "asking for one costs nothing.", "/book?addon=holiday_lights#step-where"),
)
SERVICE_BY_SLUG = {s.slug: s for s in SERVICES}

for _s in SERVICES:  # fail fast if the price list drops an add-on a page sells
    if _s.add_on and _s.add_on not in ADD_ONS:
        raise ValueError(f"{_s.slug}: unknown add-on {_s.add_on}")


def area_days() -> str:
    rows = "".join(f"<li><strong>{esc(WEEKDAY_NAMES[z.service_weekday])}</strong><span>{esc(short_name(z))}</span></li>"
                   for z in sorted(SERVICE_ZONES, key=lambda z: z.service_weekday))
    return f'<ul class="local-list">{rows}</ul>'


def price_line(s: Service) -> str:
    """The price in words: "From $75 a visit", "+$15 per visit" or "Free quote"."""
    if s.add_on is None:
        return f"From {dollars(price_range()[0])} a visit"
    a = ADD_ONS[s.add_on]
    return "Free quote" if a.get("quote") else f"+{dollars(a['price'])} per visit"


def details(s: Service) -> str:
    """The middle of each page: what you get and how it works, from the price list and the terms."""
    low, _ = price_range()
    acres = f"{MAX_SQFT / 43_560:g}"
    if s.add_on is None:
        yards = "".join(f"<li><strong>{esc(y['label'])}</strong><span>{note}</span></li>" for y, note in zip(
            YARD_TYPES.values(), ("Open lawn, normal edging", "Many trees, beds or obstacles to trim around",
                                  "Hills or slopes that take extra care")))
        return f"""
    <section class="section" aria-labelledby="what-title">
      <div class="site-wrap">
        <h2 id="what-title">What you choose when you book</h2>
        <ul class="local-list">
          <li><strong>Yard only</strong><span>We mow the main or fenced yard.</span></li>
          <li><strong>Full property</strong><span>We mow the whole lot except the house.</span></li>
        </ul>
        <p class="hint">The price shown for your choice is locked. We don't re-measure on site.</p>
        <h3>Your yard type</h3>
        <ul class="local-list">{yards}</ul>
      </div>
    </section>

    <section class="section" id="prices" aria-labelledby="prices-title">
      <div class="site-wrap">
        <h2 id="prices-title">Mowing prices</h2>
        <p class="section-lede">A flat price per visit from {dollars(low)}, before tax. The booking form sizes your lawn
          from your address and shows your exact price before you book.</p>
        {price_table()}
        <p class="hint">Neighbors already on the route lower your price: {percent(density_pct(2))}% off the mowing with 2 or
          more booked within half a mile, {percent(density_pct(5))}% with 5 or more. Lawns over {MAX_SQFT:,} sq ft
          ({acres} acres) are quoted in person.</p>
      </div>
    </section>"""
    a = ADD_ONS[s.add_on]
    if a.get("quote"):
        season = season_text(s.add_on)
        return f"""
    <section class="section" aria-labelledby="what-title">
      <div class="site-wrap">
        <h2 id="what-title">How a lighting quote works</h2>
        <ul class="local-list">
          <li><strong>Install window</strong><span>{esc(season or "Seasonal")}</span></li>
          <li><strong>Price</strong><span>Custom quote, based on your home's size, roofline and installation needs</span></li>
          <li><strong>Asking costs nothing</strong><span>Add the quote request to a mowing booking; nothing is charged for it</span></li>
        </ul>
        <p class="hint">The quote request shows on the crew's stop, so we can look at your roofline on the visit.</p>
      </div>
    </section>"""
    return f"""
    <section class="section" aria-labelledby="what-title">
      <div class="site-wrap">
        <h2 id="what-title">How it works</h2>
        <ul class="local-list">
          <li><strong>Price</strong><span>{dollars(a['price'])} per visit, before tax</span></li>
          <li><strong>When</strong><span>On the same visit as your mow: add it when you book</span></li>
          <li><strong>Time on site</strong><span>About {a['minutes']} extra minutes for the crew</span></li>
        </ul>
        <p class="hint">Add-ons are done on a mowing visit, so the crew is already at your home. You see the full price
          with tax before you book.</p>
      </div>
    </section>"""


def service_structured_data(settings: Settings, s: Service, site: str) -> dict:
    url = f"{site}/services/{s.slug}"
    node = {"@type": "Service", "@id": f"{url}#service", "serviceType": s.name, "name": f"{s.name} in Spring, TX",
            "url": url, "provider": {"@id": f"{site}/#business"},
            "areaServed": [{"@type": "City", "name": f"{a.city}, TX"} for a in AREAS]}
    if s.add_on is None:
        low, high = price_range()
        node["offers"] = {"@type": "AggregateOffer", "priceCurrency": "USD", "lowPrice": f"{low:.2f}", "highPrice": f"{high:.2f}"}
    elif ADD_ONS[s.add_on]["price"]:
        node["offers"] = {"@type": "Offer", "priceCurrency": "USD", "price": f"{ADD_ONS[s.add_on]['price']:.2f}"}
    return {"@context": "https://schema.org", "@graph": [
        business_node(settings, site), node,
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{site}/"},
            {"@type": "ListItem", "position": 2, "name": "Services", "item": f"{site}/services"},
            {"@type": "ListItem", "position": 3, "name": s.name, "item": url}]},
    ]}


def service_html(settings: Settings, version: str, s: Service, site: str) -> str:
    others = "".join(f'<li><a href="/services/{o.slug}">{esc(o.name)}</a></li>' for o in SERVICES if o is not s)
    body = f"""
    <section class="sp-hero" aria-labelledby="svc-title">
      <div class="site-wrap sp-hero-copy">
        {crumbs([("Home", "/"), ("Services", "/services"), (s.name, None)])}
        <p class="eyebrow">Veteran-owned · Spring, TX · {esc(price_line(s))}</p>
        <h1 id="svc-title">{esc(s.name)} in Spring, TX</h1>
        <p class="lede">{esc(s.lede)}</p>
        <div class="hero-actions">
          <a class="btn btn-lg sp-btn-fresh" href="{esc(s.book)}">{"Ask for a quote" if s.slug == "holiday-lighting" else "Book online"}</a>
          <a class="btn btn-lg sp-btn-line" href="/local">Areas we serve</a>
        </div>
      </div>
    </section>
{details(s)}

    <section class="section" aria-labelledby="days-title">
      <div class="site-wrap">
        <h2 id="days-title">One area a day</h2>
        <p class="section-lede">The crew works one area each weekday, so we're not driving across Houston between lawns.
          Saturday is for make-up visits.</p>
        {area_days()}
        <ul class="area-links">{area_links(AREAS)}</ul>
      </div>
    </section>

    <section class="section" aria-labelledby="how-title">
      <div class="site-wrap">
        <h2 id="how-title">Booking, paying and changing plans</h2>
        <ul class="spec-list">
          <li>No contract or subscription: each booking is one visit.</li>
          <li>Pay by card, Apple Pay or Google Pay when you book. The crew only goes to paid visits.</li>
          <li>We text you when the crew is on the way.</li>
          <li>Cancel free, with a full refund, until we text that the crew is on the way.</li>
        </ul>
        <p class="hint">Details are in our <a href="/terms">terms</a> and <a href="/refunds">refund policy</a>.</p>
      </div>
    </section>
{cta_band(f"Book {s.name.lower()} online.")}

    <section class="section" aria-labelledby="more-title">
      <div class="site-wrap">
        <h2 id="more-title">Other services</h2>
        <ul class="area-links">{others}</ul>
      </div>
    </section>"""
    title = f"{s.name} in Spring, TX | {settings.business_name}"
    description = f"{s.name} around Spring, Klein, New Caney and Cleveland, TX. {price_line(s)}. Veteran-owned. Book online."
    ld = f'\n  <script type="application/ld+json">{script_json(service_structured_data(settings, s, site))}</script>'
    return layout(settings, version, title=title, description=description, body=body,
                  canonical=f"{site}/services/{s.slug}", og_image=f"{site}/static/icons/post-one-share.jpg",
                  head_extra=ld, page="area")


def services_index_html(settings: Settings, version: str, site: str) -> str:
    cards = "".join(f"""
          <li><a class="card local-card" href="/services/{s.slug}">
            <strong>{esc(s.name)}</strong>
            <span>{esc(price_line(s))}</span>
            <span class="local-card-cta">Prices and how it works</span>
          </a></li>""" for s in SERVICES)
    body = f"""
    <section class="sp-hero local-index" aria-labelledby="svc-title">
      <div class="site-wrap sp-hero-copy">
        {crumbs([("Home", "/"), ("Services", None)])}
        <p class="eyebrow">Veteran-owned · Spring, TX area</p>
        <h1 class="page-title" id="svc-title">Our services</h1>
        <p class="lede">Lawn mowing first, with bin and gutter cleaning you can add to the same visit. Every price is
          shown with tax before you book.</p>
      </div>
    </section>

    <div class="sp-overlap">
      <div class="site-wrap">
        <ul class="local-grid" aria-labelledby="svc-title">{cards}
        </ul>
      </div>
    </div>
{cta_band("Put your lawn on the route.")}"""
    return layout(settings, version, title=f"Services | {settings.business_name}",
                  description="Lawn mowing, trash bin cleaning, gutter cleaning and holiday lighting around Spring, TX. "
                              "Flat prices shown before you book.",
                  body=body, canonical=f"{site}/services", og_image=f"{site}/static/icons/post-one-share.jpg", page="index")


def register_service_pages(app: FastAPI, settings: Settings, version: str = "") -> None:
    def html_page(text: str) -> HTMLResponse:
        return HTMLResponse(text, headers={"Cache-Control": "no-cache"})

    @app.get("/services", include_in_schema=False)
    def services(request: Request):
        return html_page(services_index_html(settings, version, site_url(settings, request)))

    @app.get("/services/{slug}", include_in_schema=False)
    def service(slug: str, request: Request):
        s = SERVICE_BY_SLUG.get(slug.lower().strip("/"))
        if s is None:
            return RedirectResponse("/services", status_code=301)
        if slug != s.slug:
            return RedirectResponse(f"/services/{s.slug}", status_code=301)
        return html_page(service_html(settings, version, s, site_url(settings, request)))
