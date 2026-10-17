"""Delegating to the agents: the Today/Tomorrow briefing, the playbook, and the fake mock week."""

import re
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "starnet"))
import semper_green_site as sg  # noqa: E402

from app.models import JobRequest  # noqa: E402
from app.nightly import run_nightly  # noqa: E402

from .test_api_flow import NOW, TOMORROW, book  # noqa: E402
from .test_starnet_setup import box  # noqa: E402,F401  (the fake StarNet computer)


def brief(box, client, settings):
    settings.agent_key_read = "k" * 40
    sg.KEY_FILE.write_text("k" * 40)
    with patch("app.agent_api.local_now", return_value=NOW):
        return sg.briefing(sg.SemperGreenSite(), None)


def test_the_briefing_says_what_is_happening_today_and_whether_tomorrows_route_is_built(box, client, repo, settings):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
        assert book(client, "B", "0101").status_code == 201
    text = brief(box, client, settings)
    assert "Today (Wed Oct 14): 0 booking(s)" in text and "No bookings, so no route." in text
    assert "Tomorrow (Thu Oct 15): 2 booking(s), 0 finished, $173.20 expected, $0.00 collected. Route: NOT BUILT yet" in text
    assert "built automatically at 5 PM" in text
    run_nightly(repo, settings, TOMORROW)
    assert "Route: BUILT (2 stops, 0 finished)" in brief(box, client, settings)
    assert text.index("Today (") < text.index("Tomorrow (") < text.index("Next 7 days:")


def test_the_briefing_flags_a_booking_added_after_the_route_was_built(box, client, repo, settings):
    with patch("app.main.local_now", return_value=NOW):
        book(client, "A", "0100")
    run_nightly(repo, settings, TOMORROW)
    with patch("app.main.local_now", return_value=NOW):
        pass
    repo.create_job(name="Late Add", phone="+12815550133", address="100 B Example Rd",
                    geo=__import__("app.models", fromlist=["GeoPoint"]).GeoPoint(lat=30.12, lng=-95.3, formatted_address="x"),
                    service="mowing", scheduled_date=TOMORROW, service_minutes=40, zone_key="SPRING_LUXURY_LOOP",
                    quoted_price=50.0, payment_method="cash", pay_token="t" * 32, access_code="LATEADD2", tax_rate=0.0825)
    assert "1 booking(s) NOT on it" in brief(box, client, settings)


def test_the_playbook_covers_every_agent_and_only_uses_commands_that_exist(tmp_path):
    path = sg.write_playbook(str(tmp_path / "playbook.md"))
    text = Path(path).read_text(encoding="utf-8")
    for agent in ("The Beyonder", "Marketer", "Recon Radar", "Engineer", "The Overseer", "The Dispatcher",
                  "The Sales Deck", "The Comms Officer"):
        assert f"## {agent}" in text
    for command in re.findall(r"python semper_green_site\.py (--[a-z-]+)", text):
        assert command in ("--brief", "--sync", "--build-route", "--notify"), command    # the only commands agents run
    assert "NEEDS OWNER" in text and "never" in text.lower()
    assert "the website writes and sends the \"on the way\" message" in text and "SECURITY" in text
    for secret_pattern in ("sk_", "whsec_", "AGENT_KEY", "RENDER_API_KEY", "rnd_", "X-Agent-Key"):
        assert secret_pattern not in text                          # no real keys or key settings in the instructions


def test_the_playbook_lines_match_what_the_briefing_actually_prints():
    """If someone renames a briefing line, the agents' instructions must change with it."""
    for phrase in ("Today", "Tomorrow", "Next 7 days", "Still to set up", "Route", "NOT BUILT", "BUILT", "NOT on it"):
        assert phrase in sg.PLAYBOOK
    source = Path(sg.__file__).read_text(encoding="utf-8")
    for printed in ('"Next 7 days:"', "Route: NOT BUILT yet", "NOT on it", "Still to set up on the website:"):
        assert printed in source


