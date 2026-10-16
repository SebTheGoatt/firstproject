"""The one-command StarNet setup and the plain-English briefing."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "starnet"))
import semper_green_site as sg  # noqa: E402

from .test_api_flow import NOW, TOMORROW, book  # noqa: E402


@pytest.fixture
def box(client, settings, tmp_path, monkeypatch):
    """A StarNet computer: its own key file, files in a temp folder, a clipboard we can read, and the real site app."""
    monkeypatch.setattr(sg, "KEY_FILE", tmp_path / "key")
    monkeypatch.setattr(sg, "BRIEF_FILE", str(tmp_path / "briefing.txt"))
    monkeypatch.setattr(sg, "EXPECTED_FILE", str(tmp_path / "expected.json"))
    monkeypatch.delenv("SEMPER_AGENT_KEY", raising=False)
    clip = []
    monkeypatch.setattr(sg, "copy_to_clipboard", lambda text: clip.append(text) or True)

    def call(self, method, path):
        r = client.request(method, path, headers={"X-Agent-Key": self._key})
        if r.status_code >= 400:
            raise sg.SiteError(f"The site said {r.status_code}: {r.json().get('detail', '')}", status=r.status_code)
        return r.json()
    monkeypatch.setattr(sg.SemperGreenSite, "_call", call)
    out = []
    return type("Box", (), {"clip": clip, "out": out, "say": out.append, "dir": tmp_path})


def test_first_run_makes_a_key_and_copies_one_line_for_render(box):
    assert sg.setup(out=box.say) == 0
    key = sg.read_key_file()
    assert len(key) >= 40 and box.clip == [f"AGENT_KEY_READ={key}"]
    text = "\n".join(box.out)
    assert "Render" in text and "run this same command again" in text
    assert key not in text                          # the secret is never printed when it was copied for you


def test_without_a_clipboard_the_line_is_shown_instead(box, monkeypatch):
    monkeypatch.setattr(sg, "copy_to_clipboard", lambda text: False)
    sg.setup(out=box.say)
    assert f"AGENT_KEY_READ={sg.read_key_file()}" in "\n".join(box.out)


def test_running_again_before_render_has_the_key_says_so_plainly(box, settings):
    sg.setup(out=box.say)
    box.out.clear()
    assert sg.setup(out=box.say) == 1                                  # the site has no agent keys at all yet (503)
    assert "doesn't have the key yet" in box.out[0] and "Save, rebuild, and deploy" in box.out[0]


def test_a_wrong_key_recopies_the_right_line(box, settings):
    sg.setup(out=box.say)
    settings.agent_key_read = "some-other-key-in-render"
    box.out.clear(); box.clip.clear()
    assert sg.setup(out=box.say) == 1
    assert "doesn't match" in box.out[0] and box.clip == [f"AGENT_KEY_READ={sg.read_key_file()}"]


def test_an_old_site_says_to_deploy(box, monkeypatch):
    sg.setup(out=box.say)
    box.out.clear()

    def old_site(self, method, path):
        raise sg.SiteError("The site said 404: Not Found", status=404)
    monkeypatch.setattr(sg.SemperGreenSite, "_call", old_site)
    assert sg.setup(out=box.say) == 1 and "Manual Deploy" in box.out[0]


def test_once_connected_it_saves_settings_and_writes_the_briefing(box, client, settings):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
    sg.setup(out=box.say)
    settings.agent_key_read = sg.read_key_file()                       # what the owner pasted into Render
    box.out.clear()
    assert sg.setup(out=box.say) == 0
    text = "\n".join(box.out)
    assert "All set" in text and "SEMPER GREEN LAWN CARE BRIEFING" in text
    assert Path(sg.EXPECTED_FILE).exists()                              # StarNet now knows the site's settings
    briefing = Path(sg.BRIEF_FILE).read_text(encoding="utf-8")
    assert "Next 7 days:" in briefing and "Same page as StarNet: yes." in briefing
    assert "Still to set up on the website:" in briefing and "CHARITY_VFW_NAME" in briefing


def test_the_briefing_is_plain_english_and_private(box, client, settings):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
    settings.agent_key_read = "k" * 40
    sg.KEY_FILE.write_text("k" * 40)
    with patch("app.agent_api.local_now", return_value=NOW):
        text = sg.briefing(sg.SemperGreenSite(), None)
    assert "Next 7 days" in text and "$86.60" in text and "Rules for agents" in text
    for private in ("Customer A", "555", "100 A Example", "access", "k" * 10):
        assert private not in text
    assert "No saved expectations" not in text            # the briefing only lists problems and differences


def test_the_site_object_finds_the_saved_key_by_itself(box):
    sg.KEY_FILE.write_text("saved-key-123456789012345678901234567890\n")
    assert sg.SemperGreenSite()._key == "saved-key-123456789012345678901234567890"


# ---------- --connect: the Render side from the command line ----------

SITE = sg.DEFAULT_SITE


class FakeRender:
    """Stands in for Render's API. Setting the env var is what turns the key on at the site, like the real thing."""

    def __init__(self, settings, services=None, statuses=("build_in_progress", "update_in_progress", "live")):
        self.settings, self.calls, self.statuses = settings, [], list(statuses)
        self.services = services if services is not None else [
            {"cursor": "c1", "service": {"id": "srv-123", "name": "property-dispatch", "serviceDetails": {"url": SITE}}},
            {"cursor": "c2", "service": {"id": "srv-999", "name": "other-app", "serviceDetails": {"url": "https://other.onrender.com"}}}]

    def __call__(self, method, path, key, body=None, timeout=40.0):
        self.calls.append((method, path.split("?")[0], body))
        assert key == "rnd_secret_api_key"
        if method == "GET" and path.startswith("/services?"):
            return self.services
        if method == "PUT" and path.endswith("/env-vars/AGENT_KEY_READ"):
            self.settings.agent_key_read = body["value"]
            return {"key": "AGENT_KEY_READ"}
        if method == "POST" and path.endswith("/deploys"):
            return {"id": "dep-1", "status": "created"}
        if method == "GET" and "/deploys/dep-1" in path:
            return {"status": self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]}
        raise AssertionError(f"unexpected Render call {method} {path}")


