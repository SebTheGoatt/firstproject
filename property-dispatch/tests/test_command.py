"""Owner command view: real numbers only. Anything not tracked is None, never a made-up value."""
from unittest.mock import patch

from .test_api_flow import CREW, NOW, TOMORROW, book


def test_command_view_is_owner_only(client):
    assert client.get("/api/owner/command").status_code in (401, 403)
    page = client.get("/owner/command")
    assert page.status_code == 200 and page.headers["x-robots-tag"] == "noindex" and "{{" not in page.text


def test_command_view_reports_bookings_and_never_invents_numbers(client, settings):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
    with patch("app.command.local_now", return_value=NOW):
        d = client.get("/api/owner/command", headers=CREW).json()
    assert d["revenue_mtd"] == {"bookings": 0, "expected": 0.0, "collected": 0.0, "unpaid": 0.0, "sales_tax": 0.0,
                                "paid_count": 0}                     # nothing scheduled earlier this month
    tomorrow = next(w for w in d["week"] if w["date"] == TOMORROW.isoformat())
    assert tomorrow["jobs"] == 1 and tomorrow["area"] == "Colony Ridge"       # Thursday's area
    (row,) = d["terminal"]
    assert row["status"] == "PENDING DISPATCH" and row["area"] == "Spring" and row["off_area"] is True
    assert row["name"] == "Customer A" and row["move_to"] == "2026-10-19"     # INTERCEPT target: Spring's next Monday
    assert d["next_route"] == {"date": TOMORROW.isoformat(), "built": False, "stops": 0}
    df = d["defense"]
    assert df["cgl"] is None and df["stripe_disputes"] is None and df["fleet"] is None   # not on file / not tracked
    assert df["tda"].startswith("N/A")
