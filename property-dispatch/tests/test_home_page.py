"""The Post One homepage: the approved layout, the working widgets it keeps, and prices that only come from the pricing data."""
import re
from pathlib import Path

from app.local_pages import AREAS

HOME = Path(__file__).resolve().parents[1].joinpath("static", "home.html")


def test_home_has_the_post_one_sections_and_keeps_every_widget(client):
    t = client.get("/").text
    assert '<p class="po-eyebrow">Lawn mowing · Veteran-owned · Spring, TX</p>' in t
    assert '<h1 id="hero-title">Every yard gets Post&nbsp;One attention.</h1>' in t
    assert '<a class="btn btn-lg po-btn-fresh" href="/book">Get my price</a>' in t and 'href="#pricing">See pricing</a>' in t
    for section in ("how", "pricing", "services", "areas", "story"):
        assert f'<section id="{section}"' in t, section
    # The address check, next open day, map, crew grid and mobile book bar still have the ids their script uses.
    for el in ("area-checker", "check-address", "check-btn", "check-picker", "check-result", "next-day", "cutoff",
               "spots-left", "hero-actions", "final-cta", "install-btn", "install-ios", "area-list", "area-price-note",
               "area-map", "area-map-wrap", "crew", "crew-grid", "book-bar", "bar-day", "mow-from",
               "hero-price", "hero-price-note", "price-rows", "price-tax-note", "year"):
        assert f'id="{el}"' in t, el
    assert all(f'<li><a href="/local/{a.slug}">' in t for a in AREAS)          # an area chip for every area page
    assert "Your yard is our first priority." in t and "Semper Green LLC" in t   # the business pitch; who customers contract with
    assert "Marine Security Guard" not in t                                      # we sell the business, not the founder's service history
    assert "{{" not in t


def test_home_prices_come_only_from_the_pricing_data(client):
    """No dollar amount is written into the page; the script fills them from /api/booking-info."""
    text = HOME.read_text(encoding="utf-8")
    assert not re.search(r"\$\d", text)
    assert 'data-addon-price="bin_cleaning"' in text and 'data-addon-price="gutters"' in text
    info = client.get("/api/booking-info").json()
    assert info["yield"]["base"] > 0 and info["yield"]["included_sqft"] > 0 and info["yield"]["step"] > 0
    add_ons = {a["key"]: a for a in info["add_ons"]}
    assert add_ons["bin_cleaning"]["price"] > 0 and add_ons["gutters"]["price"] > 0


def test_home_makes_no_claims_the_settings_do_not_back(client, settings, repo):
    from fastapi.testclient import TestClient

    from app.main import create_app

    t = client.get("/").text.lower()
    for claim in ("licensed", "insured", "bonded", "clearance", "semper fi", "globe and anchor", "usmc", "tel:", "★★"):
        assert claim not in t, claim
    settings.business_phone = "(281) 555-0199"            # the phone shows only once the owner sets it
    assert 'href="tel:' in TestClient(create_app(settings, repo=repo, sms=None)).get("/").text


def test_scroll_story_reads_prices_and_days_from_the_data(client):
    t = client.get("/").text
    story = t[t.index('<section id="scroll-story"'):t.index('<section id="how"')]
    for el in ("scrolly-from", "scrolly-days", "scrolly-title"):
        assert f'id="{el}"' in story
    assert "$" not in story                                       # the price comes from /api/booking-info
    assert not any(day in story for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"))
    assert 'srcset="/static/img/lawn-stripes-tall.webp"' in story and 'loading="lazy"' in story
    assert client.get("/static/img/lawn-stripes-wide.webp").status_code == 200
