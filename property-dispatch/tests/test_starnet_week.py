"""The mock-week runner: every agent does its job each day on the local model, and gets scored."""

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "starnet"))
import semper_green_site as sg  # noqa: E402

from .test_api_flow import NOW, TOMORROW, book  # noqa: E402
from .test_starnet_setup import box  # noqa: E402,F401  (the fake StarNet computer)

GOOD = {
    "The Overseer": "TODAY: 0 bookings\nTOMORROW: 2 bookings, route NOT BUILT\nPROBLEMS: none\nNEEDS OWNER: nothing",
    "Recon Radar": "BUSY DAYS: none\nQUIET DAYS: Sun Oct 18\nEXPECTED THIS WEEK: see briefing",
    "The Dispatcher": "NEEDS OWNER: build tomorrow's route (2 bookings).",
    "The Beyonder": "WEEK SO FAR: fine\nGOING WELL: bookings\nWATCH: routes\nNEEDS OWNER: nothing",
}


def agent_of(body):
    system = body["messages"][0]["content"]
    for name in ("The Overseer", "Recon Radar", "The Dispatcher", "The Beyonder", "Marketer", "The Sales Deck",
                 "The Comms Officer", "Engineer"):
        if f"## {name}:" in system:
            return name


@pytest.fixture
def week(box, client, settings):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
        assert book(client, "B", "0101").status_code == 201
    settings.agent_key_read = "k" * 40
    sg.KEY_FILE.write_text("k" * 40)
    site = sg.SemperGreenSite()
    return type("W", (), {"site": site, "dir": box.dir, "out": []})


def fake_chat(calls, answers=GOOD, default="Done."):
    def chat(url, body):
        calls.append(body)
        return {"role": "assistant", "content": answers.get(agent_of(body), default)}
    return chat


def test_who_works_when():
    sat = sg.day_jobs(0, date(2026, 10, 17))
    assert [(j[2], j[3]) for j in sat] == [("6:30 AM", "The Overseer"), ("7:00 AM", "Recon Radar"), ("9:00 AM", "Marketer"),
                                          ("5:15 PM", "The Dispatcher"), ("5:30 PM", "The Overseer"), ("6:00 PM", "The Beyonder")]
    assert any(j[3] == "Engineer" for j in sg.day_jobs(2, date(2026, 10, 19)))          # a Monday
    assert not any(j[3] == "Engineer" for j in sg.day_jobs(3, date(2026, 10, 20)))
    assert any(j[3] == "The Sales Deck" for j in sg.day_jobs(2, date(2026, 10, 19)))
    assert sum(j[3] == "The Comms Officer" for d in range(7) for j in sg.day_jobs(d, date(2026, 10, 17 + d))) == 1


def test_a_practice_day_briefing_shows_that_day_as_today(week):
    with patch("app.agent_api.local_now", return_value=NOW):
        text = sg.briefing(week.site, None, as_of=date(2026, 10, 14), clock="5:15 PM")
    assert "(Wed Oct 14, 5:15 PM, practice day)" in text
    assert "Today (Wed Oct 14): 0 booking(s)" in text and "Tomorrow (Thu Oct 15): 2 booking(s)" in text
    assert "Wed Oct 14: 0 bookings of 25 possible" in text and "Thu Oct 15: 2 bookings of 25 possible, $173.20 expected" in text
    assert "Customer A" not in text


def test_the_week_runs_every_job_writes_the_report_and_scores_it(week):
    calls, out = [], []
    path = str(week.dir / "report.md")
    assert sg.run_week(week.site, days=7, start=date(2026, 10, 17), model="small-model", chat=fake_chat(calls),
                       out=out.append, report_path=path, expected={}) == 0
    assert len(calls) == 37                                   # 28 daily + 6 (Marketer+Beyonder x3) + Sales Deck + Comms + Engineer
    assert all(c["model"] == "small-model" and c["stream"] is False and "tools" not in c for c in calls)
    report = Path(path).read_text(encoding="utf-8")
    assert "## Day 1: Sat Oct 17" in report and "## Day 7: Fri Oct 23" in report and "## Scorecard" in report
    assert "### 5:15 PM  The Dispatcher ✓ format" in report
    assert "| The Overseer | 14 | 14/14 | 0 | 0 |" in report and "| The Beyonder | 3 | 3/3 | 0 | 0 |" in report
    system = calls[0]["messages"][0]["content"]
    assert "Rules for EVERY agent" in system and "## The Overseer:" in system and "## Marketer:" not in system
    assert "practice day" in calls[0]["messages"][1]["content"]
    assert any("Scorecard" in line for line in out) and out[-1].strip().startswith("Done.")


