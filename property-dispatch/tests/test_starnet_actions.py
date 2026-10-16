"""StarNet acting for the business: the ops key, building routes, the on-the-way message, security, practice safety."""

import sys
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "starnet"))
import semper_green_site as sg  # noqa: E402

from app.nightly import run_nightly  # noqa: E402

from .test_api_flow import CREW, NOW, TOMORROW, book  # noqa: E402
from .test_starnet_client import site  # noqa: E402,F401
from .test_starnet_setup import FakeRender, box, rkey  # noqa: E402,F401
from .test_starnet_go import home  # noqa: E402,F401

MORNING = datetime(2026, 10, 15, 6, 45, tzinfo=ZoneInfo("America/Chicago"))


def route_ready(client, repo, settings):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
        assert book(client, "B", "0101").status_code == 201
    run_nightly(repo, settings, TOMORROW)


def test_the_ops_client_tells_the_next_customer_through_the_site_and_never_sees_the_message(site, client, repo, settings, sms):
    route_ready(client, repo, settings)
    ops = site("ops-key-456", ops=True)
    before = len(sms.sent)
    with patch("app.agent_api.local_now", return_value=MORNING):
        result = ops.notify_on_the_way(TOMORROW.isoformat(), 1)
        out = sg.run_tool(ops, "notify_on_the_way", {"day": TOMORROW.isoformat(), "sequence": 1})
    assert result == {"notified": True, "texted": True, "pushed": 0, "reason": None}
    assert len(sms.sent) == before + 1
    assert "already_notified" in out and "Customer" not in out and "555" not in out
    with patch("app.agent_api.local_now", return_value=MORNING):
        too_early = sg.run_tool(ops, "notify_on_the_way", {"day": TOMORROW.isoformat(), "sequence": 2})
    assert "next stop" in too_early                                              # the site's own rule, passed on plainly
    assert "Dates look like" in sg.run_tool(ops, "notify_on_the_way", {"day": "soon", "sequence": 1})


def test_a_read_only_computer_cannot_notify_or_build(site):
    read = site("read-key-123")
    for name, args in (("notify_on_the_way", {"day": "2026-10-15", "sequence": 1}), ("build_route", {"day": "2026-10-15"})):
        assert "No ops key yet" in sg.run_tool(read, name, args)


def test_the_ops_key_is_found_in_the_right_order(tmp_path, monkeypatch):
    home_file, shared = tmp_path / "home_ops", tmp_path / "workspace"
    shared.mkdir()
    monkeypatch.setattr(sg, "OPS_KEY_FILE", home_file)
    monkeypatch.delenv("SEMPER_AGENT_OPS_KEY", raising=False)
    monkeypatch.setattr(sg, "__file__", str(shared / "semper_green_site.py"))
    assert sg.read_ops_key() == ""
    home_file.write_text("from-home\n")
    assert sg.read_ops_key() == "from-home"
    (shared / sg.OPS_KEY_NAME).write_text("from-the-workspace\n")
    assert sg.read_ops_key() == "from-the-workspace"              # the copy beside the script (the Dispatcher's) wins
    monkeypatch.setenv("SEMPER_AGENT_OPS_KEY", "from-the-environment")
    assert sg.read_ops_key() == "from-the-environment"
    key = sg.new_key(tmp_path / "another")
    assert len(key) >= 40 and (tmp_path / "another").read_text().strip() == key


def test_connect_with_ops_puts_both_keys_in_render_and_prints_neither(box, settings, rkey, tmp_path, monkeypatch):
    monkeypatch.setattr(sg, "OPS_KEY_FILE", tmp_path / "ops")
    puts = []

    class Fake(FakeRender):
        def __call__(self, method, path, key, body=None, timeout=40.0):
            if method == "PUT" and path.endswith("/env-vars/AGENT_KEY_OPS"):
                puts.append(body["value"]); settings.agent_key_ops = body["value"]; return {}
            return super().__call__(method, path, key, body, timeout)

    assert sg.connect(out=box.say, render=Fake(settings), sleep=lambda s: None, poll_s=0, with_ops=True) == 0
    ops_key = (tmp_path / "ops").read_text().strip()
    assert puts == [ops_key] and ops_key != sg.read_key_file() and len(ops_key) >= 40
    text = "\n".join(box.out)
    assert "ops key in Render" in text and ops_key not in text and "rnd_secret_api_key" not in text


def test_the_ops_key_goes_into_the_workspace_only_if_the_owner_says_yes(tmp_path, monkeypatch):
    monkeypatch.setattr(sg, "OPS_KEY_FILE", tmp_path / "ops")
    ws = tmp_path / "ws"; ws.mkdir()
    out = []
    assert sg.share_ops_key(str(ws), ask=lambda q: pytest.fail("no key, so nothing to ask"), out=out.append) is False
    assert "--connect --ops" in out[0]
    (tmp_path / "ops").write_text("the-ops-key\n")
    out.clear()
    assert sg.share_ops_key(str(ws), ask=lambda q: "", out=out.append) is False                # Enter means no
    assert not (ws / sg.OPS_KEY_NAME).exists() and "only look and report" in out[-1]
    assert "cannot see customers or money" in out[0] and "AGENT_ACTIONS_PAUSED=true" in out[0]
    assert sg.share_ops_key(str(ws), ask=lambda q: "y", out=out.append) is True
    assert (ws / sg.OPS_KEY_NAME).read_text().strip() == "the-ops-key"
    assert sg.share_ops_key(str(ws), ask=lambda q: pytest.fail("already shared"), out=out.append) is True


