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
    assert "  Week total: 2 bookings, $227.32 expected" in text and "  Week total: 2 bookings, $227.32 expected" in practice
    assert text.index("Next 7 days:") < text.index("Week total:") < text.index("Same page as StarNet")
    # ...and an agent that copies it is not accused of inventing a number
    assert sg.check_output("Recon Radar", "BUSY DAYS: none\nQUIET DAYS: none\nEXPECTED THIS WEEK: $227.32", text) == (True, [])


def test_the_playbook_tells_recon_radar_to_copy_not_add():
    section = sg.playbook_sections()["Recon Radar"]
    assert 'copy the dollar amount from the "Week total" line' in section and "Never add numbers yourself" in section


def test_mock_day_orders_list_every_job_in_clock_order_with_a_practice_briefing_command():
    text = sg.mock_day_orders(1, date(2026, 10, 17), FOLDER)
    assert text.startswith("MOCK DAY 1: Sat Oct 17 (practice). In the folder C:\\Users\\Raymu.")
    order = [line.split("  ", 1)[1] for line in text.splitlines() if line[:1].isdigit() and "  " in line]
    assert order == ["The Overseer", "The Dispatcher", "Recon Radar", "Marketer", "The Dispatcher", "The Overseer", "The Beyonder"]
    assert '--brief --as-of 2026-10-17 --clock "6:30 AM"' in text and '--clock "5:15 PM"' in text
    assert "Use Recon Radar's QUIET DAYS" in text and "Reply to the owner with your report and nothing else" in text
    assert "Nothing is sent to customers and nothing on the website changes" in text
    monday = sg.mock_day_orders(3, date(2026, 10, 17), FOLDER)                # day 3 = Monday Oct 19
    assert "Engineer" in monday and "--sync" in monday and "The Sales Deck" in monday
    assert "The Comms Officer" in sg.mock_day_orders(2, date(2026, 10, 17), FOLDER) and "write a short text" in sg.mock_day_orders(2, date(2026, 10, 17), FOLDER)


def test_the_messages_for_the_beyonder_are_safe_short_and_name_the_workspace_files(tmp_path):
    setup, practice = sg.starnet_messages(FOLDER)
    assert FOLDER + "\\agents\\" in setup and len(setup) < 1700 and len(practice) < 900
    for slug in ("the-overseer", "recon-radar", "the-dispatcher", "marketer", "the-sales-deck", "the-comms-officer",
                 "engineer", "the-beyonder"):
        assert slug in setup
    assert "Read the file" in setup and "Do not change the website and do not deploy anything" in setup
    assert "--brief" not in setup                          # agents only read a file; nobody has to run a command
    assert "do not deploy" in practice and "do not contact any customer" in practice and "NEEDS OWNER" in practice
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
    assert times["The Dispatcher"] == ["6:45 AM", "5:15 PM"] and "Dispatcher 6:45 AM and 5:15 PM" in setup


def test_flags_are_read_from_the_command_line():
    args = ["--brief", "--as-of", "2026-10-17", "--clock", "6:30 AM"]
    assert sg._flag(args, "--as-of") == "2026-10-17" and sg._flag(args, "--clock") == "6:30 AM"
    assert sg._flag(["--brief"], "--as-of") is None and sg._flag(["--brief", "--as-of"], "--as-of") is None


# ---------- files inside StarNet's workspace ----------

def make_site(box, client, settings):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
        assert book(client, "B", "0101").status_code == 201
    settings.agent_key_read = "k" * 40
    sg.KEY_FILE.write_text("k" * 40)
    return sg.SemperGreenSite()


def test_each_agent_gets_one_file_with_its_rules_and_a_fresh_briefing(box, client, settings, tmp_path):
    site = make_site(box, client, settings)
    with patch("app.agent_api.local_now", return_value=NOW):
        paths = sg.write_agent_files(site, str(tmp_path), expected={})
    assert sorted(Path(p).name for p in paths) == sorted(f"{sg.slug(a)}.md" for a in sg.AGENT_NAMES) and len(paths) == 8
    overseer = (tmp_path / "agents" / "the-overseer.md").read_text(encoding="utf-8")
    assert "## Rules for EVERY agent" in overseer and "## The Overseer:" in overseer and "## The briefing" in overseer
    assert "SEMPER GREEN LAWN CARE BRIEFING" in overseer and "Week total: 2 bookings" in overseer
    assert "## Marketer:" not in overseer and "## The Dispatcher:" not in overseer           # only its own job
    assert overseer.rstrip().endswith("Reply with the report and nothing else.")
    assert "Result of --sync:" in (tmp_path / "agents" / "engineer.md").read_text(encoding="utf-8")
    assert "Recon Radar's latest report" in (tmp_path / "agents" / "marketer.md").read_text(encoding="utf-8")
    assert "Wait for the owner" in (tmp_path / "agents" / "the-comms-officer.md").read_text(encoding="utf-8")
    everything = " ".join(Path(p).read_text(encoding="utf-8") for p in paths)
    for private in ("Customer A", "Customer B", "555", "100 A Example", "k" * 20):
        assert private not in everything


