"""Community: sponsored mows (paid in full by a sponsor, never free), private nominations, real public totals, and the
pay page's round-up."""

from datetime import date
from pathlib import Path

import pytest
from unittest.mock import patch

from app.pricing import ADD_ONS, YIELD_BASE

from .test_api_flow import CREW, NOW, TOMORROW

NOMINEE = {"zone_key": "SPRING_LUXURY_LOOP", "nominee_name": "Neighbor D", "nominee_address": "100 D Example Rd",
           "nominee_phone": "(281) 555-0199", "reason": "Recovering from surgery.", "nominator_name": "Friend",
           "nominator_contact": "friend@example.com"}


def sponsor(client, repo, letter="A", phone="0100", paid=True):
    with patch("app.main.local_now", return_value=NOW), patch("app.visit_routes.local_now", return_value=NOW):
        r = client.post("/api/jobs", json={**book_body(letter, phone), "add_ons": ["sponsor_mow"]})
    assert r.status_code == 201, r.text
    job = r.json()
    assert any(a["key"] == "sponsor_mow" and a["price"] == float(YIELD_BASE) for a in job["add_ons"])
    if paid:
        repo.mark_paid(job["id"], method="card", amount_paid=job["total"], donation=0.0)
    return job


def book_body(letter, phone):
    return {"name": f"Customer {letter}", "phone": f"(281) 555-{phone}", "address": f"100 {letter} Example Rd",
            "service": "mowing", "lawn_sqft": 5000, "package": "standard", "scheduled_date": TOMORROW.isoformat()}


def nominate(client, **kw):
    return client.post("/api/nominations", json={**NOMINEE, **kw})


def schedule(client, nid, consent=True, day=TOMORROW):
    with patch("app.community.local_now", return_value=NOW):
        return client.post(f"/api/owner/nominations/{nid}/schedule", json={"day": day.isoformat(), "consent": consent},
                           headers=CREW)


def test_a_sponsored_mow_costs_the_full_base_price():
    assert ADD_ONS["sponsor_mow"]["price"] == YIELD_BASE


def test_the_sponsorship_rides_on_the_bill_but_not_the_crews_stop(client, repo):
    job = sponsor(client, repo, paid=False)
    assert job["add_on_total"] >= float(YIELD_BASE) and job["total"] > job["subtotal"]   # taxed like any mow
    from app.models import order_label
    assert order_label("mowing", job["add_ons"]) == "Mowing"                           # the crew mows this lawn only


def test_nominations_are_private_and_owner_only(client):
    assert nominate(client).status_code == 201
    assert client.get("/api/owner/community").status_code in (401, 403)
    page = client.get("/community")
    assert page.status_code == 200 and "Neighbor D" not in page.text and "Recovering" not in page.text
    data = client.get("/api/owner/community", headers=CREW).json()
    assert [n["nominee_name"] for n in data["nominations"]] == ["Neighbor D"]


def test_nomination_validation_and_honeypot(client, repo):
    assert nominate(client, zone_key="NOWHERE").status_code == 422
    assert nominate(client, reason="").status_code == 422
    assert nominate(client, website="http://spam").status_code == 201        # bots get a thank-you, nothing is kept
    assert repo.list_nominations() == []


def test_no_paid_sponsorship_means_no_sponsored_mow(client, repo):
    nominate(client)
    [n] = repo.list_nominations()
    sponsor(client, repo, paid=False)                                         # booked but not paid: doesn't count
    r = schedule(client, n["id"])
    assert r.status_code == 409 and "sponsorship" in r.json()["detail"]


def test_scheduling_needs_their_ok(client, repo):
    sponsor(client, repo)
    nominate(client)
    [n] = repo.list_nominations()
    assert schedule(client, n["id"], consent=False).status_code == 422


def test_a_paid_sponsorship_books_one_sponsored_mow(client, repo):
    sponsor(client, repo)
    nominate(client)
    nominate(client, nominee_name="Neighbor E", nominee_address="100 E Example Rd", nominee_phone="(281) 555-0198")
    first, second = sorted(repo.list_nominations(), key=lambda n: n["nominee_name"])
    r = schedule(client, first["id"])
    assert r.status_code == 200, r.text
    job = repo.jobs.get(r.json()["job_id"])
    assert job["payment_method"] == "sponsored" and job["payment_status"] == "paid"
    assert job["amount_due"] == 0 and job["access_code"]                       # the neighbor pays nothing, gets a visit page
    assert repo.get_nomination(first["id"])["status"] == "scheduled"
    assert schedule(client, first["id"]).status_code == 409                   # already scheduled
    r = schedule(client, second["id"])                                        # one sponsorship, one mow
    assert r.status_code == 409 and "sponsorship" in r.json()["detail"]
    data = client.get("/api/owner/community", headers=CREW).json()
    assert data["sponsorships"] == {"paid": 1, "used": 1, "waiting": 0}


def test_public_totals_are_real(client, repo):
    page = client.get("/community").text
    assert "Mow it" in page and "nominate" in page and "/book?addon=sponsor_mow" in page
    job = sponsor(client, repo)
    t = repo.community_totals()
    assert t["sponsored_done"] == 0 and t["given"] == round(job.get("charity_amount") or 0, 2)


def test_decline(client, repo):
    nominate(client)
    [n] = repo.list_nominations()
    assert client.post(f"/api/owner/nominations/{n['id']}/decline", headers=CREW).status_code == 200
    assert repo.get_nomination(n["id"])["status"] == "declined"
    assert client.post("/api/owner/nominations/nope/decline", headers=CREW).status_code == 404


def test_pages_and_links(client):
    assert client.get("/owner/community").status_code == 200
    assert "/community" in client.get("/sitemap.xml").text
    assert 'href="/community"' in client.get("/").text and 'href="/owner/community"' in client.get("/owner/command").text
    assert 'id="round-chip"' in (Path(__file__).parent.parent / "static" / "pay.html").read_text()


def round_up(due: float) -> float:
    """Mirror of the pay page's roundUp(): cents to the next $5."""
    c = round(due * 100)
    return ((500 - c % 500) % 500) / 100


def test_round_up_math():
    assert round_up(86.60) == 3.40 and round_up(80.00) == 0 and round_up(81.19) == 3.81 and round_up(4.99) == 0.01



@pytest.mark.area_days
def test_sponsored_mows_keep_the_one_area_a_day_rule(client, repo):
    from app.models import GeoPoint, Service
    job = repo.create_job(name="Sponsor", phone="+12815550100", address="100 A Example Rd",
                          geo=GeoPoint(lat=30.15, lng=-95.39, formatted_address="100 A Example Rd"), service=Service.MOWING,
                          scheduled_date=date(2026, 10, 19), service_minutes=45, zone_key="SPRING_LUXURY_LOOP",
                          quoted_price=75.0, add_ons=[{"key": "sponsor_mow", "label": "Sponsor a neighbor's mow", "price": 75.0}])
    repo.mark_paid(job["id"], method="card", amount_paid=81.19, donation=0.0)
    nominate(client)
    [n] = repo.list_nominations()
    r = schedule(client, n["id"])                                             # the test day is a Thursday; Spring is Mondays
    assert r.status_code == 409 and "Monday" in r.json()["detail"]
    assert schedule(client, n["id"], day=date(2026, 10, 19)).status_code == 200
