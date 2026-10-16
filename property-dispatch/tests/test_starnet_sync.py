"""Claude Code (the site) and StarNet on the same page: the manifest, the comparison, and the guard tests."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "starnet"))
import semper_green_site as sg  # noqa: E402

from app import agent_api, pricing  # noqa: E402

READ = {"X-Agent-Key": "read-key-123"}


@pytest.fixture
def on(settings):
    settings.agent_key_read = "read-key-123"
    return settings


@pytest.fixture
def manifest(client, on):
    def get():
        r = client.get("/api/agent/manifest", headers=READ)
        assert r.status_code == 200, r.text
        return r.json()
    return get


def test_manifest_needs_the_agent_key_and_holds_no_secrets(client, on, manifest):
    assert client.get("/api/agent/manifest").status_code == 401
    on.stripe_secret_key = "sk_test_SUPERSECRETVALUE"
    on.crew_access_token = "owner-secret-code"
    on.vapid_private_key = "private-key-material"
    text = json.dumps(manifest())
    for secret in ("SUPERSECRETVALUE", "owner-secret-code", "private-key-material", "read-key-123"):
        assert secret not in text
    m = manifest()
    assert m["business"] == "Semper Green Lawn Care" and m["manifest_version"] == 1 and m["api_version"] == agent_api.API_VERSION
    assert m["stripe_mode"] == "test"          # only the key's prefix is read, never the key itself
    on.stripe_secret_key = "sk_live_SUPERSECRETVALUE"
    assert manifest()["stripe_mode"] == "live" and "SUPERSECRETVALUE" not in json.dumps(manifest())
    on.stripe_secret_key = ""
    assert manifest()["stripe_mode"] is None


def test_manifest_facts_match_the_pricing_code(manifest):
    f = manifest()["facts"]
    assert f["pricing"]["base_fee"] == 35.0 and f["pricing"]["sqft_limits"] == {"min": 100, "max": 87120}
    assert f["pricing"]["packages"]["supporter"] == {"label": "Plus", "rate_per_sqft": 0.01, "giving": 0.07}
    assert f["pricing"]["add_ons"]["holiday_lights"]["quote_only"] is True and f["pricing"]["add_ons"]["gutters"]["price"] == 15.0
    assert "COLONY_RIDGE" in f["areas"] and f["areas"]["COLONY_RIDGE"]["tax_rate"] == 0.0825
    assert sum(f["giving_split"].values()) == pytest.approx(1.0)
    assert f["schedule"]["route_locks_at_hour"] == 17


def test_manifest_lists_what_the_owner_still_has_to_set(client, on, manifest):
    on.crew_access_token = "change-me"
    m = manifest()
    names = {a["name"]: a["status"] for a in m["attention"]}
    assert names["CREW_ACCESS_TOKEN"] == "default"                     # an insecure placeholder is flagged
    assert names["CHARITY_VFW_NAME"] == "default" and "STRIPE_SECRET_KEY" in names
    assert all(a["level"] in ("required", "recommended") for a in m["attention"])   # optional extras don't nag
    on.crew_access_token = "owner-secret-code"
    assert "CREW_ACCESS_TOKEN" not in {a["name"] for a in manifest()["attention"]}


def test_the_fingerprint_changes_only_when_something_real_changes(client, on, manifest):
    a, b = manifest(), manifest()
    assert a["fingerprint"] == b["fingerprint"]
    on.ollama_base_url = "https://agent.example.com/v1"                 # a feature turned on
    assert manifest()["fingerprint"] != a["fingerprint"]


def test_THE_GUARD_starnet_tools_and_the_site_contract_cannot_drift_apart():
    """If this fails, someone changed the tool list on one side only. Fix both together."""
    site = {e["tool"]: e for e in agent_api.ENDPOINTS}
    local = {t["function"]["name"] for t in sg.TOOLS}
    assert local == set(site)
    assert sg.NEEDS_APPROVAL == {n for n, e in site.items() if e["needs_approval"]}
    assert all(e["scope"] == "ops" for n, e in site.items() if e["needs_approval"])   # approval-gated = ops key only
    assert sg.CLIENT_VERSION >= agent_api.CLIENT_MIN_VERSION


def test_accepting_the_site_puts_both_sides_on_the_same_page(manifest, tmp_path):
    m = manifest()
    path = sg.save_expectations(m, str(tmp_path / "exp.json"))
    report = sg.compare(m, sg.load_expectations(path))
    assert report["in_sync"] is True and report["critical"] == [] and report["differences"] == []
    assert sg.format_report(report).startswith("✅")


def test_it_notices_when_the_site_changes_a_price_or_a_feature(client, on, manifest, tmp_path, monkeypatch):
    m = manifest()
    expected = sg.load_expectations(sg.save_expectations(m, str(tmp_path / "exp.json")))
    packages = copy.deepcopy(pricing.PACKAGES)
    packages["standard"]["rate"] = pricing.Decimal("0.011")
    monkeypatch.setattr(pricing, "PACKAGES", packages)
    monkeypatch.setattr("app.agent_manifest.PACKAGES", packages)
    on.ollama_base_url = "https://agent.example.com/v1"
    report = sg.compare(manifest(), expected)
    assert report["in_sync"] is False
    joined = " ".join(report["differences"])
    assert "facts.pricing.packages.standard.rate_per_sqft: StarNet has 0.009, the site says 0.011" in joined
    assert "features.dispatch_assistant: StarNet has False, the site says True" in joined
    assert sg.format_report(report).startswith("⚠️")


def test_a_safety_mismatch_is_critical_not_just_different(manifest):
    m = manifest()
    report = sg.compare(m, None, needs_approval=set())                  # a StarNet that forgot the approval step
    assert not report["in_sync"] and any(c.startswith("SAFETY") and "build_route" in c for c in report["critical"])
    stricter = sg.compare(m, None, needs_approval=sg.NEEDS_APPROVAL | {"day_summary"})
    assert stricter["in_sync"] and any("stricter" in n for n in stricter["notes"])


def test_missing_extra_and_outdated_tools_are_reported(manifest):
    m = manifest()
    fewer = [t for t in sg.TOOLS if t["function"]["name"] != "week_outlook"]
    assert any("week_outlook" in d for d in sg.compare(m, None, tools=fewer)["differences"])
    extra = sg.TOOLS + [sg._tool("delete_everything", "no")]
    assert any("delete_everything" in c for c in sg.compare(m, None, tools=extra)["critical"])
    newer = {**m, "min_client_version": 99}
    assert any("version" in c for c in sg.compare(newer, None)["critical"])


def test_the_sync_tool_works_through_the_model_tools(client, on, manifest, monkeypatch):
    site = sg.SemperGreenSite(base_url="http://localhost:8000", key="read-key-123")
    monkeypatch.setattr(site, "_call", lambda method, path: client.request(method, path, headers=READ).json())
    monkeypatch.setattr(sg, "load_expectations", lambda path=None: None)
    out = json.loads(sg.run_tool(site, "sync_check", {}))
    assert out["in_sync"] is True and any("No saved expectations" in n for n in out["notes"])
    assert any("CHARITY_VFW_NAME" in a for a in out["attention"])
