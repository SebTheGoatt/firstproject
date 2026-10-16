"""The site's side of "are we on the same page?".

GET /api/agent/manifest returns what the site is, what it can do for agents, the business facts agents rely on
(prices, tax, areas, hours), which features and settings are on, and a fingerprint of all that. StarNet compares
it with its own copy (starnet/semper_green_site.py --sync) and reports anything that has drifted.

Only names and yes/no statuses appear here. Never a key, password, token, phone number or customer detail.
"""

import hashlib
import json

from . import push
from .charity import CHARITY_SPLIT
from .config import Settings
from .pricing import ADD_ONS, MAX_SQFT, MIN_SQFT, PACKAGES
from .zones import FLAT_FEE, SERVICE_ZONES

MANIFEST_VERSION = 1

# Env vars the owner sets in Render: (name, group, level, what it turns on)
SETTINGS_CHECKLIST = [
    ("SUPABASE_URL", "database", "required", "the live database"),
    ("SUPABASE_SERVICE_ROLE_KEY", "database", "required", "the live database"),
    ("CREW_ACCESS_TOKEN", "security", "required", "the owner sign-in"),
    ("CRON_SECRET", "security", "required", "the nightly route build"),
    ("WEBHOOK_SECRET", "security", "required", "job-completed webhooks"),
    ("PUBLIC_BASE_URL", "site", "recommended", "links in notifications and Stripe returns"),
    ("STRIPE_SECRET_KEY", "payments", "recommended", "card, Apple Pay and Google Pay"),
    ("STRIPE_WEBHOOK_SECRET", "payments", "recommended", "marking card payments as paid"),
    ("VAPID_PUBLIC_KEY", "notifications", "optional", "visit notifications"),
    ("VAPID_PRIVATE_KEY", "notifications", "optional", "visit notifications"),
    ("TWILIO_ACCOUNT_SID", "texting", "optional", "text messages"),
    ("TWILIO_AUTH_TOKEN", "texting", "optional", "text messages"),
    ("TWILIO_FROM_NUMBER", "texting", "optional", "text messages"),
    ("AGENT_KEY_READ", "agents", "optional", "StarNet looking at the site"),
    ("AGENT_KEY_OPS", "agents", "optional", "StarNet building routes"),
    ("OLLAMA_BASE_URL", "agents", "optional", "the dispatch assistant"),
    ("CHARITY_VFW_NAME", "giving", "recommended", "naming the VFW post on receipts"),
    ("CHARITY_NICU_NAME", "giving", "recommended", "naming the NICU program on receipts"),
    ("CHARITY_YOUTH_NAME", "giving", "recommended", "naming the youth program on receipts"),
]
_ATTR = {n: n.lower() for n, *_ in SETTINGS_CHECKLIST}
_ATTR.update({"CHARITY_YOUTH_NAME": "charity_youth_name"})


def _status(settings: Settings, name: str) -> str:
    """'set', 'missing', 'default' (still a placeholder / not customised). Never the value."""
    attr = _ATTR[name]
    value = getattr(settings, attr, "")
    if name.startswith("CHARITY_"):
        default = Settings.model_fields[attr].default
        return "default" if value == default else "set"
    if name in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY") and settings.data_backend == "memory":
        return "set"
    if not value:
        return "missing"
    return "default" if value == "change-me" else "set"


def _money(x) -> float:
    return float(x)


def facts(settings: Settings) -> dict:
    """What agents may rely on. Dicts only (no lists), so two copies can be compared field by field."""
    return {
        "pricing": {
            "base_fee": FLAT_FEE,
            "sqft_limits": {"min": MIN_SQFT, "max": MAX_SQFT},
            "packages": {k: {"label": p["label"], "rate_per_sqft": _money(p["rate"]), "giving": _money(p["giving"])}
                         for k, p in PACKAGES.items()},
            "add_ons": {k: {"label": a["label"], "price": None if a["price"] is None else _money(a["price"]),
                            "quote_only": bool(a.get("quote")), "seasonal": bool(a.get("season"))}
                        for k, a in ADD_ONS.items()},
        },
        "areas": {z.key: {"name": z.name, "tax_rate": z.tax_rate, "base_fee": z.mow_rate} for z in SERVICE_ZONES},
        "giving_split": {k: _money(v) for k, v in CHARITY_SPLIT.items()},
        "schedule": {"timezone": settings.business_timezone, "route_locks_at_hour": settings.freeze_hour,
                     "daily_job_quota": settings.daily_job_quota, "booking_horizon_days": settings.booking_horizon_days},
    }


def build_manifest(settings: Settings, state, endpoints: list[dict], build: dict, client_min_version: int,
                   api_version: int) -> dict:
    stripe_key = settings.stripe_secret_key or ""
    features = {
        "card_payments": state.stripe is not None,
        "texting": state.sms is not None,
        "visit_notifications": push.keys_status(settings) == "ok",
        "notification_keys": push.keys_status(settings),
        "dispatch_assistant": settings.agent_enabled,
        "agent_read_key": bool(settings.agent_key_read),
        "agent_ops_key": bool(settings.agent_key_ops),
    }
    config = [{"name": n, "group": g, "level": lvl, "turns_on": why, "status": _status(settings, n)}
              for n, g, lvl, why in SETTINGS_CHECKLIST]
    attention = [{"name": c["name"], "level": c["level"], "status": c["status"], "turns_on": c["turns_on"]}
                 for c in config if c["level"] in ("required", "recommended") and c["status"] in ("missing", "default")]
    stripe_mode = "live" if stripe_key.startswith(("sk_live_", "rk_live_")) else \
        "test" if stripe_key.startswith(("sk_test_", "rk_test_")) else None
    contract = {"manifest_version": MANIFEST_VERSION, "api_version": api_version, "endpoints": endpoints,
                "facts": facts(settings), "features": features, "stripe_mode": stripe_mode,
                "config": [{"name": c["name"], "status": c["status"]} for c in config]}
    fingerprint = hashlib.sha256(json.dumps(contract, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return {
        "manifest_version": MANIFEST_VERSION, "api_version": api_version, "min_client_version": client_min_version,
        "business": settings.business_name, "build": build, "endpoints": endpoints, "facts": contract["facts"],
        "features": features, "stripe_mode": stripe_mode, "config": config, "attention": attention,
        "fingerprint": fingerprint,
    }
