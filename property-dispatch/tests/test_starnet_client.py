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

    def make(key, ops=False):
        s = sg.SemperGreenSite(base_url="http://localhost:8000", key=key, ops=ops)

        def call(method, path):          # route the client's HTTP calls through the test app
            r = client.request(method, path, headers={"X-Agent-Key": key})
            if r.status_code >= 400:
                raise sg.SiteError(f"The site said {r.status_code}: {r.json().get('detail', '')}", status=r.status_code)
            return r.json()
        monkeypatch.setattr(s, "_call", call)
        return s
    monkeypatch.setattr(sg, "read_ops_key", lambda: "")        # this computer has no ops key unless a test makes one
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


def test_route_building_needs_the_ops_key_and_no_longer_asks_for_approval(site, client, repo, settings):
    with patch("app.main.local_now", return_value=NOW), patch("app.agent_api.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
        ops, read = site("ops-key-456", ops=True), site("read-key-123")
        day = {"day": TOMORROW.isoformat()}
        assert "No ops key yet" in json.loads(sg.run_tool(read, "build_route", day))["error"]     # a read-only computer can't
        assert sg.NEEDS_APPROVAL == set()                                                          # the owner delegated it
        assert json.loads(sg.run_tool(ops, "build_route", day))["built"] is True
        assert json.loads(sg.run_tool(ops, "build_route", {"day": "tomorrow"}))["error"].startswith("Dates look like")


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


class NoToolsOllama(http.server.BaseHTTPRequestHandler):
    """Like many small GGUF coder models: refuses the tools list, answers fine without it."""
    seen: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        NoToolsOllama.seen.append(body)
        if "tools" in body:
            out, code = json.dumps({"error": "registry.ollama.ai/library/some-model does not support tools"}).encode(), 400
        else:
            out, code = json.dumps({"message": {"role": "assistant", "content": "All good. Two bookings tomorrow."}}).encode(), 200
        self.send_response(code); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_a_model_without_tool_support_gets_the_briefing_instead(site, client, repo, settings):
    day_with_bookings(client, repo, settings)
    NoToolsOllama.seen = []
    srv = http.server.HTTPServer(("127.0.0.1", 0), NoToolsOllama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with patch("app.agent_api.local_now", return_value=NOW):
            answer = sg.ask(site("read-key-123"), "How does tomorrow look?", model="hf.co/some/Small-Coder:Q4_K_M",
                            ollama_url=f"http://127.0.0.1:{srv.server_port}")
    finally:
        srv.shutdown()
    assert answer == "All good. Two bookings tomorrow."
    with_tools, without = NoToolsOllama.seen
    assert "tools" in with_tools and "tools" not in without
    assert without["model"] == "hf.co/some/Small-Coder:Q4_K_M"
    prompt = without["messages"][-1]["content"]
    assert "SEMPER GREEN LAWN CARE BRIEFING" in prompt and "How does tomorrow look?" in prompt
    assert "Customer A" not in prompt and "555" not in prompt                     # still no personal details


def test_model_errors_are_explained_not_blamed_on_ollama_being_off(site):
    class Broken(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            out = json.dumps({"error": "model 'nope' not found"}).encode()
            self.send_response(404); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), Broken)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        answer = sg.ask(site("read-key-123"), "hi", model="nope", ollama_url=f"http://127.0.0.1:{srv.server_port}")
    finally:
        srv.shutdown()
    assert "Ollama said 404" in answer and "not found" in answer and "Is Ollama running" not in answer
