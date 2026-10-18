"""Local service-area pages (/local), the sitemap and robots.txt."""

import dataclasses
import html
import json
import re
import xml.etree.ElementTree as ET
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import urlparse

from fastapi.testclient import TestClient

from app.local_pages import AREAS
from app.main import create_app
from app.pricing import PACKAGES, PRICE_BRACKETS
from app.zones import zone_by_key

from .conftest import FakeGeocoder
from .test_api_flow import NOW, TOMORROW, book

AREA_PATHS = [f"/local/{a.slug}" for a in AREAS]
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
    return [prices[k] for _, prices in PRICE_BRACKETS for k in PACKAGES]


def test_every_area_page_renders_for_crawlers(client):
    with patch("app.local_pages.local_now", return_value=NOW):
        for a in AREAS:
            r = client.get(f"/local/{a.slug}")
            assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
            t = r.text
            assert f"<h1 id=\"area-title\">Lawn mowing in {a.city}, TX</h1>" in t
            assert f"<title>Lawn Mowing in {a.city}, TX | Semper Green Lawn Care</title>" in t
            assert f'<link rel="canonical" href="http://testserver/local/{a.slug}">' in t
            assert 'property="og:title"' in t and 'property="og:description"' in t and 'name="description"' in t
            assert 'name="viewport"' in t and "/static/styles.css?v=" in t
            assert "noindex" not in t and "{{" not in t
            assert html.escape(a.intro) in t
            assert all(html.escape(p) in t for p in a.places)
            assert all(z in t for z in a.zips)
            assert "8.25% Texas sales tax added" in t
            assert "Thursday, October 15" in t          # next service day you can book, from NOW
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
    assert "Friday, October 16" in t and "Next-day booking closes at 5 PM." in t


def test_price_table_lists_every_tier_and_size(client):
    t = client.get("/local/spring").text
    for p in PACKAGES.values():
        assert f'<th scope="col">{p["label"]}</th>' in t
    for size in ("Up to 3,500 sq ft", "3,501-7,500 sq ft", "7,501-15,000 sq ft", "Over 15,000 sq ft"):
        assert f'<th scope="row">{size}<small>' in t
    for price in all_prices():
        assert f">${price:,.0f}</td>" in t
    # Add-ons with a price, quote-only ones as a free quote; the yard / full property picks are not add-ons.
    assert "Bin cleaning" in t and "Gutter cleaning" in t and "+$15 per visit" in t and "Free quote" in t
    assert "<strong>Yard only</strong>" not in t and "<strong>Full property</strong>" not in t


def test_prices_and_tax_are_read_live(client, monkeypatch):
    bumped = tuple((limit, {k: v + 1 for k, v in prices.items()}) for limit, prices in PRICE_BRACKETS)
    monkeypatch.setattr("app.local_pages.PRICE_BRACKETS", bumped)
    zone = zone_by_key("KLEIN_CORE")
    monkeypatch.setattr("app.local_pages.zone_by_key", lambda key: dataclasses.replace(zone, tax_rate=0.0725))
    t = client.get("/local/klein").text
    assert ">$76</td>" in t and ">$233</td>" in t and "7.25% Texas sales tax added" in t
    assert by_type(json_ld(t))["LocalBusiness"]["priceRange"] == "$76-$233"


