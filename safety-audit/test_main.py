import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

import main

ACTIVE_COMPANY = {"id": "company-uuid", "stripe_customer_id": "cus_Test8972", "account_status": "active"}


def supabase_returning(rows):
    """A Supabase client whose every query chain ends in .execute() -> rows."""
    client = MagicMock()
    query = client.table.return_value
    for method in ("select", "eq", "insert", "update"):
        getattr(query, method).return_value = query
    query.execute.return_value = SimpleNamespace(data=rows)
    return client


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def stripe_subscriptions(monkeypatch):
    """Mock the Stripe payload: by default the customer has one active subscription."""
    listing = SimpleNamespace(data=[{"id": "sub_123", "status": "active"}])
    mock_list = MagicMock(return_value=listing)
    monkeypatch.setattr(main.stripe.Subscription, "list", mock_list)
    return mock_list


@pytest.fixture
def supabase(monkeypatch):
    db = supabase_returning([ACTIVE_COMPANY])
    monkeypatch.setattr(main, "get_supabase", lambda: db)
    return db


def blank_pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_non_pdf_upload_returns_400(client, stripe_subscriptions, monkeypatch):
    # Supabase has no cached active row, so verification goes to the mocked Stripe payload
    monkeypatch.setattr(main, "get_supabase", lambda: supabase_returning([{**ACTIVE_COMPANY, "account_status": "inactive"}]))

    response = client.post(
        "/api/v1/audit",
        params={"stripe_customer_id": "cus_Test8972"},
        files={"file": ("shop_log.txt", b"Zone 3 egress blocked", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid data transmission format. PDF required."
    stripe_subscriptions.assert_called_once_with(customer="cus_Test8972", status="active", limit=1)


def test_inactive_stripe_subscription_returns_403(client, stripe_subscriptions, monkeypatch):
    stripe_subscriptions.return_value = SimpleNamespace(data=[])
    monkeypatch.setattr(main, "get_supabase", lambda: supabase_returning([]))

    response = client.post(
        "/api/v1/audit",
        params={"stripe_customer_id": "cus_Lapsed"},
        files={"file": ("log.pdf", blank_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 403


def test_pdf_without_text_returns_400(client, stripe_subscriptions, supabase):
    response = client.post(
        "/api/v1/audit",
        params={"stripe_customer_id": "cus_Test8972"},
        files={"file": ("log.pdf", blank_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 400
    assert "no readable string data" in response.json()["detail"]


def test_successful_audit_is_saved(client, stripe_subscriptions, supabase, monkeypatch):
    findings = {
        "complianceScore": 85,
        "criticalViolations": ["Blockage identified in Zone 3 emergency egress paths."],
        "equipmentRisks": ["Hydraulic pressure variance flagged on Press #4."],
        "actionableSteps": ["Clear Zone 3 pathways immediately."],
    }
    monkeypatch.setattr(main.pypdf, "PdfReader", lambda f: SimpleNamespace(
        pages=[SimpleNamespace(extract_text=lambda: "Zone 3 egress blocked by pallets.")]
    ))

    async def fake_create(**kwargs):
        assert kwargs["model"] == main.AUDIT_MODEL
        assert "Zone 3 egress blocked" in kwargs["messages"][0]["content"]
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(findings))],
        )

    fake_anthropic = MagicMock()
    fake_anthropic.beta.messages.create = fake_create
    monkeypatch.setattr(main, "get_anthropic", lambda: fake_anthropic)

    response = client.post(
        "/api/v1/audit",
        params={"stripe_customer_id": "cus_Test8972"},
        files={"file": ("log.pdf", b"%PDF-stub", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json() == {"success": True, "data": findings}
    saved = supabase.table.return_value.insert.call_args.args[0]
    assert saved["company_id"] == "company-uuid"
    assert saved["compliance_score"] == 85


def test_webhook_with_bad_signature_returns_400(client):
    response = client.post(
        "/api/v1/webhooks/stripe",
        content=b"{}",
        headers={"stripe-signature": "t=1,v1=bogus"},
    )
    assert response.status_code == 400
