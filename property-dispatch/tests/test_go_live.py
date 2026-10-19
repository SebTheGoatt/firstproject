"""Go-live readiness: production settings, the dispatch manifest (+ email backup), home page structured data."""

import json
import re
from unittest.mock import patch

import httpx

from app.config import Settings
from app.manifest import build_manifest, email_manifest
from app.nightly import run_nightly
from app.readiness import checks

from .test_api_flow import CREW, NOW, TOMORROW, book
from .test_local_pages import app_with


def test_production_matrix_names_are_understood(monkeypatch):
    for k, v in {"BASE_YARD_LATITUDE": "30.0102", "BASE_YARD_LONGITUDE": "-95.4201", "TWILIO_PHONE_NUMBER": "+19365550100",
                 "GOOGLE_MAPS_API_KEY": "AIzaTest", "RESEND_API_KEY": "re_test", "OPERATIONAL_ALERT_EMAIL": "ops@example.com",
                 "ENVIRONMENT": "production", "STRIPE_PUBLISHABLE_KEY": "pk_live_x", "SECRET_KEY": "s" * 64}.items():
        monkeypatch.setenv(k, v)
    s = Settings(_env_file=None)
    assert (s.base_lat, s.base_lng, s.twilio_from_number, s.google_maps_browser_key) == (30.0102, -95.4201, "+19365550100", "AIzaTest")
    assert (s.resend_api_key, s.operational_alert_email, s.environment) == ("re_test", "ops@example.com", "production")


def booked_route(client, repo, settings, method="cash"):
    with patch("app.main.local_now", return_value=NOW):
        book(client, "A", "0100")
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    client.put(f"/api/stops/{stop['stop_id']}/note", headers=CREW, json={"note": "Gate code 4455, dog in back"})
    return stop


def test_manifest_lists_every_stop_truthfully(client, repo, settings):
    booked_route(client, repo, settings)
    r = client.get(f"/api/owner/manifest/{TOMORROW}", headers=CREW)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    t = r.text
    for words in ("POST ONE LAWN CO. - OFFICIAL DISPATCH MANIFEST", "[STOP #1] - STATUS: PENDING DISPATCH", "100 A Example Rd", "Customer A",
                  "Gate code 4455, dog in back", "COLLECT $113.66 CASH", "DISCIPLINE DICTATES EXECUTION"):
        assert words in t, words
    assert "Pre-Auth" not in t                                    # we never pre-authorize cards
    assert client.get(f"/api/owner/manifest/{TOMORROW}").status_code == 401
    assert client.get("/api/owner/manifest/2030-01-01", headers=CREW).status_code == 404


def test_manifest_email_goes_only_to_the_owner_and_never_raises(client, repo, settings):
    booked_route(client, repo, settings)
    sent = []

    def handler(req):
        sent.append((req.headers["authorization"], json.loads(req.content)))
        return httpx.Response(200, json={"id": "em_1"})

    route = repo.get_route(TOMORROW)
    text = build_manifest(route, {}, settings, TOMORROW)
    assert email_manifest(text, settings, TOMORROW) is False             # not configured: nothing sent
    settings.resend_api_key, settings.operational_alert_email = "re_test", "ops@example.com"
    assert email_manifest(text, settings, TOMORROW, httpx.Client(transport=httpx.MockTransport(handler))) is True
    auth, body = sent[0]
    assert auth == "Bearer re_test" and body["to"] == ["ops@example.com"] and "Customer A" in body["text"]
    down = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(500)))
    assert email_manifest(text, settings, TOMORROW, down) is False


def test_nightly_build_reports_the_manifest_email(repo, settings, client):
    with patch("app.main.local_now", return_value=NOW):
        book(client, "A", "0100")
    assert run_nightly(repo, settings, TOMORROW)["manifest_emailed"] is False


def test_readiness_lists_what_is_missing(client, settings):
    r = client.get("/api/owner/readiness", headers=CREW).json()
    assert r["ready"] is False
    by = {c["key"]: c for c in r["checks"]}
    assert by["database"]["ok"] is False and "DATA_BACKEND" in by["database"]["fix"]
    assert by["stripe_live"]["ok"] is False and by["twilio"]["ok"] is False and by["secrets"]["ok"] is False
    assert by["contact"]["ok"] is False and "BUSINESS_EMAIL" in by["contact"]["fix"]
    assert by["reviews"]["required"] is False and by["phone"]["required"] is False    # a phone line is optional
    assert all("sk_" not in c["fix"] or "…" in c["fix"] for c in r["checks"])    # never echoes a secret
    assert client.get("/api/owner/readiness").status_code == 401
    page = client.get("/owner/readiness")
    assert page.status_code == 200 and page.headers["x-robots-tag"] == "noindex"


def test_readiness_flags_a_leftover_old_business_name(client, settings):
    by = {c["key"]: c for c in client.get("/api/owner/readiness", headers=CREW).json()["checks"]}
    assert by["brand_name"]["ok"] is True and by["brand_name"]["required"] is False
    old = settings.model_copy(update={"business_name": "Semper Green Lawn Care"})    # BUSINESS_NAME still set in Render
    item = next(c for c in checks(old, client.app.state.repo, stripe_enabled=False) if c["key"] == "brand_name")
    assert item["ok"] is False and "BUSINESS_NAME=Post One Lawn Co." in item["fix"]


def test_fully_configured_business_is_ready(settings, repo):
    for k, v in dict(environment="production", stripe_secret_key="sk_live_x", stripe_webhook_secret="whsec_x",
                     twilio_account_sid="AC1", twilio_auth_token="t", twilio_from_number="+19365550100",
                     public_base_url="https://example.com", crew_access_token="c" * 30, webhook_secret="w" * 30,
                     cron_secret="x" * 30, business_email="biz@example.com").items():
        setattr(settings, k, v)    # no BUSINESS_PHONE: a phone line is optional

    class Live:                                # a reachable database with the new columns and no test data
        def __getattr__(self, name):
            return getattr(repo, name)
    items = checks(settings.model_copy(update={"data_backend": "supabase"}), Live(), stripe_enabled=True)
    missing = [c["key"] for c in items if c["required"] and not c["ok"]]
    assert missing == []


def test_home_page_carries_the_business_structured_data(client, settings, repo):
    t = client.get("/").text
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', t, re.S).group(1)
    d = json.loads(block)
    assert d["@type"] == "HomeAndConstructionBusiness" and "telephone" not in d     # no phone until BUSINESS_PHONE is set
    assert d["url"] == "http://testserver/" and d["address"]["postalCode"] == "77373"
    assert [a["name"] for a in d["areaServed"]] == ["Spring, TX", "Klein, TX", "New Caney, TX", "Cleveland, TX", "Colony Ridge, TX"]
    assert d["openingHoursSpecification"][0]["opens"] == "07:00"
    assert "streetAddress" not in d["address"] and "geo" not in d and "{{" not in t
    t = app_with(settings, repo, business_phone="(281) 555-0199").get("/").text
    d = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', t, re.S).group(1))
    assert d["telephone"] == "+12815550199"
