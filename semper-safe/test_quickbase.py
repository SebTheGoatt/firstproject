import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

import main
import quickbase

SECRET = "test-secret"
COMPANY = {"id": "company-uuid", "stripe_customer_id": "cus_Test8972", "account_status": "active"}
PAYLOAD = {"recordId": 42, "tableId": "bqx7abc", "appId": "bqx7app", "stripe_customer_id": "cus_Test8972"}
FINDINGS = {
    "complianceScore": 64,
    "criticalViolations": ["Zone 3 egress blocked."],
    "equipmentRisks": [],
    "actionableSteps": ["Clear Zone 3."],
}


class FakeSupabase:
    """Answers the company lookup and the loop-guard lookup; records inserts."""

    def __init__(self, previous_audit_text=None):
        self.previous_audit_text = previous_audit_text
        self.inserted = []

    def table(self, name):
        db = self
        query = MagicMock()
        for method in ("select", "eq", "order", "limit"):
            getattr(query, method).return_value = query
        query.insert.side_effect = lambda row: db.inserted.append(row) or query
        if name == "companies":
            rows = [COMPANY]
        elif self.previous_audit_text is not None:
            rows = [{"raw_text_payload": self.previous_audit_text}]
        else:
            rows = []
        query.execute.return_value = SimpleNamespace(data=rows)
        return query


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("QUICKBASE_WEBHOOK_SECRET", SECRET)
    return TestClient(main.app)


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(main, "get_supabase", lambda: fake)
    return fake


@pytest.fixture
def quickbase_api(monkeypatch):
    """Fake Quickbase: the record holds a shop log; writes succeed."""
    calls = []

    async def fake_post(path, body):
        calls.append((path, body))
        if path == "/records/query":
            return {"data": [{"6": {"value": calls_text["text"]}}]}
        return {"data": [], "metadata": {"lineErrors": {}}}

    calls_text = {"text": "Pallets stacked in Zone 3 egress all shift."}
    monkeypatch.setattr(quickbase, "quickbase_post", fake_post)
    return SimpleNamespace(calls=calls, record=calls_text)


@pytest.fixture
def claude(monkeypatch):
    audit = MagicMock()

    async def fake_audit(text):
        audit(text)
        return dict(FINDINGS)

    monkeypatch.setattr(main, "run_claude_audit", fake_audit)
    return audit


def post(client, token=SECRET):
    return client.post("/api/v1/integrations/quickbase/webhook", json=PAYLOAD, headers={"X-Semper-Safe-Token": token})


def test_rejects_requests_without_the_secret(client, db, quickbase_api, claude):
    response = post(client, token="wrong")

    assert response.status_code == 401
    assert quickbase_api.calls == []
    claude.assert_not_called()


def test_audits_record_and_writes_results_back(client, db, quickbase_api, claude):
    response = post(client)

    assert response.status_code == 200
    assert response.json() == {"status": "success", "record_id": 42, "score_updated": 64}
    claude.assert_called_once_with("Pallets stacked in Zone 3 egress all shift.")

    write_path, write_body = quickbase_api.calls[-1]
    assert write_path == "/records"
    row = write_body["data"][0]
    assert row["3"] == {"value": 42}
    assert row["12"] == {"value": 64}
    assert row["13"] == {"value": "Zone 3 egress blocked."}
    assert row["14"] == {"value": "No system fatigue detected."}

    assert db.inserted[0]["filename"] == "Quickbase bqx7abc record #42"
    assert db.inserted[0]["company_id"] == "company-uuid"


def test_skips_text_it_already_audited(client, quickbase_api, claude, monkeypatch):
    # The write-back edits the record, which can fire the webhook again with the same text
    fake = FakeSupabase(previous_audit_text=quickbase_api.record["text"])
    monkeypatch.setattr(main, "get_supabase", lambda: fake)

    response = post(client)

    assert response.json()["status"] == "skipped"
    claude.assert_not_called()
    assert [path for path, _ in quickbase_api.calls] == ["/records/query"]


def test_skips_records_with_no_log_text(client, db, quickbase_api, claude):
    quickbase_api.record["text"] = "   "

    response = post(client)

    assert response.json()["status"] == "skipped"
    claude.assert_not_called()


# Realistic crane log from a fabrication shop floor
CRANE_LOG = (
    "Shift entry: Overhead Crane #3 operational check completed. Lead noticed a slight hydraulic "
    "shudder during maximum structural beam lifting at 0800. Also, Zone 2 staging block exit paths "
    "are currently obstructed with unorganized scrap plate metal."
)


def test_full_pipeline_against_quickbase_http_api(client, db, claude, monkeypatch):
    """Runs the real quickbase_post, faking only the network, so URLs, headers and bodies are checked."""
    monkeypatch.setenv("QUICKBASE_REALM", "demo.quickbase.com")
    monkeypatch.setenv("QUICKBASE_USER_TOKEN", "b7tok_123")
    requests_seen = []

    def quickbase_server(request):
        requests_seen.append(request)
        body = json.loads(request.content)
        if request.url.path == "/v1/records/query":
            return httpx.Response(200, json={"data": [{"6": {"value": CRANE_LOG}}]})
        return httpx.Response(200, json={"data": [], "metadata": {"lineErrors": {}, "updatedRecordIds": [body["data"][0]["3"]["value"]]}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(quickbase.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(quickbase_server), **kw))

    response = client.post(
        "/api/v1/integrations/quickbase/webhook",
        json={"recordId": 101, "tableId": "b3x7abcde", "appId": "br98zxyz", "stripe_customer_id": "cus_9060XT_Live"},
        headers={"X-Semper-Safe-Token": SECRET},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success", "record_id": 101, "score_updated": 64}
    claude.assert_called_once_with(CRANE_LOG)

    read, write = requests_seen
    assert str(read.url) == "https://api.quickbase.com/v1/records/query"
    assert read.headers["QB-Realm-Hostname"] == "demo.quickbase.com"
    assert read.headers["Authorization"] == "QB-USER-TOKEN b7tok_123"
    assert json.loads(read.content) == {"from": "b3x7abcde", "select": [6], "where": "{3.EX.101}"}

    assert str(write.url) == "https://api.quickbase.com/v1/records"
    written = json.loads(write.content)
    assert written["to"] == "b3x7abcde"
    assert written["data"][0]["3"] == {"value": 101}
    assert written["data"][0]["12"] == {"value": 64}


def test_quickbase_write_rejection_is_reported(client, db, claude, monkeypatch):
    def quickbase_server(request):
        if request.url.path == "/v1/records/query":
            return httpx.Response(200, json={"data": [{"6": {"value": CRANE_LOG}}]})
        return httpx.Response(200, json={"data": [], "metadata": {"lineErrors": {"1": ["Field 12 is read-only"]}}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(quickbase.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(quickbase_server), **kw))

    response = post(client)

    assert response.status_code == 502
    assert db.inserted == []