def test_json_ld_business_service_and_breadcrumbs(client):
    low, high = min(all_prices()), max(all_prices())
    for a in AREAS:
        nodes = by_type(json_ld(client.get(f"/local/{a.slug}").text))
        assert set(nodes) == {"LocalBusiness", "Service", "BreadcrumbList"}
        biz, svc, crumbs = nodes["LocalBusiness"], nodes["Service"], nodes["BreadcrumbList"]
        assert biz["@id"] == "http://testserver/#business" and biz["name"] == "Semper Green Lawn Care"
        assert biz["priceRange"] == f"${low:,.0f}-${high:,.0f}" == "$75-$232"
        assert {c["name"] for c in biz["areaServed"]} == {f"{x.city}, TX" for x in AREAS}
        assert svc["serviceType"] == "Lawn mowing" and svc["provider"] == {"@id": biz["@id"]}
        assert svc["areaServed"] == {"@type": "City", "name": f"{a.city}, TX"}
        offers = svc["hasOfferCatalog"]["itemListElement"]
        assert len(offers) == len(PRICE_BRACKETS) * len(PACKAGES)
        assert all(o["@type"] == "Offer" and o["priceCurrency"] == "USD" and o["name"] for o in offers)
        assert sorted(Decimal(o["price"]) for o in offers) == sorted(all_prices())
        for p in PACKAGES.values():   # one offer per tier per size bracket
            assert sum(o["name"].startswith(p["label"] + ":") for o in offers) == len(PRICE_BRACKETS)
        items = crumbs["itemListElement"]
        assert [i["name"] for i in items] == ["Home", "Areas we serve", f"{a.city}, TX"]
        assert items[-1]["item"] == f"http://testserver/local/{a.slug}"


def test_json_ld_never_has_ratings_phone_or_street(settings, repo):
    c = app_with(settings, repo, twilio_from_number="+12815550000")    # a texting number is not a business phone
    for path in AREA_PATHS:
        raw = LD_JSON.findall(c.get(path).text)[0]
        for banned in ("aggregateRating", "review", "telephone", "streetAddress", "2815550000"):
            assert banned not in raw, (path, banned)


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
    assert locs == [f"http://testserver{p}" for p in ("/", "/book", "/team", "/local", *AREA_PATHS)]
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
    assert "2% on Neighborhood Block Lock" in t and "12% on Bi-Weekly Demand" in t
    t = app_with(settings, repo, charity_vfw_name="VFW Post 0000 (test)").get("/local/cleveland").text
    assert "VFW Post 0000 (test)" in t


def test_business_name_cannot_break_out_of_json_ld(settings, repo):
    name = 'Bob</script><script>alert(1)</script> & "Sons"'
    t = app_with(settings, repo, business_name=name).get("/local/spring").text
    assert "<script>alert(1)" not in t and "&lt;/script&gt;" in t
    assert t.count("</script>") == t.count("<script")
    assert by_type(json_ld(t))["LocalBusiness"]["name"] == name


def test_home_footer_links_every_area(client):
    t = client.get("/").text
    assert 'href="/local"' in t and all(f'href="/local/{a.slug}"' in t for a in AREAS)


# ---------- Review fixes: full days, duplicate text, wording, Spanish ----------
def test_next_day_skips_days_that_are_already_full(client, repo, settings):
    from .test_api_flow import book
    settings.daily_job_quota = 2
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201 and book(client, "B", "0101").status_code == 201
    with patch("app.local_pages.local_now", return_value=NOW):
        t = client.get("/local/spring").text
    assert "Thursday, October 15" not in t and "Friday, October 16" in t      # the 15th is full
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
    from app.pricing import bracket_price, bracket_profile
    for a in AREAS:
        t = client.get(f"/local/{a.slug}").text
        full = zone_by_key(a.zone_key).full_property_sqft
        prices = " / ".join(f"${bracket_price(full, k):,.0f}" for k in PACKAGES)
        assert f"about {full:,} sq ft ({bracket_profile(full)}): {prices} before tax" in t
        assert f"<span>{a.county}</span>" in t
    assert "about 14,500 sq ft" in client.get("/local/cleveland").text and "about 8,000 sq ft" in client.get("/local/spring").text


def test_meta_descriptions_fit_in_search_results(client):
    for a in AREAS:
        t = client.get(f"/local/{a.slug}").text
        d = html.unescape(re.search(r'<meta name="description" content="([^"]+)"', t).group(1))
        assert len(d) <= 160, (a.slug, len(d))


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
