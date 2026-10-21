from types import SimpleNamespace
from unittest.mock import MagicMock

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
