"""Privacy policy, terms (damage policy), refund policy, texting consent and the "delete my information" request."""

import html
import re
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.legal_pages import SMS_CONSENT
from app.main import create_app
from app.nightly import run_nightly

from .conftest import FakeGeocoder
from .test_api_flow import CREW, NOW, TOMORROW, book
from .test_visit_owner import JPEG, booked, owner_get


def app_with(settings, repo, **changes) -> TestClient:
    for k, v in changes.items():
        setattr(settings, k, v)
    return TestClient(create_app(settings, repo=repo, geocoder=FakeGeocoder()))


# ---------- Policy pages ----------
def test_policy_pages_name_the_business_and_how_to_reach_it(client, settings):
    for path, words in (("/privacy", "We do not sell your information"), ("/terms", 'id="damage"'),
                        ("/refunds", "full refund")):
        r = client.get(path)
        assert r.status_code == 200 and "noindex" not in r.text and "{{" not in r.text
        t = r.text
        assert words in t and "Semper Green LLC, doing business as Post One Lawn Co." in t
        assert 'href="mailto:' not in t and 'href="tel:' not in t     # email and phone only once they're set
        assert "reply to any of our text messages" in t
    t = app_with(settings, client.app.state.repo, business_phone="(281) 555-0199",
                 business_email="hello@example.com").get("/refunds").text
    assert 'href="tel:2815550199">(281) 555-0199</a>' in t and 'href="mailto:hello@example.com"' in t


def test_damage_policy_is_specific_and_only_claims_insurance_when_set(client, settings, repo):
    t = client.get("/terms").text
    for words in ("within <strong>72 hours</strong>", "Hidden or unmarked items", "invisible dog fence",
                  "repair it, have it repaired", "indirect or consequential", "Texas law"):
        assert words in t, words
    assert "liability coverage" not in t
    t = app_with(settings, repo, liability_coverage="$2M").get("/terms").text
    assert "We carry $2M in commercial general liability coverage." in t


def test_privacy_policy_matches_what_the_app_does(client):
    t = client.get("/privacy").text
    for words in ("Stripe", "Twilio", "Supabase", "Render", "Reply\n          <strong>STOP</strong>", "4 years",
                  "Delete my information", "We do not use advertising or tracking cookies"):
        assert words in t, words


def test_every_customer_page_links_the_policies_and_contact(client, settings):
    with patch("app.main.local_now", return_value=NOW):
        job = book(client, "A", "0100").json()
    paths = ("/", "/book", "/team", "/visit", f"/pay/{'x' * 20}", "/local/spring")
    for path in paths:
        t = client.get(path).text
        assert all(f'href="/{p}"' in t for p in ("privacy", "terms", "refunds")), path
        assert "Semper Green LLC" in t and 'href="tel:' not in t, path     # no phone until BUSINESS_PHONE is set
    c = app_with(settings, client.app.state.repo, business_phone="(281) 555-0199")
    for path in paths:
        assert 'href="tel:2815550199">(281) 555-0199</a>' in c.get(path).text, path
    assert job["access_code"]


def test_sitemap_lists_the_policies(client):
    t = client.get("/sitemap.xml").text
    assert all(f"/{p}</loc>" in t for p in ("privacy", "terms", "refunds"))


# ---------- Texting consent ----------
def test_booking_form_asks_for_texting_consent(client):
    t = client.get("/book").text
    assert re.search(r'<input type="checkbox" id="sms-consent" name="sms_consent" required>', t)
    assert html.escape(SMS_CONSENT.format(brand="Post One Lawn Co.", legal="Semper Green LLC")) in t and "Reply STOP to opt out" in t
    assert "{{SMS_CONSENT}}" not in t


def test_booking_without_consent_is_refused(client, sms):
    def post(consent):
        with patch("app.main.local_now", return_value=NOW):
            return client.post("/api/jobs", json={
                "name": "Customer A", "phone": "(281) 555-0100", "address": "100 A Example Rd", "service": "mowing",
                "lawn_sqft": 5000, "package": "standard", "scheduled_date": TOMORROW.isoformat(), "sms_consent": consent})
    r = post(False)
    assert r.status_code == 422 and "tick the box" in r.json()["detail"] and sms.sent == []
    assert post(True).status_code == 201 and len(sms.sent) == 1


