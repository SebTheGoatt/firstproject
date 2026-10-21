"""Marketing hub, attribution, and the SEO / GEO pieces (FAQ data, llms.txt, robots, profiles)."""
import html
import json
import re
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.local_pages import AREAS
from app.main import create_app

from .conftest import FakeGeocoder
from .test_api_flow import CREW, NOW, TOMORROW

LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def book_from(client, letter, phone, source=None):
    body = {"name": f"Customer {letter}", "phone": f"(281) 555-{phone}", "address": f"100 {letter} Example Rd",
            "service": "mowing", "lawn_sqft": 5000, "yard_type": "STANDARD", "scheduled_date": TOMORROW.isoformat(),
            "sms_consent": True, "payment_method": "cash"}
    if source:
        body["source"] = source
    with patch("app.main.local_now", return_value=NOW):
        return client.post("/api/jobs", json=body)


def test_bookings_carry_their_source_into_the_scoreboard(client, repo):
    assert book_from(client, "A", "0100", "yard-sign-spring").status_code == 201
    assert book_from(client, "B", "0101", "ai-chatgpt").status_code == 201
    assert book_from(client, "C", "0102").status_code == 201
    assert book_from(client, "D", "0103", "Bad Tag!").status_code == 422            # only short lowercase labels
    d = client.get("/api/owner/marketing", headers=CREW).json()
    names = {c["name"]: c["bookings"] for c in d["last_30"]["channels"]}
    assert names["Yard sign"] == 1 and names["ChatGPT"] == 1 and d["last_30"]["total"] == 3
    assert any(n.startswith("Not tracked") for n in names)
    assert {t["name"] for t in d["last_90"]["tags"]} == {"yard-sign-spring", "ai-chatgpt"}
    assert client.get("/api/owner/marketing").status_code in (401, 403)


def test_a_missing_source_column_never_blocks_a_booking(client, repo):
    with patch.object(repo, "set_job_source", side_effect=RuntimeError("column source does not exist")):
        assert book_from(client, "A", "0100", "flyer-klein").status_code == 201
    with patch.object(repo, "bookings_by_source", side_effect=RuntimeError("missing")):
        assert client.get("/api/owner/marketing", headers=CREW).json()["tracking_ready"] is False


def test_week_posts_use_real_prices_days_and_tagged_links(client):
    with patch("app.marketing.local_now", return_value=NOW), patch("app.booking.local_now", return_value=NOW):
        posts = client.get("/api/owner/marketing", headers=CREW).json()["posts"]
    assert posts and all(p["date"] > NOW.date().isoformat() for p in posts)
    for day in posts:
        for p in day["posts"]:
            assert "$75" in p["en"] and "$75" in p["es"]
            if p["channel"] != "instagram":
                assert f"?ref={p['channel']}-{day['slug']}" in p["en"]
    assert "25 openings" not in json.dumps(posts)                                   # counts only when actually short


def test_qr_codes_and_prints_only_for_our_own_pages(client):
    r = client.get("/marketing/qr.svg?path=/local/klein&ref=yard-sign-klein")
    assert r.status_code == 200 and r.headers["content-type"] == "image/svg+xml" and b"<svg" in r.content
    for bad in ("/marketing/qr.svg?path=https://evil.example&ref=x", "/marketing/qr.svg?path=/local/klein&ref=Bad Tag"):
        assert client.get(bad).status_code == 404
    for kind in ("yard-sign", "door-hanger", "flyer"):
        page = client.get(f"/owner/marketing/print?kind={kind}&path=/local/klein&ref={kind}-klein")
        assert page.status_code == 200 and "<svg" in page.text and "noindex" in page.text
        assert "Tuesday" in page.text                                               # Klein's real day
    assert client.get("/owner/marketing/print?kind=billboard&path=/&ref=x").status_code == 404
    assert client.get("/owner/marketing").status_code == 200


def test_home_faq_data_matches_the_visible_faq(client):
    t = client.get("/").text
    faq = next(json.loads(b) for b in LD.findall(t) if json.loads(b).get("@type") == "FAQPage")
    visible = [html.unescape(q) for q in re.findall(r"<summary>(.*?)</summary>", t)]
    assert [q["name"] for q in faq["mainEntity"]] == visible and len(visible) >= 6


def test_area_pages_answer_their_own_questions(client):
    for a in AREAS:
        t = client.get(f"/local/{a.slug}").text
        graph = json.loads(LD.findall(t)[0])["@graph"]
        faq = next(n for n in graph if n["@type"] == "FAQPage")
        for q in faq["mainEntity"]:
            assert html.escape(q["name"]) in t and html.escape(q["acceptedAnswer"]["text"]) in t


def test_llms_txt_states_the_facts_from_live_data(client):
    t = client.get("/llms.txt")
    assert t.status_code == 200 and t.headers["content-type"].startswith("text/plain")
    for fact in ("# Post One Lawn Co.", "Monday: Spring", "Friday: Cleveland", "$75", "Neighbor discount", "/book"):
        assert fact in t.text
    assert "cash to the crew" in t.text                                             # no Stripe in this test app


def test_robots_welcomes_ai_search_and_keeps_private_pages_out(client):
    r = client.get("/robots.txt").text
    for bot in ("OAI-SearchBot", "PerplexityBot", "ClaudeBot", "Google-Extended"):
        assert f"User-agent: {bot}\nAllow: /" in r
    for private in ("/crew", "/owner", "/api/", "/pay/", "/visit/"):
        assert f"Disallow: {private}" in r


def test_social_profiles_appear_only_when_set(settings, repo):
    c = TestClient(create_app(settings, repo=repo, geocoder=FakeGeocoder(), sms=None))
    biz = json.loads(LD.findall(c.get("/").text)[0])
    assert "sameAs" not in biz
    settings.facebook_url, settings.instagram_url, settings.yelp_url = "https://facebook.com/postone", "not-a-link", ""
    c = TestClient(create_app(settings, repo=repo, geocoder=FakeGeocoder(), sms=None))
    assert json.loads(LD.findall(c.get("/").text)[0])["sameAs"] == ["https://facebook.com/postone"]
