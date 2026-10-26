"""The owner's numbers: KPIs from real bookings and routes, and planning numbers until visits are done."""

from datetime import date, timedelta
from unittest.mock import patch

from app.numbers import compute, pre_tax

from .test_api_flow import CREW, NOW, TOMORROW
from .test_visit_owner import booked

TODAY = date(2026, 10, 14)


def row(cid, status="completed", day=TODAY - timedelta(days=3), subtotal=80.0, zone="KLEIN_CORE"):
    return {"customer_id": cid, "scheduled_date": day, "status": status, "zone_key": zone, "subtotal": subtotal,
            "tax_amount": 6.6, "amount_due": subtotal + 6.6, "amount_paid": subtotal + 6.6, "charity_amount": 1.6,
            "donation": 0, "payment_status": "paid", "service_minutes": 45, "source": None, "created_at": None}


def test_kpis_from_real_visits(settings):
    rows = [row("c1"), row("c1", day=TODAY - timedelta(days=10)), row("c2"), row("c3"), row("c4", status="cancelled")]
    routes = [{"route_date": TODAY - timedelta(days=3), "total_distance_m": 16093.44, "total_duration_s": 1200},
              {"route_date": TODAY - timedelta(days=10), "total_distance_m": 0, "total_duration_s": 1200}]
    ahead = [row("c5", status="scheduled", day=TODAY + timedelta(days=5))]
    d = compute(rows, rows, routes, ahead, settings, TODAY, 28)
    a = d["actual"]
    assert a["visits"] == 4 and a["revenue"] == 320 and a["avg_ticket"] == 80 and a["giving"] == 6.4
    assert a["cancel_rate"] == 0.2                          # 1 of 5 bookings
    assert a["repeat_rate"] == round(1 / 3, 3)              # c1 came twice; c4 cancelled and doesn't count
    assert a["lawn_share"] == round(180 / 220, 3) and a["per_crew_hour"] == round(320 / (220 / 60), 2)
    assert a["visits_per_week"] == 1.0 and a["miles"] == 10.0
    u = d["unit"]
    assert u["basis"] == "actual" and u["ticket"] == 80 and u["onsite_min"] == 45 and u["drive_min"] == 10 and u["miles"] == 2.5
    assert d["areas"] == [{"area": "Klein", "visits": 4, "revenue": 320.0}]
    assert d["ahead"] and all(x["area"] for x in d["ahead"])          # only area days, each named
    assert sum(x["booked"] for x in d["ahead"]) == 1


def test_planning_numbers_before_any_visits(settings):
    d = compute([], [], [], [], settings, TODAY, 90)
    assert d["unit"]["basis"] == "planning" and d["unit"]["ticket"] == 75.0 and d["unit"]["onsite_min"] == 45
    assert d["actual"]["avg_ticket"] is None and d["actual"]["cancel_rate"] is None and d["fill_rate"] == 0


def test_pre_tax_falls_back_for_older_bookings():
    assert pre_tax({"subtotal": None, "amount_due": 86.6, "tax_amount": 6.6}) == 80
    assert pre_tax({"subtotal": 70.0, "amount_due": 999}) == 70


def test_owner_only_page_and_api(client):
    booked(client, "A", "0100")
    assert client.get("/api/owner/numbers").status_code in (401, 403)
    with patch("app.numbers.local_now", return_value=NOW):
        d = client.get("/api/owner/numbers?days=30", headers=CREW).json()
    assert d["period"]["days"] == 30 and any(x["date"] == TOMORROW.isoformat() and x["booked"] == 1 for x in d["ahead"])
    page = client.get("/owner/numbers")
    assert page.status_code == 200 and "noindex" in page.headers.get("x-robots-tag", "")
    assert 'href="/owner/numbers"' in client.get("/owner/command").text
