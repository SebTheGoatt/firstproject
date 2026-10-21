"""Local service-area pages (/local), the sitemap and robots.txt."""

import dataclasses
import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import urlparse

from fastapi.testclient import TestClient

from app.local_pages import AREAS, HOODS
from app.main import create_app
from app.local_pages import SAMPLE_SIZES, dollars
from app.pricing import MAX_SQFT, YARD_TYPES, yield_mow_fee
from app.zones import zone_by_key

from .conftest import FakeGeocoder
from .test_api_flow import NOW, TOMORROW, book

AREA_PATHS = [f"/local/{a.slug}" for a in AREAS]
HOOD_PATHS = [f"/local/{h.area}/{h.slug}" for h in HOODS]
from app.service_pages import SERVICES  # noqa: E402
SERVICE_PATHS = [f"/services/{s.slug}" for s in SERVICES]
LD_JSON = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def app_with(settings, repo, **changes) -> TestClient:
    for k, v in changes.items():
        setattr(settings, k, v)
    return TestClient(create_app(settings, repo=repo, geocoder=FakeGeocoder(), sms=None))


def json_ld(text: str) -> dict:
    blocks = LD_JSON.findall(text)
    assert len(blocks) == 1, "exactly one JSON-LD block per area page"
    return json.loads(blocks[0])


def by_type(data: dict) -> dict:
    return {node["@type"]: node for node in data["@graph"]}


def all_prices() -> list[Decimal]:
    """The table: the yield engine's mowing price for each sample size and yard type."""
    return [yield_mow_fee(n, k) for n in SAMPLE_SIZES for k in YARD_TYPES]


def test_every_area_page_renders_for_crawlers(client):
    with patch("app.local_pages.local_now", return_value=NOW):
        for a in AREAS:
            r = client.get(f"/local/{a.slug}")
            assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
            t = r.text
            assert f"<h1 id=\"area-title\">Lawn mowing in {a.city}, TX</h1>" in t
            assert f"<title>Lawn Mowing in {a.city}, TX | Post One Lawn Co.</title>" in t
            assert f'<link rel="canonical" href="http://testserver/local/{a.slug}">' in t
            assert 'property="og:title"' in t and 'property="og:description"' in t and 'name="description"' in t
            assert 'name="viewport"' in t and "/static/styles.css?v=" in t
            assert "noindex" not in t and "{{" not in t
            assert html.escape(a.intro) in t
            assert all(html.escape(p) in t for p in a.places)
            assert all(z in t for z in a.zips)
            assert "8.25% Texas sales tax added" in t
            first = {0: "Monday, October 19", 1: "Tuesday, October 20", 2: "Wednesday, October 21",
                     3: "Thursday, October 15", 4: "Friday, October 16"}[zone_by_key(a.zone_key).service_weekday]
            assert first in t                           # the area's own next service day, from NOW
            assert 'href="/book">Book online</a>' in t
            assert all(f'href="/local/{o.slug}"' in t for o in AREAS if o is not a)
            assert "Veteran-owned" in t


def test_meta_descriptions_and_intros_are_unique(client):
    pages = [client.get(p).text for p in AREA_PATHS]
    descriptions = {re.search(r'<meta name="description" content="([^"]+)"', t).group(1) for t in pages}
    assert len(descriptions) == len(AREAS) and len({a.intro for a in AREAS}) == len(AREAS)
    banned = ("best", "#1", "guarantee", "verified", "insured", "licensed")
    for a in AREAS:
        assert not any(w in a.intro.lower() for w in banned), a.slug


def test_next_day_follows_the_5pm_cutoff(client):
    with patch("app.local_pages.local_now", return_value=NOW.replace(hour=18)):
        t = client.get("/local/klein").text
    # Klein is Tuesdays: the 5 PM cutoff only shuts tomorrow (Thursday), so the next Klein day is still the 20th.
    assert "Tuesday, October 20" in t and "We mow Klein every Tuesday" in t and "5 PM the day before" in t