def test_go_pastes_the_full_setup_once_then_only_what_is_new(home, box, site, client, repo, settings, tmp_path):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
    connected = site("read-key-123")
    ws = tmp_path / "ws"; ws.mkdir()
    sg.save_folder(str(ws))                                         # an owner from before: folder known, no routines version
    assert sg.saved_routines_version() == 1
    out = []
    sg.go(connected, out=out.append, ask=lambda q: "n", rounds=1, sleep=lambda s: None)
    update = sg.starnet_update_message(str(ws))
    assert box.clip[-1] == update and "Add exactly one new scheduled routine" in update and "6:45 AM" in update
    assert "Change no other routine" in update and "do not deploy anything" in update
    assert "the-dispatcher.md" in update and "the-overseer" not in update
    assert sg.saved_routines_version() == sg.ROUTINES_VERSION == 2
    out.clear(); box.clip.clear()
    sg.go(connected, out=out.append, ask=lambda q: "n", rounds=1, sleep=lambda s: None)       # nothing new now
    assert box.clip == [] and "up to date: nothing to paste" in "\n".join(out)


def test_a_brand_new_owner_gets_the_full_setup_message_with_the_dispatchers_morning_run(home, box, site, client, settings, tmp_path):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
    ws = tmp_path / "ws"; ws.mkdir()
    sg.go(site("read-key-123"), out=lambda *_: None, ask=lambda q: str(ws), find=lambda: [], rounds=1, sleep=lambda s: None)
    assert "Dispatcher 6:45 AM and 5:15 PM" in box.clip[-1] and sg.saved_routines_version() == 2


def test_the_briefing_has_a_security_watch(box, client, settings, site):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
    s = site("read-key-123")
    for _ in range(3):                                                  # three refused calls land in the agent log
        client.get("/api/agent/health", headers={"X-Agent-Key": "wrong"})
    settings.crew_access_token = "change-me"
    with patch("app.agent_api.local_now", return_value=NOW):
        text = sg.briefing(s, None)
    assert "Security watch:" in text
    assert "Agent log:" in text and "3 refused, 0 rate-limited" in text
    assert "Notification keys: ok.   Stripe: not set up mode.   Agent actions: ACTIVE." in text
    assert "Weak spots: CREW_ACCESS_TOKEN" in text
    settings.agent_actions_paused = True
    settings.crew_access_token = "owner-secret"
    settings.webhook_secret = "hook-secret"
    with patch("app.agent_api.local_now", return_value=NOW):
        text = sg.briefing(s, None)
    assert "Agent actions: PAUSED by the owner." in text and "Weak spots: none." in text
    assert text.index("Still to set up") < text.index("Security watch:") < text.index("Rules for agents")
    assert "owner-secret" not in text and "wrong" not in text


def test_the_dispatchers_file_has_its_dates_and_the_only_commands_it_may_run(box, client, settings, site, tmp_path):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
    s = site("read-key-123")
    with patch("app.agent_api.local_now", return_value=NOW):
        sg.write_agent_files(s, str(tmp_path), expected={})
        file = (tmp_path / "agents" / "the-dispatcher.md").read_text(encoding="utf-8")
        other = (tmp_path / "agents" / "marketer.md").read_text(encoding="utf-8")
    assert "Today's date is 2026-10-14. Tomorrow's date is 2026-10-15." in file
    assert "python semper_green_site.py --build-route 2026-10-14" in file and "--notify 2026-10-14 1" in file
    assert "## The Dispatcher:" in file and "--notify" not in other and "--build-route" not in other


def test_practice_days_can_never_change_anything(box, client, settings, site, tmp_path):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
    s = site("read-key-123")
    files = sg.write_mock_day_files(s, str(tmp_path), 1, date(2026, 10, 14), expected={})
    for label, agent, path in files:
        text = Path(path).read_text(encoding="utf-8")
        assert "PRACTICE day" in text and "WOULD RUN: <the command>" in text and "practice day" in text.split("## The briefing")[1][:200]
    morning_dispatcher = next(p for l, a, p in files if a == "The Dispatcher" and l == "6:45 AM")
    assert "--notify 2026-10-14 1" in Path(morning_dispatcher).read_text(encoding="utf-8")        # it knows what it WOULD run


def test_the_playbook_gives_every_agent_a_security_duty_and_the_dispatcher_its_exact_jobs():
    sections = sg.playbook_sections()
    for agent in ("The Overseer", "Recon Radar", "The Dispatcher", "Marketer", "The Sales Deck", "The Comms Officer", "Engineer"):
        assert "SECURITY" in sections[agent], agent
    assert "SECURITY. Never write a password, key, token or phone number" in sections["Rules for EVERY agent"]
    assert "possible attack" in sections["Rules for EVERY agent"] and "PAUSED" in sections["Rules for EVERY agent"]
    assert "practice day" in sections["Rules for EVERY agent"] and "WOULD RUN" in sections["Rules for EVERY agent"]
    d = sections["The Dispatcher"]
    assert "6:45 AM and 5:15 PM" in d and "--build-route" in d and "--notify" in d and "Only ever notify stop 1" in d
    assert "the owner pays and posts" in sections["Marketer"] and "approve ad spend" in sections["Marketer"]
    assert "SECURITY:" in sections["The Overseer"] and "SECURITY:" in sections["The Beyonder"]


def test_dispatcher_answers_in_the_new_formats_are_accepted_and_chatter_is_not():
    for good in ("BUILT ROUTE 2026-10-15: 8 stops.", "NOTIFIED STOP 1 2026-10-15.", "ROUTE OK: 8 stops 2026-10-15.",
                 "NO JOBS TOMORROW.", "NEEDS OWNER: Too early.", "WOULD RUN: python semper_green_site.py --notify 2026-10-15 1"):
        assert sg.check_output("The Dispatcher", good, "")[0] is True, good
    assert sg.check_output("The Dispatcher", "I will now try to build it, one moment.", "")[0] is False
