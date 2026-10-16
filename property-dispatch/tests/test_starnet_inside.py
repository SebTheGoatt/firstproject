"""Doing it inside StarNet: the week total, practice-day orders, and the messages the Beyonder is given."""

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "starnet"))
import semper_green_site as sg  # noqa: E402

from .test_api_flow import NOW, book  # noqa: E402
from .test_starnet_setup import box  # noqa: E402,F401  (the fake StarNet computer)

FOLDER = r"C:\Users\Raymu"


def test_the_briefing_gives_the_week_total_so_agents_copy_it(box, client, settings):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
        assert book(client, "B", "0101").status_code == 201
    settings.agent_key_read = "k" * 40
    sg.KEY_FILE.write_text("k" * 40)
    with patch("app.agent_api.local_now", return_value=NOW):
        text = sg.briefing(sg.SemperGreenSite(), None)
        practice = sg.briefing(sg.SemperGreenSite(), None, as_of=date(2026, 10, 14), clock="7:00 AM")
    assert "  Week total: 2 bookings, $173.20 expected" in text and "  Week total: 2 bookings, $173.20 expected" in practice
    assert text.index("Next 7 days:") < text.index("Week total:") < text.index("Same page as StarNet")
    # ...and an agent that copies it is not accused of inventing a number
    assert sg.check_output("Recon Radar", "BUSY DAYS: none\nQUIET DAYS: none\nEXPECTED THIS WEEK: $173.20", text) == (True, [])


def test_the_playbook_tells_recon_radar_to_copy_not_add():
    section = sg.playbook_sections()["Recon Radar"]
    assert 'copy the dollar amount from the "Week total" line' in section and "Never add numbers yourself" in section


def test_mock_day_orders_list_every_job_in_clock_order_with_a_practice_briefing_command():
    text = sg.mock_day_orders(1, date(2026, 10, 17), FOLDER)
    assert text.startswith("MOCK DAY 1: Sat Oct 17 (practice). In the folder C:\\Users\\Raymu.")
    order = [line.split("  ", 1)[1] for line in text.splitlines() if line[:1].isdigit() and "  " in line]
    assert order == ["The Overseer", "Recon Radar", "Marketer", "The Dispatcher", "The Overseer", "The Beyonder"]
    assert '--brief --as-of 2026-10-17 --clock "6:30 AM"' in text and '--clock "5:15 PM"' in text
    assert "Use Recon Radar's QUIET DAYS" in text and "Reply to the owner with your report and nothing else" in text
    assert "Nothing is sent to customers and nothing on the website changes" in text
    monday = sg.mock_day_orders(3, date(2026, 10, 17), FOLDER)                # day 3 = Monday Oct 19
    assert "Engineer" in monday and "--sync" in monday and "The Sales Deck" in monday
    assert "The Comms Officer" in sg.mock_day_orders(2, date(2026, 10, 17), FOLDER) and "write a short text" in sg.mock_day_orders(2, date(2026, 10, 17), FOLDER)


def test_the_messages_for_the_beyonder_are_safe_short_and_name_the_folder(tmp_path):
    setup, practice = sg.starnet_messages(FOLDER)
    for m in (setup, practice):
        assert FOLDER in m and "semper_green_site.py" in m and len(m) < 1600
        assert "Do not change the website" in m or "do not change the website" in m
        assert "deploy" in m.lower() and "customer" in m.lower() or "Create nothing else" in m
    assert "Overseer 6:30 AM and 5:30 PM" in setup and "Dispatcher 5:15 PM" in setup and "Engineer on Mondays" in setup
    assert "--brief" in setup and "NEEDS OWNER" in setup and "--mock-day 1" in practice
    path = sg.write_starnet_files(FOLDER, str(tmp_path / "routines.md"))
    saved = Path(path).read_text(encoding="utf-8")
    assert setup in saved and practice in saved and "Paste these to The Beyonder" in saved


def test_every_schedule_line_in_the_setup_message_matches_the_jobs_the_runner_uses():
    setup, _ = sg.starnet_messages(FOLDER)
    times = {}
    for j in sg.day_jobs(0, date(2026, 10, 17)):
        times.setdefault(j[3], []).append(j[2])
    assert times["The Overseer"] == ["6:30 AM", "5:30 PM"] and "Overseer 6:30 AM and 5:30 PM" in setup
    assert times["Recon Radar"] == ["7:00 AM"] and "Recon Radar 7:00 AM" in setup
    assert times["The Dispatcher"] == ["5:15 PM"] and "Dispatcher 5:15 PM" in setup


def test_flags_are_read_from_the_command_line():
    args = ["--brief", "--as-of", "2026-10-17", "--clock", "6:30 AM"]
    assert sg._flag(args, "--as-of") == "2026-10-17" and sg._flag(args, "--clock") == "6:30 AM"
    assert sg._flag(["--brief"], "--as-of") is None and sg._flag(["--brief", "--as-of"], "--as-of") is None