def test_price_table_lists_every_yard_type_and_size(client):
    t = client.get("/local/spring").text
    for y in YARD_TYPES.values():
        assert f'<th scope="col">{y["label"]}</th>' in t
    for size in ("Up to 5,000 sq ft", "7,500 sq ft", "10,000 sq ft", "15,000 sq ft", "20,000 sq ft"):
        assert f'<th scope="row">{size}<small>' in t
    for price in all_prices():
        assert f">{dollars(price)}</td>" in t
    assert ">$75</td>" in t and ">$131.25</td>" in t      # 10,000 sq ft steep slopes: 75 x 1.40 x 1.25
    assert "5% off the mowing (10% with 5 or more)" in t
    # Add-ons with a price, quote-only ones as a free quote; the yard / full property picks are not add-ons.
    assert "Bin cleaning" in t and "Gutter cleaning" in t and "+$15 per visit" in t and "Free quote" in t
    assert "<strong>Yard only</strong>" not in t and "<strong>Full property</strong>" not in t


def test_prices_and_tax_are_read_live(client, monkeypatch):
    monkeypatch.setattr("app.pricing.YIELD_BASE", Decimal("80.00"))
    zone = zone_by_key("KLEIN_CORE")
    monkeypatch.setattr("app.local_pages.zone_by_key", lambda key: dataclasses.replace(zone, tax_rate=0.0725))
    t = client.get("/local/klein").text
    assert ">$80</td>" in t and "7.25% Texas sales tax added" in t
    assert by_type(json_ld(t))["HomeAndConstructionBusiness"]["priceRange"].startswith("$80-")


def test_json_ld_business_service_and_breadcrumbs(client):
    for a in AREAS:
        nodes = by_type(json_ld(client.get(f"/local/{a.slug}").text))
        assert set(nodes) == {"HomeAndConstructionBusiness", "Service", "BreadcrumbList"}
        biz, svc, crumbs = nodes["HomeAndConstructionBusiness"], nodes["Service"], nodes["BreadcrumbList"]
        assert biz["@id"] == "http://testserver/#business" and biz["name"] == "Post One Lawn Co."
        assert biz["legalName"] == "Semper Green LLC"
        assert biz["priceRange"] == f"$75-{dollars(yield_mow_fee(MAX_SQFT, 'STEEP_SLOPES'))}"
        assert {c["name"] for c in biz["areaServed"]} == {f"{x.city}, TX" for x in AREAS}
        assert svc["serviceType"] == "Lawn mowing" and svc["provider"] == {"@id": biz["@id"]}
        assert svc["areaServed"] == {"@type": "City", "name": f"{a.city}, TX"}
        offers = svc["hasOfferCatalog"]["itemListElement"]
        assert len(offers) == len(SAMPLE_SIZES) * len(YARD_TYPES)
        assert all(o["@type"] == "Offer" and o["priceCurrency"] == "USD" and o["name"] for o in offers)
        assert sorted(Decimal(o["price"]) for o in offers) == sorted(all_prices())
        for y in YARD_TYPES.values():   # one offer per yard type per size
            assert sum(o["name"].startswith(y["label"] + ":") for o in offers) == len(SAMPLE_SIZES)
        items = crumbs["itemListElement"]
        assert [i["name"] for i in items] == ["Home", "Areas we serve", f"{a.city}, TX"]
        assert items[-1]["item"] == f"http://testserver/local/{a.slug}"


def test_json_ld_never_has_ratings_phone_or_street(settings, repo):
    c = app_with(settings, repo, twilio_from_number="+12815550000")    # a texting number is not a business phone
    for path in AREA_PATHS:
        raw = LD_JSON.findall(c.get(path).text)[0]
        for banned in ("aggregateRating", "review", "streetAddress", "2815550000", '"geo"', '"telephone"'):
            assert banned not in raw, (path, banned)
    c = app_with(settings, repo, business_phone="(281) 555-0199")      # a phone only once BUSINESS_PHONE is set
    for path in AREA_PATHS:
        raw = LD_JSON.findall(c.get(path).text)[0]
        assert '"telephone": "+12815550199"' in raw and "2815550000" not in raw, path   # never the texting number


def test_index_lists_every_area(client):
    r = client.get("/local")
    assert r.status_code == 200 and "<h1" in r.text and "Areas we serve</h1>" in r.text
    assert '<link rel="canonical" href="http://testserver/local">' in r.text
    for a in AREAS:
        assert f'href="/local/{a.slug}"' in r.text and f"Lawn mowing in {a.city}, TX" in r.text


