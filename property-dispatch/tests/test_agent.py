"""Owner-only dispatch assistant (Ollama): off by default, minimal data out, errors never leak."""

import json
from unittest.mock import patch

import httpx
import pytest

from app.nightly import run_nightly

from .test_api_flow import CREW, NOW, TOMORROW, book


@pytest.fixture
def on(settings):
    settings.ollama_base_url = "https://agent.example.com/v1"
    settings.ollama_model = "qwen2.5:14b"
    return settings


def make_day(client, repo, settings, build=True):
    with patch("app.main.local_now", return_value=NOW):
        assert book(client, "A", "0100").status_code == 201
        assert book(client, "B", "0101", service="mowing").status_code == 201
    if build:
        run_nightly(repo, settings, TOMORROW)


def answer_with(text, seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})
    return httpx.MockTransport(handler)


URL = f"/api/owner/dispatch-assistant/{TOMORROW}"


def test_off_until_configured_and_owner_only(client, settings):
    assert client.post(URL, headers=CREW).status_code == 503
    settings.ollama_base_url = "https://agent.example.com/v1"
    assert client.post(URL).status_code == 401
    assert client.post(URL, headers={"X-Crew-Token": "wrong"}).status_code == 401


def test_sends_only_route_data_and_returns_the_answer(client, repo, settings, on):
    make_day(client, repo, settings)
    seen = []
    client.app.state.agent_transport = answer_with("Bring the gutter kit for stop 1.", seen)
    settings.ollama_api_key = "key-from-render"
    r = client.post(URL, headers=CREW, json={"question": "Anything risky?"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["assistant"] == "Bring the gutter kit for stop 1." and out["route_source"] == "solver"
    assert out["model"] == "qwen2.5:14b"

    req = seen[0]
    assert str(req.url) == "https://agent.example.com/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer key-from-render"
    sent = json.loads(req.content)
    assert sent["model"] == "qwen2.5:14b" and sent["stream"] is False
    user_text = sent["messages"][1]["content"]
    assert "100 A Example Rd" in user_text and "Anything risky?" in user_text
    # Privacy: nothing identifying the customer ever leaves the app.
    for secret in ("Customer A", "Customer B", "281", "555", "access_code", "phone", "pay_token"):
        assert secret not in user_text, secret
    assert [b["route_stop"] for b in out["data_sent"]["bookings"]] == [1, 2]
    assert {"name", "phone", "access_code"}.isdisjoint(out["data_sent"]["bookings"][0])


def test_works_before_the_route_is_built_and_with_no_bookings(client, repo, settings, on):
    seen = []
    client.app.state.agent_transport = answer_with("ok", seen)
    empty = client.post(URL, headers=CREW).json()
    assert empty["assistant"] == "No bookings on that day." and not seen        # no model call for an empty day
    make_day(client, repo, settings, build=False)
    out = client.post(URL, headers=CREW).json()
    assert out["route_source"] == "none" and all(b["route_stop"] is None for b in out["data_sent"]["bookings"])


def test_an_unreachable_or_broken_assistant_is_a_clean_502(client, repo, settings, on):
    make_day(client, repo, settings)

    def down(request):
        raise httpx.ConnectError("tunnel is down: https://agent.example.com secret-detail")

    client.app.state.agent_transport = httpx.MockTransport(down)
    r = client.post(URL, headers=CREW)
    assert r.status_code == 502 and "isn't reachable" in r.json()["detail"]
    assert "agent.example.com" not in r.text and "secret-detail" not in r.text

    client.app.state.agent_transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"oops": 1}))
    assert client.post(URL, headers=CREW).status_code == 502


def test_tunnel_password_is_sent_as_basic_auth(client, repo, settings, on):
    make_day(client, repo, settings)
    seen = []
    client.app.state.agent_transport = answer_with("ok", seen)
    settings.ollama_basic_auth = "sg-agent:s3cret"
    assert client.post(URL, headers=CREW).status_code == 200
    assert seen[0].headers["authorization"] == "Basic c2ctYWdlbnQ6czNjcmV0"       # sg-agent:s3cret