# ---------- Delete my information ----------
def test_delete_my_information_erases_personal_details_but_keeps_tax_records(client, repo, settings):
    job = booked(client)
    code = job["access_code"].replace("-", "")
    assert client.post(f"/api/visit/{code}/forget", json={"confirm": True}).status_code == 409   # visit still ahead
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    client.post(f"/api/stops/{stop['stop_id']}/photos", headers=CREW, json={"kind": "after", "photo": JPEG})
    client.put(f"/api/stops/{stop['stop_id']}/note", headers=CREW, json={"note": "Gate code 1234"})
    client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"cash_collected": 113.66})

    assert client.post(f"/api/visit/{code}/forget", json={"confirm": False}).status_code == 422
    r = client.post(f"/api/visit/{code}/forget", json={"confirm": True})
    assert r.status_code == 200 and r.json() == {"deleted": True}

    assert client.get(f"/api/visit/{code}").status_code == 404                     # the code no longer works
    j = repo.jobs[job["id"]]
    cust = repo.customers[j["customer_id"]]
    assert cust["name"] == "Deleted customer" and re.fullmatch(r"\+999\d{10}", cust["phone"])
    assert j["address"] == "Deleted at the customer's request" and j["pay_token"] is None
    assert (j["lat"], j["lng"]) == (round(j["lat"], 2), round(j["lng"], 2))
    assert repo.list_job_photos(job["id"]) == [] and not repo.stop_notes(repo.stops[stop["stop_id"]]["route_id"])
    day = owner_get(client, f"/api/owner/day/{TOMORROW}").json()
    assert day["jobs"][0]["customer_name"] == "Deleted customer" and day["totals"]["collected"] == 113.66
    for leftover in ("Customer A", "0100", "100 A Example Rd"):
        assert leftover not in str(day)


def test_delete_needs_a_real_code(client):
    assert client.post("/api/visit/ABCD-EFGH/forget", json={"confirm": True}).status_code == 404
    assert client.post("/api/visit/not-a-code/forget", json={"confirm": True}).status_code == 404


def test_visit_page_has_the_delete_button(client):
    assert 'id="forget-btn">Delete my information</button>' in client.get("/visit").text


def test_policies_name_the_dba_and_link_each_other(client, settings, repo):
    """Each policy says who the customer deals with (the LLC, doing business as the public name) and links the others."""
    for path, title in (("/privacy", "Privacy Policy"), ("/terms", "Terms of Service"), ("/refunds", "Refund & Cancellation Policy")):
        t = client.get(path).text
        assert f'<a href="{path}" aria-current="page">{html.escape(title)}</a>' in t, path
        assert t.count('aria-current="page"') == 2, path            # this policy in the side list, and the breadcrumb
        assert all(f'href="/{p}"' in t for p in ("privacy", "terms", "refunds"))
    assert 'Semper Green LLC, doing business as Post One Lawn Co. ("we") mows lawns' in client.get("/privacy").text
    assert "between you and Semper Green LLC, doing business as Post One Lawn Co., when you book" in client.get("/terms").text
    t = app_with(settings, repo, business_name="Acme Lawn Care").get("/privacy").text
    assert "Semper Green LLC, doing business as Acme Lawn Care" in t and "Post One" not in t


def test_refund_policy_matches_what_the_app_enforces(client):
    """Online cancel closes at the on-the-way text (app/changes.py), weather goes to the Saturday make-up, a locked-out
    visit isn't refunded, and the price is never raised on site without the customer's OK."""
    t = client.get("/refunds").text
    assert "until we text that the crew is on the way" in t and "can no longer be cancelled or refunded" in t
    assert "We mow through light rain" in t and "Saturday" in t
    assert "<strong>are not refunded</strong>" in t
    assert "before the crew arrives" not in t
    terms = client.get("/terms").text
    assert "We never charge your card more without your OK" in terms and "October 22, 2026" in terms
    for path in ("/", "/services/lawn-mowing", "/llms.txt"):
        assert "before the crew arrives" not in client.get(path).text, path


def test_pages_never_say_the_price_changes_on_site(client):
    """The terms lock the price at booking; the home page and booking form say the same."""
    for path in ("/", "/book"):
        t = client.get(path).text
        assert "the price only changes if" not in t, path
        assert "never charged more without your OK" in t, path