def test_unknown_area_is_a_friendly_404(client):
    for path in ("/local/houston", "/local/houston/main-st"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 404 and r.headers["content-type"].startswith("text/html")
        assert 'href="/local"' in r.text and "houston" not in r.text.lower()


def test_street_urls_fold_into_the_area_page(client):
    for path, target in (("/local/spring/bridgemont-ln", "/local/spring"), ("/local/klein/a/b/c", "/local/klein"),
                         ("/local/splendora/some-st", "/local/new-caney"), ("/local/spring/", "/local/spring")):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 301 and r.headers["location"] == target, path


def test_aliases_redirect(client):
    for path, target in (("/local/splendora", "/local/new-caney"), ("/local/plum-grove", "/local/cleveland")):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 301 and r.headers["location"] == target


def test_sitemap_is_valid_xml_with_every_public_page(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [e.text for e in ET.fromstring(r.content).findall("s:url/s:loc", ns)]
    assert locs == [f"http://testserver{p}" for p in ("/", "/book", "/services", *SERVICE_PATHS, "/team", "/local", *AREA_PATHS, *HOOD_PATHS, "/about", "/privacy", "/terms", "/refunds")]
    for loc in locs:
        assert client.get(urlparse(loc).path, follow_redirects=False).status_code == 200, loc


def test_robots_points_to_the_sitemap(client, settings, repo):
    r = client.get("/robots.txt").text
    assert "Sitemap: http://testserver/sitemap.xml" in r
    assert "Disallow: /crew" in r and "Disallow: /api/" in r
    c = app_with(settings, repo, public_base_url="https://lawns.test/")
    assert "Sitemap: https://lawns.test/sitemap.xml" in c.get("/robots.txt").text
    assert "<loc>https://lawns.test/local/spring</loc>" in c.get("/sitemap.xml").text


def test_customer_data_never_appears_on_local_pages(client):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0101").status_code == 201
        r = client.post("/api/jobs", json={
            "name": "Zebulon Quackenbush", "phone": "(281) 555-0199", "address": "4821 A Bridgemont Ln",
            "service": "mowing", "lawn_sqft": 5000, "package": "standard", "scheduled_date": TOMORROW.isoformat()})
        assert r.status_code == 201, r.text
    for path in ("/local", *AREA_PATHS, "/sitemap.xml", "/robots.txt"):
        t = client.get(path).text
        for private in ("Zebulon", "Quackenbush", "Bridgemont", "4821", "555-0199", "Customer A", "100 A Example"):
            assert private not in t, (path, private)
    assert "bridgemont" not in client.get("/local/spring/bridgemont-ln", follow_redirects=False).headers["location"]


def test_insured_and_background_lines_only_when_set(client, settings, repo):
    t = client.get("/local/spring").text.lower()
    assert "liability" not in t and "background" not in t
    t = app_with(settings, repo, liability_coverage="$2M").get("/local/spring").text
    assert "$2M liability coverage" in t and "Background-checked" not in t
    t = app_with(settings, repo, liability_coverage="", crew_background_checked=True).get("/local/spring").text
    assert "Background-checked crew" in t and "liability" not in t.lower()


def test_causes_come_from_settings(client, settings, repo):
    t = client.get("/local/cleveland").text
    assert html.escape(settings.charity_toys_name) in t and html.escape(settings.charity_nicu_name) in t
    assert "2% of every visit's price goes to the cause you pick" in t
    t = app_with(settings, repo, charity_vfw_name="VFW Post 0000 (test)").get("/local/cleveland").text
    assert "VFW Post 0000 (test)" in t


def test_business_name_cannot_break_out_of_json_ld(settings, repo):
    name = 'Bob</script><script>alert(1)</script> & "Sons"'
    t = app_with(settings, repo, business_name=name).get("/local/spring").text
    assert "<script>alert(1)" not in t and "&lt;/script&gt;" in t
    assert t.count("</script>") == t.count("<script")
    assert by_type(json_ld(t))["HomeAndConstructionBusiness"]["name"] == name


def test_home_footer_links_every_area(client):
    t = client.get("/").text
    assert 'href="/local"' in t and all(f'href="/local/{a.slug}"' in t for a in AREAS)


# ---------- Review fixes: full days, duplicate text, wording, Spanish ----------
def test_next_day_skips_days_that_are_already_full(client, repo, settings):
    from .test_api_flow import book
    settings.daily_job_quota = 2
    with patch("app.main.local_now", return_value=NOW):
        monday = date(2026, 10, 19)
        assert book(client, "A", "0100", day=monday).status_code == 201 and book(client, "B", "0101", day=monday).status_code == 201
    with patch("app.local_pages.local_now", return_value=NOW):
        t = client.get("/local/spring").text
    assert "Monday, October 19" not in t and "Monday, October 26" in t      # Spring's Monday the 19th is full
    for private in ("Customer A", "100 A Example Rd"):
        assert private not in t


def test_area_pages_share_no_city_swapped_headings(client):
    for a in AREAS:
        t = client.get(f"/local/{a.slug}").text
        assert f"Why {a.city} homeowners" not in t and f"Mowing prices in {a.city}" not in t
        assert f"Book your {a.city} mow" not in t and f"Where we mow in {a.city}" not in t
        assert f"Veteran-owned · Based in Spring, TX · Serving {a.city}" in t
        assert "you never pay extra" not in t and "not added on top" in t


def test_each_area_states_its_own_full_property_size_and_county(client):
    from app.pricing import bracket_profile
    for a in AREAS:
        t = client.get(f"/local/{a.slug}").text
        full = zone_by_key(a.zone_key).full_property_sqft
        prices = " / ".join(dollars(yield_mow_fee(full, k)) for k in YARD_TYPES)
        assert f"about {full:,} sq ft ({bracket_profile(full)}): {prices} before tax" in t
        assert f"<span>{a.county}</span>" in t
    assert "about 14,500 sq ft" in client.get("/local/cleveland").text and "about 8,000 sq ft" in client.get("/local/spring").text


def test_meta_descriptions_fit_in_search_results(client):
    for path in AREA_PATHS + HOOD_PATHS:
        t = client.get(path).text
        d = html.unescape(re.search(r'<meta name="description" content="([^"]+)"', t).group(1))
        assert len(d) <= 160, (path, len(d))


def test_real_charity_names_appear_only_once_the_owner_sets_them(client, settings, repo):
    t = client.get("/local/spring").text
    assert "Veterans of Foreign Wars" not in t and "Local veterans and their families" in t
    t = app_with(settings, repo, charity_vfw_name="VFW Post 0000 (test)").get("/local/spring").text
    assert "VFW Post 0000 (test)" in t and "Local veterans and their families" not in t


def test_trailing_slash_and_odd_paths(client):
    r = client.get("/local/", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/local"
    r = client.get("/local//spring", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/local/spring"
    r = client.get("/local//nowhere", follow_redirects=False)
    assert r.status_code == 404 and "text/html" in r.headers["content-type"] and "nowhere" not in r.text


def test_area_pages_load_the_spanish_switch(client):
    assert '<script src="/static/i18n.js?v=' in client.get("/local/klein").text
    assert '<script src="/static/i18n.js?v=' in client.get("/local").text


def test_server_pages_share_the_post_one_footer_and_hero(client):
    """Every server-rendered page: the Post Green hero band, the public name in the footer, the legal name in the legal line."""
    for path in ("/local", "/local/spring", "/about", "/privacy", "/terms", "/refunds", "/local/nowhere", "/no-such-page"):
        t = client.get(path, headers={"Accept": "text/html"}).text
        assert 'class="site local page-server-pages' in t and 'class="sp-hero' in t, path
        assert re.search(r'<p class="footer-copy">© \d{4} Post One Lawn Co\.</p>', t), path
        assert '<p class="legal-line">Post One Lawn Co. is operated by Semper Green LLC · <a href="/privacy">Privacy</a>' in t, path
        assert '<p class="footer-tagline">On post. On time.</p>' in t, path


def test_area_pages_point_to_the_home_address_check(client):
    """"Check your address" goes to the address form on the home page, which really has that id."""
    assert 'id="area-checker"' in client.get("/").text
    assert client.get("/local").text.count('href="/#area-checker"') == 1
    t = client.get("/local/klein").text
    assert 'href="/#area-checker"' in t and 'href="/#areas"' not in t
    assert t.count('<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">') == 3      # one icon per trust line


def test_every_neighborhood_page_renders_with_its_own_text(client):
    seen = set()
    for h, path in zip(HOODS, HOOD_PATHS):
        r = client.get(path)
        assert r.status_code == 200 and "{{" not in r.text, path
        assert f"<h1 id=\"hood-title\">Lawn mowing in {html.escape(h.name)}</h1>" in r.text
        assert html.escape(h.intro) in r.text and h.intro not in seen
        seen.add(h.intro)
        area = next(a for a in AREAS if a.slug == h.area)
        day = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"][zone_by_key(area.zone_key).service_weekday]
        assert f"every {day}" in r.text and f'href="/local/{area.slug}"' in r.text
        assert f'<link rel="canonical" href="http://testserver{path}">' in r.text
        crumbs = by_type(json_ld(r.text))["BreadcrumbList"]["itemListElement"]
        assert [c["name"] for c in crumbs] == ["Home", "Areas we serve", f"{area.city}, TX", h.name]


def test_neighborhoods_are_inside_served_areas_only(client):
    for h in HOODS:
        area = next(a for a in AREAS if a.slug == h.area)
        assert h.name in area.places
    for path in ("/local/the-woodlands", "/local/spring/the-woodlands", "/local/oak-ridge-north"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code in (301, 404) and "woodlands" not in r.headers.get("location", ""), path


def test_area_pages_link_their_neighborhoods(client):
    page = client.get("/local/colony-ridge").text
    for slug in ("santa-fe", "grand-san-jacinto", "montebello", "camino-real", "bella-vista"):
        assert f'href="/local/colony-ridge/{slug}"' in page


def test_neighborhood_shortcuts_redirect_to_the_canonical_page(client):
    for path, target in (("/local/woodsons-reserve", "/local/spring/woodsons-reserve"),
                         ("/local/klein/the-canopies", "/local/new-caney/the-canopies"),
                         ("/local/splendora/porters-mill", "/local/new-caney/porters-mill"),
                         ("/local/cleveland/Grand-Oaks-Reserve", "/local/cleveland/grand-oaks-reserve")):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 301 and r.headers["location"] == target, path


def test_every_public_page_has_canonical_and_share_tags(client):
    for path in ("/", "/book", "/about", "/team", "/privacy", "/terms", "/refunds", "/local", "/services", *SERVICE_PATHS,
                 *AREA_PATHS, *HOOD_PATHS):
        t = client.get(path).text
        assert t.count('rel="canonical"') == 1 and f'<link rel="canonical" href="http://testserver{path}">' in t, path
        assert t.count('property="og:image"') == 1 and 'content="http://testserver/static/icons/post-one-share.jpg"' in t, path


def test_home_faq_days_match_the_area_schedule(client):
    from app.zones import SERVICE_ZONES, WEEKDAY_NAMES
    page = html.unescape(client.get("/").text)
    assert 'id="faq"' in page and "Do I have to sign a contract?" in page
    names = {"SPRING_LUXURY_LOOP": "Spring", "KLEIN_CORE": "Klein", "I69_HIGH_DENSITY_SPINE": "New Caney and Splendora",
             "COLONY_RIDGE": "Colony Ridge", "CLEVELAND_HUB": "Cleveland and Plum Grove"}
    for z in SERVICE_ZONES:
        assert f"{names[z.key]} on {WEEKDAY_NAMES[z.service_weekday]}s" in page, z.key


def test_service_pages_quote_only_what_the_price_list_charges(client):
    from app.pricing import ADD_ONS
    for s, path in zip(SERVICES, SERVICE_PATHS):
        r = client.get(path)
        assert r.status_code == 200 and "{{" not in r.text, path
        assert f'<h1 id="svc-title">{html.escape(s.name)} in Spring, TX</h1>' in r.text
        crumbs = by_type(json_ld(r.text))["BreadcrumbList"]["itemListElement"]
        assert [c["name"] for c in crumbs] == ["Home", "Services", s.name]
        if s.add_on and ADD_ONS[s.add_on]["price"]:
            assert f"{dollars(ADD_ONS[s.add_on]['price'])} per visit" in r.text
    mow = client.get("/services/lawn-mowing").text
    assert all(dollars(p) in mow for p in all_prices())
    assert "Free quote" in client.get("/services/holiday-lighting").text


def test_services_index_and_links(client):
    page = client.get("/services").text
    for path in SERVICE_PATHS:
        assert f'href="{path}"' in page and f'href="{path}"' in client.get("/").text
    r = client.get("/services/Lawn-Mowing", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/services/lawn-mowing"
    assert client.get("/services/pressure-washing", follow_redirects=False).headers["location"] == "/services"
