"""The one command: find StarNet's workspace, set everything up, copy one message, keep it fresh."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "starnet"))
import semper_green_site as sg  # noqa: E402

from .test_api_flow import NOW, book  # noqa: E402
from .test_starnet_setup import box  # noqa: E402,F401  (the fake StarNet computer)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(sg, "WORKSPACE_FILE", tmp_path / "remembered_folder")
    return tmp_path


def tree(root: Path):
    ws = root / "Documents" / "StarNet" / "workspace"
    ws.mkdir(parents=True)
    (ws / "meta-ad-desk-plan.md").write_text("plan")
    (root / "Documents" / "Taxes").mkdir()
    (root / "Documents" / "Taxes" / "notes.md").write_text("x")
    (root / "node_modules" / "StarNet-clone").mkdir(parents=True)
    (root / "node_modules" / "StarNet-clone" / "meta-ad-desk-plan.md").write_text("junk")
    return ws


def test_it_finds_the_folder_holding_files_the_starnet_agents_saved(tmp_path):
    ws = tree(tmp_path)
    found = sg.find_starnet_workspaces(roots=[str(tmp_path)], seconds=5)
    assert found[0] == (str(ws), "has files the StarNet agents saved")
    assert not any("node_modules" in folder for folder, _ in found)            # junk folders are skipped
    assert any(why == "named like StarNet" for _, why in found)                # the StarNet parent folder is offered too
    assert sg.find_starnet_workspaces(roots=[str(tmp_path / "Documents" / "Taxes")], seconds=5) == []


def test_the_search_gives_up_on_time_and_depth(tmp_path):
    deep = tmp_path
    for i in range(10):
        deep = deep / f"level{i}"
    deep.mkdir(parents=True)
    (deep / "meta-ad-desk-plan.md").write_text("x")
    assert sg.find_starnet_workspaces(roots=[str(tmp_path)], seconds=5, max_depth=4) == []
    assert sg.find_starnet_workspaces(roots=[str(tmp_path)], seconds=0) == []


def test_choosing_the_folder_confirm_pick_or_paste(tmp_path):
    real = tmp_path / "ws"; real.mkdir()
    one = [(str(real), "has files the StarNet agents saved")]
    out = []
    assert sg.choose_workspace(one, ask=lambda q: "", out=out.append) == str(real) and "Found StarNet's workspace" in out[0]
    replies = iter(["n", f'"{real}"'])
    assert sg.choose_workspace(one, ask=lambda q: next(replies), out=out.append) == str(real)               # said no, pasted it
    many = [(str(tmp_path / "a"), "x"), (str(real), "y")]
    assert sg.choose_workspace(many, ask=lambda q: "2", out=out.append) == str(real)
    typed = iter([str(real)])
    assert sg.choose_workspace([], ask=lambda q: next(typed), out=out.append) == str(real)
    assert "couldn't find" in " ".join(out)
    both = [(str(real), "has files the StarNet agents saved"), (str(tmp_path / "StarNet"), "named like StarNet")]
    out.clear()
    assert sg.choose_workspace(both, ask=lambda q: "", out=out.append) == str(real)          # only the strong guess is offered
    assert "Found StarNet's workspace" in out[0] and "a few places" not in " ".join(out)
    answers = iter(["nope", "still nope", "no again"])
    assert sg.choose_workspace([], ask=lambda q: next(answers), out=out.append) is None and out.count("That folder doesn't exist. Try again.") == 3


def test_the_chosen_folder_is_remembered(home, tmp_path):
    assert sg.saved_folder() is None
    ws = tmp_path / "ws"; ws.mkdir()
    sg.save_folder(str(ws))
    assert sg.saved_folder() == str(ws)
    ws.rmdir()
    assert sg.saved_folder() is None                                           # a folder that no longer exists is forgotten


@pytest.fixture
def connected(box, client, settings):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
    settings.agent_key_read = "k" * 40
    sg.KEY_FILE.write_text("k" * 40)
    return sg.SemperGreenSite()


def test_go_sets_everything_up_copies_one_message_and_keeps_watching(home, box, connected, tmp_path):
    ws = tree(tmp_path / "pc")
    out, slept = [], []
    code = sg.go(connected, out=out.append, ask=lambda q: "y", find=lambda: sg.find_starnet_workspaces([str(tmp_path / "pc")], 5),
                 rounds=2, sleep=slept.append, minutes=5)
    assert code == 0
    assert (ws / "semper_green_site.py").exists() and (ws / "semper_green_playbook.md").exists()
    assert len(list((ws / "agents").glob("*.md"))) == 8 and (ws / "starnet_routines.md").exists()
    assert sg.saved_folder() == str(ws)
    setup_message = sg.starnet_messages(str(ws))[0]
    assert box.clip[-1] == setup_message                                       # one paste is all it takes
    text = "\n".join(out)
    assert "I copied the message for The Beyonder to your clipboard" in text and "Leave this window open" in text
    assert sum("refreshed 8 agent files" in l for l in out) == 2 and slept == [300]


def test_the_second_time_it_remembers_the_folder_and_asks_nothing(home, box, connected, tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    sg.save_folder(str(ws))
    out = []
    code = sg.go(connected, out=out.append, ask=lambda q: pytest.fail("should not ask"),
                 find=lambda: pytest.fail("should not search"), rounds=1, sleep=lambda s: None)
    assert code == 0 and out[0] == f"Using StarNet's workspace: {ws}" and len(list((ws / "agents").glob("*.md"))) == 8


def test_go_says_what_to_do_first_if_starnet_is_not_connected_yet(home, box):
    site = sg.SemperGreenSite(base_url="http://localhost:8000", key="wrong-key-wrong-key-wrong-key-1234")
    out = []
    assert sg.go(site, out=out.append, ask=lambda q: "", find=lambda: []) == 1
    assert "--setup" in out[0] and not Path(sg.WORKSPACE_FILE).exists()


def test_go_stops_politely_if_no_folder_is_given(home, box, connected):
    out = []
    assert sg.go(connected, out=out.append, ask=lambda q: "", find=lambda: []) == 1
    assert "No folder, so I stopped" in out[-1] and sg.saved_folder() is None


def test_delivering_a_message_shows_it_even_without_a_clipboard(box, monkeypatch):
    out = []
    monkeypatch.setattr(sg, "copy_to_clipboard", lambda t: False)
    sg.deliver("hello beyonder", out.append)
    assert out == ["\nhello beyonder\n"]
    monkeypatch.setattr(sg, "copy_to_clipboard", lambda t: True)
    out.clear()
    sg.deliver("hello beyonder", out.append, "practice day 1")
    assert "copied practice day 1 to your clipboard" in out[0] and "hello beyonder" in out[1]


def test_running_a_command_before_connecting_is_one_plain_sentence_not_a_traceback(tmp_path):
    import subprocess
    env = {"PATH": "", "HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "SEMPER_SITE_URL": "http://localhost:1"}
    for flag in ("--go", "--brief", "--sync"):
        r = subprocess.run([sys.executable, str(Path(sg.__file__)), flag], capture_output=True, text=True, env=env)
        assert r.returncode == 1 and "Traceback" not in r.stderr, (flag, r.stderr)
        assert "No key yet" in r.stdout and "--setup" in r.stdout