def test_mock_bookings_are_obviously_fake_valid_and_spread_over_the_week():
    plan = sg.mock_bookings(date(2026, 10, 17), per_day=5)               # a Saturday
    assert len(plan) == 30 and len({b["scheduled_date"] for b in plan}) == 6
    assert all(date.fromisoformat(b["scheduled_date"]).weekday() != 6 for b in plan)           # never Sunday
    assert all(b["name"].startswith("MOCK ") for b in plan)
    phones = [b["phone"] for b in plan]
    assert len(set(phones)) == len(phones) and all(re.fullmatch(r"\(281\) 555-01\d\d", p) for p in phones)
    assert {b["address"] for b in plan} <= set(sg.MOCK_ADDRESSES)
    assert {b["package"] for b in plan} <= {"standard", "supporter", "hero"}
    assert {a for b in plan for a in b["add_ons"]} <= {"gutters", "bin_cleaning"}
    assert all(b["payment_method"] in ("cash", "card") for b in plan)
    for b in plan:
        JobRequest(**b)                                                  # the real booking form accepts every one
    assert plan == sg.mock_bookings(date(2026, 10, 17), per_day=5)       # same week every time


def test_seeding_asks_first_and_creates_nothing_if_you_say_no():
    posts = []
    http = lambda method, url, body=None, **k: ({"earliest_date": "2026-10-17"} if method == "GET" else posts.append(body))
    out = []
    assert sg.seed_mock_week(out=out.append, confirm=lambda: False, http=http, sleep=lambda s: None) == 0
    assert posts == [] and "FAKE bookings on the LIVE site" in out[0] and "nothing was created" in out[-1].lower()


def test_seeding_creates_the_week_skips_what_the_site_refuses_and_prints_the_cleanup():
    posts, out = [], []

    def http(method, url, body=None, **k):
        if method == "GET":
            return {"earliest_date": "2026-10-17"}
        if body["phone"].endswith("0103"):
            raise sg.SiteError("That day is full.", status=422)
        posts.append(body)

    assert sg.seed_mock_week(per_day=4, out=out.append, confirm=lambda: True, http=http, sleep=lambda s: None) == 0
    text = "\n".join(out)
    assert len(posts) == 23 and "skipped" in text and "That day is full." in text and "23 fake bookings created, 1 skipped" in text
    assert "delete from customers where name like 'MOCK %'" in text
    assert sg.seed_mock_week(per_day=99, out=lambda *_: None, confirm=lambda: False, http=http, sleep=lambda s: None) == 0


def test_a_dead_site_is_reported_not_crashed_on():
    def down(*a, **k):
        raise sg.SiteError("Couldn't reach the site.")
    out = []
    assert sg.seed_mock_week(out=out.append, http=down) == 1 and "Couldn't reach" in out[0]


def test_new_caney_mock_week_is_its_own_valid_fake_week():
    plan = sg.mock_bookings(date(2026, 10, 26), per_day=5, area="new-caney")           # a Monday
    assert len(plan) == 30 and len({b["scheduled_date"] for b in plan}) == 6
    assert all(b["name"].startswith("MOCK ") for b in plan)
    assert {b["address"] for b in plan} <= set(sg.NEW_CANEY_ADDRESSES)
    assert all(("Splendora" in a or "New Caney" in a) for a in sg.NEW_CANEY_ADDRESSES)
    other = sg.mock_bookings(date(2026, 10, 19), per_day=5)
    phones = [b["phone"] for b in plan]
    assert len(set(phones)) == len(phones) and not set(phones) & {b["phone"] for b in other}   # no clash with the first mock week
    assert all(re.fullmatch(r"\(281\) 555-01\d\d", p) for p in phones)
    for b in plan:
        JobRequest(**b)
    assert plan == sg.mock_bookings(date(2026, 10, 26), per_day=5, area="new-caney")


def test_new_caney_seeding_starts_on_a_monday_after_the_first_week():
    posts = []
    http = lambda method, url, body=None, **k: ({"earliest_date": "2026-10-18"} if method == "GET" else posts.append(body))
    out = []
    assert sg.seed_mock_week(out=out.append, confirm=lambda: True, http=http, sleep=lambda s: None, area="new-caney") == 0
    days = sorted({p["scheduled_date"] for p in posts})
    assert days[0] == "2026-10-26" and date.fromisoformat(days[0]).weekday() == 0 and len(posts) == 30
    assert "New Caney / Splendora area" in out[0]