def test_a_practice_day_writes_a_file_per_job_with_the_briefing_as_of_that_time(box, client, settings, tmp_path):
    site = make_site(box, client, settings)
    files = sg.write_mock_day_files(site, str(tmp_path), 1, date(2026, 10, 14), expected={})
    assert [(label, agent) for label, agent, _ in files] == [
        ("6:30 AM", "The Overseer"), ("6:45 AM", "The Dispatcher"), ("7:00 AM", "Recon Radar"), ("9:00 AM", "Marketer"),
        ("5:15 PM", "The Dispatcher"), ("5:30 PM", "The Overseer"), ("6:00 PM", "The Beyonder")]
    assert [Path(p).name for _, _, p in files] == ["0630-the-overseer.md", "0645-the-dispatcher.md", "0700-recon-radar.md",
                                                   "0900-marketer.md", "1715-the-dispatcher.md", "1730-the-overseer.md",
                                                   "1800-the-beyonder.md"]
    assert all(Path(p).parent.name == "day1" and Path(p).parent.parent.name == "mock" for _, _, p in files)
    evening = Path(files[5][2]).read_text(encoding="utf-8")
    assert "(Wed Oct 14, 5:30 PM, practice day)" in evening and "Tomorrow (Thu Oct 15): 2 booking(s)" in evening
    orders = sg.mock_day_orders(1, date(2026, 10, 14), str(tmp_path), files)
    lines = [l for l in orders.splitlines() if "Read the file" in l]
    assert len(lines) == 7 and lines[0].startswith("6:30 AM  The Overseer: Read the file ") and lines[0].endswith("Reply in the exact format.")
    assert "0630-the-overseer.md" in lines[0] and "Nothing is sent to customers" in orders


def test_watch_keeps_the_files_fresh_and_survives_a_bad_moment(box, client, settings, tmp_path, monkeypatch):
    site = make_site(box, client, settings)
    out, slept = [], []
    assert sg.watch(site, str(tmp_path), minutes=5, out=out.append, sleep=slept.append, rounds=2) == 0
    assert slept == [300] and sum("refreshed 8 agent files" in l for l in out) == 2
    monkeypatch.setattr(sg, "write_agent_files", lambda *a, **k: (_ for _ in ()).throw(sg.SiteError("Couldn't reach the site.")))
    out.clear()
    sg.watch(site, str(tmp_path), minutes=1, out=out.append, sleep=lambda s: None, rounds=1)
    assert "couldn't refresh" in out[0] and "trying again" in out[0]


def test_the_script_and_playbook_are_copied_into_the_workspace(tmp_path):
    placed = sg.install_to_workspace(str(tmp_path / "workspace"))
    assert Path(placed[0]).name == "semper_green_site.py" and "def run_week" in Path(placed[0]).read_text(encoding="utf-8")
    assert "## The Overseer:" in Path(placed[1]).read_text(encoding="utf-8")


def test_paths_use_the_folders_own_slashes():
    assert sg.join_path(r"C:\Users\Raymu\ws", "agents") == r"C:\Users\Raymu\ws\agents"
    assert sg.join_path(r"C:\Users\Raymu\ws\\", "agents", "x.md") == r"C:\Users\Raymu\ws\agents\x.md"
    assert sg.join_path("/home/me/ws/", "agents") == "/home/me/ws/agents"


def test_without_a_folder_the_commands_explain_how_to_find_starnets_workspace():
    import subprocess
    for flag in ("--starnet", "--mock-day", "--watch", "--refresh"):
        r = subprocess.run([sys.executable, str(Path(sg.__file__)), flag], capture_output=True, text=True,
                           env={"PATH": "", "SEMPER_AGENT_KEY": "k" * 40, "SEMPER_SITE_URL": "http://localhost:1", "HOME": "/tmp"})
        assert r.returncode == 1, (flag, r.stderr)
        assert "can't see this one" in r.stdout and "--go" in r.stdout and "--folder" in r.stdout