@pytest.fixture
def rkey(monkeypatch):
    monkeypatch.setenv("RENDER_API_KEY", "rnd_secret_api_key")


def test_connect_needs_a_render_key_and_says_how_to_get_one(box, monkeypatch):
    monkeypatch.delenv("RENDER_API_KEY", raising=False)
    assert sg.connect(out=box.say, render=lambda *a, **k: 1 / 0) == 1
    assert "API Key" in box.out[0] and "$env:RENDER_API_KEY" in box.out[0]


def test_connect_does_everything_from_one_command(box, settings, rkey):
    fake = FakeRender(settings)
    assert sg.connect(out=box.say, render=fake, sleep=lambda s: None, poll_s=0) == 0
    steps = [(m, p) for m, p, _ in fake.calls]
    assert steps[0] == ("GET", "/services")
    assert ("PUT", "/services/srv-123/env-vars/AGENT_KEY_READ") in steps       # found the right service by its address
    assert ("POST", "/services/srv-123/deploys") in steps
    assert steps.index(("PUT", "/services/srv-123/env-vars/AGENT_KEY_READ")) < steps.index(("POST", "/services/srv-123/deploys"))
    assert settings.agent_key_read == sg.read_key_file()                       # the key StarNet holds is the key Render got
    text = "\n".join(box.out)
    assert "Found the website on Render (property-dispatch)" in text and "All set" in text
    assert Path(sg.EXPECTED_FILE).exists() and Path(sg.BRIEF_FILE).exists()
    assert "rnd_secret_api_key" not in text and sg.read_key_file() not in text  # neither secret is ever printed


def test_connect_is_safe_to_run_twice_and_keeps_the_same_key(box, settings, rkey):
    sg.connect(out=box.say, render=FakeRender(settings), sleep=lambda s: None, poll_s=0)
    first = sg.read_key_file()
    sg.connect(out=box.say, render=FakeRender(settings), sleep=lambda s: None, poll_s=0)
    assert sg.read_key_file() == first and settings.agent_key_read == first


def test_connect_explains_a_bad_render_key(box, settings, rkey):
    def refuse(*a, **k):
        raise sg.RenderError("Render didn't accept that API key. Make a new one at Account Settings, API Keys.")
    assert sg.connect(out=box.say, render=refuse) == 1 and "didn't accept that API key" in box.out[-1]


def test_connect_names_the_services_when_it_cannot_tell_which_is_the_site(box, settings, rkey):
    fake = FakeRender(settings, services=[{"service": {"id": "srv-9", "name": "someone-elses-app", "serviceDetails": {"url": "https://x.onrender.com"}}}])
    assert sg.connect(out=box.say, render=fake) == 1
    assert "someone-elses-app" in box.out[-1] and "RENDER_SERVICE_ID" in box.out[-1]
    assert not any(m == "PUT" for m, _, _ in fake.calls)                         # it never touches a service it isn't sure about


def test_connect_reports_a_failed_deploy_and_stops(box, settings, rkey):
    fake = FakeRender(settings, statuses=("build_in_progress", "build_failed"))
    assert sg.connect(out=box.say, render=fake, sleep=lambda s: None, poll_s=0) == 1
    assert "build_failed" in box.out[-1] and "All set" not in "\n".join(box.out)


def test_connect_gives_up_waiting_politely(box, settings, rkey):
    fake = FakeRender(settings, statuses=("build_in_progress",))
    assert sg.connect(out=box.say, render=fake, sleep=lambda s: None, wait_s=30, poll_s=10) == 1
    assert "--setup" in box.out[-1]
