"""Printable dispatch manifest for a day's route, and an emailed backup copy (Resend).

    GET /api/owner/manifest/{date}   the manifest as plain text (owner only; print it from the browser)

The nightly route build emails it to OPERATIONAL_ALERT_EMAIL when RESEND_API_KEY is set, so the crew has the
day on paper even if phones or the site are down. It holds customer names, phones and gate notes, so it only
goes to the owner's address and never into logs.
"""

import logging
from datetime import date, datetime

import httpx

from .config import Settings
from .pricing import is_info

log = logging.getLogger(__name__)


def _balance(s: dict) -> str:
    due = s.get("amount_due")
    if s.get("payment_status") == "paid":
        return f"PAID ${float(s.get('amount_paid') or due or 0):.2f}"
    if due is None:
        return "Price set on site"
    if s.get("payment_method") == "card":
        return f"${float(due):.2f} by card (pay link sent when done)"
    return f"COLLECT ${float(due):.2f} CASH"


def build_manifest(route: dict, notes: dict[str, str], settings: Settings, day: date) -> str:
    out = ["=" * 80, " SEMPER GREEN LAWN CARE - OFFICIAL DISPATCH MANIFEST",
           f" OPERATIONAL DATE: {day:%A, %B} {day.day}, {day.year} | LOCK TIME: {settings.freeze_hour}:00 Central",
           "=" * 80, f" INITIAL DISPATCH ANCHOR YARD: ({settings.base_lat:.6f}, {settings.base_lng:.6f})", "-" * 80]
    for s in route["stops"]:
        out.append(f"\n[STOP #{s['sequence']}] - STATUS: {'DONE' if s.get('completed_at') else 'PENDING DISPATCH'}")
        out.append(f"  ADDRESS:  {s['address']}")
        out.append(f"  CLIENT:   {s['customer_name']} | {s['phone']}")
        out.append(f"  ACCESS:   {notes.get(s['stop_id']) or 'NO NOTE (no gate code on file)'}")
        extras = [a for a in s.get("add_ons") or [] if not is_info(a)]
        scope = next((a["label"] for a in extras if a.get("scope")), None)
        yard = next((a["label"] for a in s.get("add_ons") or [] if a.get("key") == "yard_type"), None)
        out.append(f"  SERVICES: [X] Lawn mowing{f' - {scope}' if scope else ''}"
                   + (f" ({s['lawn_sqft']:,} sq ft)" if s.get("lawn_sqft") else ""))
        if yard:
            out.append(f"            {yard}")
        for a in extras:
            if not a.get("scope"):
                out.append(f"            [X] ADD-ON: {a['label']}" + (f" (+${float(a['price']):.2f})" if a.get("price") else ""))
        out.append(f"  BALANCE:  {_balance(s)}")
        out.append("-" * 40)
    out += ["\n" + "=" * 80, " END OF DISPATCH MANIFEST - DISCIPLINE DICTATES EXECUTION", "=" * 80]
    return "\n".join(out)


def email_manifest(text: str, settings: Settings, day: date, client: httpx.Client | None = None) -> bool:
    """Send the manifest to the owner's inbox. Never raises; never logs the manifest (it has customer details)."""
    if not (settings.resend_api_key and settings.operational_alert_email):
        log.info("Manifest email not configured (RESEND_API_KEY / OPERATIONAL_ALERT_EMAIL)")
        return False
    try:
        r = (client or httpx.Client(timeout=15)).post(
            "https://api.resend.com/emails", headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": settings.resend_from, "to": [settings.operational_alert_email],
                  "subject": f"Dispatch manifest: {day:%m/%d/%Y}", "text": text})
        r.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        log.error("Manifest email failed: %s", type(exc).__name__)
        return False


def send_manifest_for(repo, settings: Settings, day: date) -> bool:
    route = repo.get_route(day)
    if not route:
        return False
    try:
        notes = repo.stop_notes(route["id"])
    except Exception:
        notes = {}
    return email_manifest(build_manifest(route, notes, settings, day), settings, day)
