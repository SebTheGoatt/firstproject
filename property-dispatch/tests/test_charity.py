"""Donations split 33% VFW / 33% NICU / 34% at-risk youth, and the pay-what-you-can rate."""

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.charity import CHARITY_SPLIT, describe, split_donation
from app.nightly import run_nightly

from .test_api_flow import CREW, NOW, TOMORROW


@pytest.mark.parametrize("amount, expected", [
    (5, {"vfw": 1.65, "nicu": 1.65, "at_risk_youth": 1.70}),
    (10, {"vfw": 3.30, "nicu": 3.30, "at_risk_youth": 3.40}),
    (0.10, {"vfw": 0.03, "nicu": 0.03, "at_risk_youth": 0.04}),
    (7.77, {"vfw": 2.57, "nicu": 2.56, "at_risk_youth": 2.64}),
])
def test_split_matches_the_percentages(amount, expected):
    assert split_donation(amount) == expected


def test_split_always_adds_up_to_the_donation_to_the_penny():
    for cents in range(1, 5_001):
        amount = Decimal(cents) / 100
        assert sum(Decimal(str(v)) for v in split_donation(amount).values()) == amount, amount
    assert split_donation(0) == {} and split_donation(None) == {}


def test_shares_add_up_to_100_percent_and_names_are_settings(settings):
    assert sum(CHARITY_SPLIT.values()) == 1
    settings.charity_vfw_name = "VFW Post 4010"
    assert [(c["name"], c["percent"]) for c in describe(settings)] == [
        ("VFW Post 4010", 33), ("Neonatal intensive care (NICU) families", 33), ("At-risk youth programs", 34)]


def test_booking_info_offers_the_packages_and_causes(client):
    info = client.get("/api/booking-info").json()
    assert [(p["key"], p["charity_rate"], p["brackets"][1]["price"]) for p in info["packages"]] == [
        ("standard", 0.02, 105), ("supporter", 0.07, 114), ("hero", 0.12, 131)]
    assert "default_package" not in info          # the customer must pick a rate; nothing is preselected
    assert [p["label"] for p in info["packages"]] == ["Neighborhood Block Lock", "Operational Target", "Bi-Weekly Demand"]
    assert info["lawn_sqft_limits"] == {"min": 100, "max": 87_120}
    assert [c["percent"] for c in info["charities"]] == [33, 33, 34]


def test_a_package_off_the_menu_is_refused(client):
    with patch("app.main.local_now", return_value=NOW):
        r = client.post("/api/jobs", json={"name": "Pat Doe", "phone": "2815550100", "address": "100 A Example Rd",
                                           "service": "mowing", "lawn_sqft": 5000, "package": "standard", "scheduled_date": TOMORROW.isoformat(),
                                           "lawn_size": "large", "package": "gold"})
    assert r.status_code == 422 and "supporter" in r.text


def test_cash_donation_is_split_and_shown_to_the_customer(client, repo, settings):
    with patch("app.main.local_now", return_value=NOW):
        job = client.post("/api/jobs", json={"name": "Pat Doe", "phone": "2815550100", "address": "100 A Example Rd",
                                             "service": "mowing", "lawn_sqft": 5000, "package": "standard", "scheduled_date": TOMORROW.isoformat()}).json()
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"cash_collected": 123.66})   # $113.66 + $10
    pay = client.get(f"/api/visit/{job['access_code'].replace('-', '')}").json()["payment"]
    assert pay["donation"] == 10.0
    assert [(c["key"], c["amount"]) for c in pay["donation_ledger"]] == [("vfw", 3.3), ("nicu", 3.3), ("at_risk_youth", 3.4)]


def test_donations_from_before_the_split_show_no_ledger(client, repo, settings):
    with patch("app.main.local_now", return_value=NOW):
        job = client.post("/api/jobs", json={"name": "Pat Doe", "phone": "2815550100", "address": "100 A Example Rd",
                                             "service": "mowing", "lawn_sqft": 5000, "package": "standard", "scheduled_date": TOMORROW.isoformat()}).json()
    repo.mark_paid(job["id"], method="cash", amount_paid=60.0, donation=5.87)   # recorded the old way, no split
    pay = client.get(f"/api/visit/{job['access_code'].replace('-', '')}").json()["payment"]
    assert pay["donation"] == 5.87 and pay["donation_ledger"] == []


def test_booking_info_counts_real_openings_on_the_next_route(client, settings, repo):
    assert client.get("/api/booking-info").json()["spots_left"] == settings.daily_job_quota
    with patch.object(repo, "count_active_jobs", return_value=settings.daily_job_quota - 2):
        assert client.get("/api/booking-info").json()["spots_left"] == 2
    with patch.object(repo, "count_active_jobs", return_value=settings.daily_job_quota + 3):
        assert client.get("/api/booking-info").json()["spots_left"] == 0
    with patch.object(repo, "count_active_jobs", side_effect=RuntimeError("db down")):
        info = client.get("/api/booking-info").json()
    assert info["spots_left"] is None and info["earliest_date"]  # the page still loads


# ---------- The customer picks one cause ----------
from app.charity import chosen_cause, ledger, route_donation  # noqa: E402


def test_route_donation_sends_everything_to_the_pick_or_splits_without_one():
    assert route_donation(7.0, "toys_for_tots") == {"toys_for_tots": 7.0}
    assert route_donation(5, None) == {"vfw": 1.65, "nicu": 1.65, "at_risk_youth": 1.70}
    assert route_donation(0, "vfw") == {} and chosen_cause({"vfw": 3.0}) == "vfw"
    assert chosen_cause({"vfw": 1.65, "nicu": 1.65, "at_risk_youth": 1.70}) is None


def test_booking_with_a_pick_routes_its_giving_and_cash_donation_there(client, repo, settings):
    settings.charity_toys_name = "Marine Toys for Tots, Liberty County"
    with patch("app.main.local_now", return_value=NOW):
        r = client.post("/api/jobs", json={"name": "Customer A", "phone": "(281) 555-0501", "address": "100 A Example Rd",
                                           "service": "mowing", "lawn_sqft": 5000, "package": "supporter",
                                           "scheduled_date": TOMORROW.isoformat(), "charity_choice": "toys_for_tots"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["charity_choice"] == "toys_for_tots" and body["charity_amount"] == 7.98   # 7% of $114
    job = repo.jobs[body["id"]]
    assert job["giving_split"] == {"toys_for_tots": 7.98}
    assert ledger(settings, job["giving_split"]) == [
        {"key": "toys_for_tots", "name": "Marine Toys for Tots, Liberty County", "percent": 100, "amount": 7.98}]

    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    assert stop["charity_choice_name"] == "Marine Toys for Tots, Liberty County"     # the crew can say where extra goes
    done = client.post(f"/api/stops/{stop['stop_id']}/complete", json={"cash_collected": 130}, headers=CREW).json()
    assert done["payment"]["donation_split"] == {"toys_for_tots": round(130 - stop["amount_due"], 2)}


def test_the_booking_page_gets_the_three_causes(client):
    info = client.get("/api/booking-info").json()
    assert [c["key"] for c in info["causes"]] == ["toys_for_tots", "vfw", "nicu"]
    assert all(c["name"] and c["blurb"] for c in info["causes"])


def test_an_unknown_pick_is_refused(client):
    r = client.post("/api/jobs", json={"name": "X", "phone": "(281) 555-0502", "address": "100 A Example Rd",
                                       "lawn_sqft": 5000, "package": "standard", "scheduled_date": TOMORROW.isoformat(),
                                       "charity_choice": "my_pocket"})
    assert r.status_code == 422