def test_agents_get_what_they_need_and_nothing_private(week):
    calls = []
    sg.run_week(week.site, days=4, start=date(2026, 10, 17), model="m", chat=fake_chat(calls), out=lambda *_: None,
                report_path=str(week.dir / "r.md"), expected={})
    by_agent = {}
    for c in calls:
        by_agent.setdefault(agent_of(c), []).append(c["messages"][1]["content"])
    assert "Recon Radar said:" in by_agent["Marketer"][0] or "Recon Radar said:" in by_agent["Marketer"][-1]
    assert all("Result of --sync:" in u for u in by_agent["Engineer"])
    beyonder = by_agent["The Beyonder"][-1]
    assert "The Overseer said:" in beyonder and "The Dispatcher said:" in beyonder and "Marketer said:" in beyonder
    assert "write a short text" in by_agent["The Comms Officer"][0]
    everything = " ".join(c["messages"][0]["content"] + c["messages"][1]["content"] for c in calls)
    for private in ("Customer A", "Customer B", "555", "100 A Example", "k" * 20):
        assert private not in everything


def test_the_scorecard_catches_wrong_formats_and_invented_numbers(week):
    bad = dict(GOOD)
    bad["The Overseer"] = "Everything looks fine today, nothing to report."                          # wrong format
    bad["Recon Radar"] = "BUSY DAYS: none\nQUIET DAYS: none\nEXPECTED THIS WEEK: $9,999.99"           # invented number
    bad["The Dispatcher"] = "I think we should probably build it."                                    # wrong format
    path = str(week.dir / "r.md")
    sg.run_week(week.site, days=1, start=date(2026, 10, 17), model="m", chat=fake_chat([], bad), out=lambda *_: None,
                report_path=path, expected={})
    report = Path(path).read_text(encoding="utf-8")
    assert "The Overseer ✗ FORMAT" in report and "The Dispatcher ✗ FORMAT" in report
    assert "✗ NUMBERS NOT IN BRIEFING: $9,999.99" in report
    assert "| The Overseer | 2 | 0/2 | 0 | 0 |" in report and "| Recon Radar | 1 | 1/1 | 1 | 0 |" in report


def test_numbers_that_are_in_the_briefing_are_fine():
    briefing_text = "Tomorrow: 2 booking(s), $173.20 expected, $0.00 collected."
    ok, invented = sg.check_output("Recon Radar", "BUSY DAYS: none\nQUIET DAYS: none\nEXPECTED THIS WEEK: $173.20", briefing_text)
    assert ok and invented == []
    ok, invented = sg.check_output("Marketer", "Mowing from $35, up to $1,200!", briefing_text + " $35")
    assert ok is None and invented == ["$1,200"]


def test_a_model_that_cannot_be_reached_stops_the_run_politely(week):
    def down(url, body):
        raise sg.ModelProblem("I couldn't reach the local model. Is Ollama running?")
    out = []
    assert sg.run_week(week.site, days=2, start=date(2026, 10, 17), model="m", chat=down, out=out.append,
                       report_path=str(week.dir / "r.md"), expected={}) == 1
    assert "keeps failing" in out[-1] and "Is Ollama running" in out[-1]


def test_picking_the_model(monkeypatch):
    monkeypatch.delenv("SEMPER_MODEL", raising=False)
    assert sg.pick_model("http://x", models=["only-one"]) == ("only-one", "")
    name, message = sg.pick_model("http://x", models=["a", "b"])
    assert name is None and "SEMPER_MODEL" in message and "    a" in message and "    b" in message
    assert sg.pick_model("http://x", models=[])[0] is None
    monkeypatch.setenv("SEMPER_MODEL", "hf.co/me/Chosen:Q4_K_M")
    assert sg.pick_model("http://x", models=["a", "b"]) == ("hf.co/me/Chosen:Q4_K_M", "")


def test_the_playbook_sections_the_runner_depends_on_exist():
    sections = sg.playbook_sections()
    for needed in (*sg.SHARED_SECTIONS, "The Overseer", "Recon Radar", "The Dispatcher", "Marketer", "The Sales Deck",
                   "The Comms Officer", "Engineer", "The Beyonder"):
        assert needed in sections, needed


def test_the_runner_stays_well_under_the_sites_call_limit(week):
    """A fast model must not trip the 120-calls-a-minute limit: the whole week should need about 20 calls."""
    calls = []
    original = week.site._call
    week.site._call = lambda method, path: (calls.append(path), original(method, path))[1]
    sg.run_week(week.site, days=7, start=date(2026, 10, 17), model="m", chat=fake_chat([]), out=lambda *_: None,
                report_path=str(week.dir / "r.md"), expected={})
    assert len(calls) < 30, len(calls)


def test_a_slow_down_answer_is_retried_not_fatal(monkeypatch):
    site = sg.SemperGreenSite(base_url="http://localhost:8000", key="k" * 20)
    answers = [sg.SiteError("Too many calls. Slow down.", status=429), sg.SiteError("Too many calls. Slow down.", status=429), {"ok": True}]

    def once(method, path):
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(site, "_call_once", once)
    slept = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))
    assert site.health() == {"ok": True} and slept == [6, 6]
    monkeypatch.setattr(site, "_call_once", lambda m, p: (_ for _ in ()).throw(sg.SiteError("Unauthorized", status=401)))
    with pytest.raises(sg.SiteError):
        site.health()                                         # real errors are not retried
