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


def test_booking_info_offers_the_rates_and_causes(client):
    info = client.get("/api/booking-info").json()
    assert info["sqft_rates"] == [0.009, 0.01, 0.011] and info["default_sqft_rate"] == 0.01
    assert [c["percent"] for c in info["charities"]] == [33, 33, 34]


def test_a_rate_off_the_menu_is_refused(client):
    with patch("app.main.local_now", return_value=NOW):
        r = client.post("/api/jobs", json={"name": "Pat Doe", "phone": "2815550100", "address": "100 A Example Rd",
                                           "service": "mowing", "scheduled_date": TOMORROW.isoformat(),
                                           "lawn_size": "large", "sqft_rate": 0.002})
    assert r.status_code == 422 and "0.9¢, 1.0¢ or 1.1¢" in r.text


def test_cash_donation_is_split_and_shown_to_the_customer(client, repo, settings):
    with patch("app.main.local_now", return_value=NOW):
        job = client.post("/api/jobs", json={"name": "Pat Doe", "phone": "2815550100", "address": "100 A Example Rd",
                                             "service": "mowing", "scheduled_date": TOMORROW.isoformat()}).json()
    run_nightly(repo, settings, TOMORROW)
    stop = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"][0]
    client.post(f"/api/stops/{stop['stop_id']}/complete", headers=CREW, json={"cash_collected": 64.13})   # $54.13 + $10
    pay = client.get(f"/api/visit/{job['access_code'].replace('-', '')}").json()["payment"]
    assert pay["donation"] == 10.0
    assert [(c["key"], c["amount"]) for c in pay["donation_ledger"]] == [("vfw", 3.3), ("nicu", 3.3), ("at_risk_youth", 3.4)]


def test_donations_from_before_the_split_show_no_ledger(client, repo, settings):
    with patch("app.main.local_now", return_value=NOW):
        job = client.post("/api/jobs", json={"name": "Pat Doe", "phone": "2815550100", "address": "100 A Example Rd",
                                             "service": "mowing", "scheduled_date": TOMORROW.isoformat()}).json()
    repo.mark_paid(job["id"], method="cash", amount_paid=60.0, donation=5.87)   # recorded the old way, no split
    pay = client.get(f"/api/visit/{job['access_code'].replace('-', '')}").json()["payment"]
    assert pay["donation"] == 5.87 and pay["donation_ledger"] == []
