"""The StarNet client file: talks to the gateway, refuses unapproved actions, drives a tool-calling model."""

import http.server
import json
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "starnet"))
import semper_green_site as sg  # noqa: E402

from .test_api_flow import CREW, NOW, TOMORROW, book  # noqa: E402


@pytest.fixture
def site(client, repo, settings, monkeypatch):
    settings.agent_key_read, settings.agent_key_ops = "read-key-123", "ops-key-456"

    def make(key):
        s = sg.SemperGreenSite(base_url="http://localhost:8000", key=key)

        def call(method, path):          # route the client's HTTP calls through the test app
            r = client.request(method, path, headers={"X-Agent-Key": key})
            if r.status_code >= 400:
                raise sg.SiteError(f"The site said {r.status_code}: {r.json().get('detail', '')}")
            return r.json()
        monkeypatch.setattr(s, "_call", call)
        return s
    return make


def day_with_bookings(client, repo, settings):
    from app.nightly import run_nightly
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
    run_nightly(repo, settings, TOMORROW)


def test_the_client_needs_a_safe_address_and_a_key():
    with pytest.raises(sg.SiteError):
        sg.SemperGreenSite(base_url="http://example.com", key="k")          # no plain http to the internet
    with pytest.raises(sg.SiteError):
        sg.SemperGreenSite(base_url="https://example.com", key="")


def test_look_tools_work_and_dates_are_checked(site, client, repo, settings):
    day_with_bookings(client, repo, settings)
    s = site("read-key-123")
    assert s.health()["business"] == "Semper Green Lawn Care"
    assert json.loads(sg.run_tool(s, "day_summary", {"day": TOMORROW.isoformat()}))["totals"]["bookings"] == 1
    assert "days" in json.loads(sg.run_tool(s, "week_outlook", {"days": 3}))
    assert "Dates look like" in json.loads(sg.run_tool(s, "day_summary", {"day": "tomorrow"}))["error"]
    assert "Dates look like" in json.loads(sg.run_tool(s, "day_summary", {"day": "2026-13-45"}))["error"]
    assert "Unknown tool" in json.loads(sg.run_tool(s, "delete_everything", {}))["error"]


def test_actions_need_approval_and_the_right_key(site, client, repo, settings):
    with patch("app.main.local_now", return_value=NOW), patch("app.agent_api.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
        ops, read = site("ops-key-456"), site("read-key-123")
        day = {"day": TOMORROW.isoformat()}
        assert "refused" in json.loads(sg.run_tool(ops, "build_route", day))              # nobody approved: refused
        assert "refused" in json.loads(sg.run_tool(ops, "build_route", day, approve=lambda t, a: False))
        assert "ops key" in json.loads(sg.run_tool(read, "build_route", day, approve=lambda t, a: True))["error"]
        assert json.loads(sg.run_tool(ops, "build_route", day, approve=lambda t, a: True))["built"] is True


class FakeOllama(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOllama.seen.append(body)
        tool_results = [m for m in body["messages"] if m["role"] == "tool"]
        if not tool_results:
            msg = {"role": "assistant", "content": "", "tool_calls": [
                {"type": "function", "function": {"name": "site_health", "arguments": {}}}]}
        else:
            msg = {"role": "assistant", "content": "Site is healthy: " + tool_results[-1]["content"][:20]}
        out = json.dumps({"message": msg}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_ask_runs_the_tool_loop_against_ollama(site):
    FakeOllama.seen = []
    srv = http.server.HTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        answer = sg.ask(site("read-key-123"), "Is the site up?", ollama_url=f"http://127.0.0.1:{srv.server_port}")
    finally:
        srv.shutdown()
    assert answer.startswith("Site is healthy")
    first, second = FakeOllama.seen
    assert [t["function"]["name"] for t in first["tools"]] == [t["function"]["name"] for t in sg.TOOLS]
    assert first["messages"][0]["role"] == "system" and second["messages"][-1]["role"] == "tool"
    assert second["messages"][-1]["tool_name"] == "site_health"


def test_ask_is_kind_when_ollama_is_off(site):
    assert "Is Ollama running" in sg.ask(site("read-key-123"), "hi", ollama_url="http://127.0.0.1:9")
