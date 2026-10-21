import os
import hmac
import logging
import httpx
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

# main is fully loaded before this module is imported (see the bottom of main.py),
# and lookups go through the module so tests can patch main's helpers.
import main

logger = logging.getLogger("SemperSafeQuickbase")

qb_router = APIRouter(prefix="/api/v1/integrations/quickbase", tags=["Quickbase"])

QB_API = "https://api.quickbase.com/v1"

# Field ID mappings matching the customer's Quickbase table layout
RECORD_ID_FIELD_ID = "3"          # Quickbase's built-in Record ID# field
TEXT_LOG_FIELD_ID = "6"           # Raw shop floor entries
COMPLIANCE_SCORE_FIELD_ID = "12"  # 0-100 score written back
VIOLATIONS_FIELD_ID = "13"        # Critical violations written back
EQUIPMENT_RISK_FIELD_ID = "14"    # Machine degradation alerts written back


class QuickbaseWebhookPayload(BaseModel):
    recordId: int
    tableId: str
    appId: str
    stripe_customer_id: str


def quickbase_headers() -> dict:
    return {
        # Your realm, e.g. "yourcompany.quickbase.com"
        "QB-Realm-Hostname": os.getenv("QUICKBASE_REALM", ""),
        "Authorization": f"QB-USER-TOKEN {os.getenv('QUICKBASE_USER_TOKEN', '')}",
        "Content-Type": "application/json",
    }


async def quickbase_post(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(f"{QB_API}{path}", headers=quickbase_headers(), json=body)
    if response.status_code != 200:
        logger.error("Quickbase %s returned %s: %s", path, response.status_code, response.text[:500])
        raise HTTPException(status_code=502, detail=f"Quickbase rejected the {path} request ({response.status_code}).")
    return response.json()


def audit_label(payload: QuickbaseWebhookPayload) -> str:
    return f"Quickbase {payload.tableId} record #{payload.recordId}"


def already_audited(company_id: str, label: str, text: str) -> bool:
    """True when this record's latest saved audit was run on the same text.

    Writing results back edits the record, which can fire the webhook again;
    this stops that from becoming an endless (and billed) audit loop.
    """
    latest = main.get_supabase().table("safety_audits")\
        .select("raw_text_payload")\
        .eq("company_id", company_id)\
        .eq("filename", label)\
        .order("created_at", desc=True)\
        .limit(1)\
        .execute()
    return bool(latest.data) and latest.data[0]["raw_text_payload"] == text[:5000]


@qb_router.post("/webhook")
async def handle_quickbase_record_update(
    payload: QuickbaseWebhookPayload,
    x_semper_safe_token: str = Header(""),
):
    # Only your Quickbase webhook knows this secret (set it as a custom header there)
    expected = os.getenv("QUICKBASE_WEBHOOK_SECRET", "")
    if not expected or not hmac.compare_digest(x_semper_safe_token, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook token.")

    tenant = await main.verify_active_tenant(payload.stripe_customer_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Corporate profile footprint missing.")

    # A. Read the raw text entry from the Quickbase record
    query = await quickbase_post("/records/query", {
        "from": payload.tableId,
        "select": [int(TEXT_LOG_FIELD_ID)],
        "where": f"{{{RECORD_ID_FIELD_ID}.EX.{payload.recordId}}}",
    })
    records = query.get("data", [])
    if not records:
        raise HTTPException(status_code=404, detail="Quickbase record not found.")

    raw_shop_text = records[0].get(TEXT_LOG_FIELD_ID, {}).get("value") or ""
    if not raw_shop_text.strip():
        return {"status": "skipped", "reason": "No shop log text in the record."}

    label = audit_label(payload)
    try:
        if already_audited(tenant["id"], label, raw_shop_text):
            return {"status": "skipped", "reason": "This text was already audited."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audit history lookup failed: {str(e)}")

    # B. Run the same Claude audit the PDF upload uses
    try:
        findings = await main.run_claude_audit(raw_shop_text)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Claude audit failed for %s: %s", label, e)
        raise HTTPException(status_code=502, detail="AI engine error while auditing the record.")

    score = findings["complianceScore"]

    # C. Write results back to the originating record (field 3 as the key updates it in place)
    write = await quickbase_post("/records", {
        "to": payload.tableId,
        "data": [{
            RECORD_ID_FIELD_ID: {"value": payload.recordId},
            COMPLIANCE_SCORE_FIELD_ID: {"value": score},
            VIOLATIONS_FIELD_ID: {"value": "\n".join(findings["criticalViolations"]) or "No core anomalies flagged."},
            EQUIPMENT_RISK_FIELD_ID: {"value": "\n".join(findings["equipmentRisks"]) or "No system fatigue detected."},
        }],
    })
    line_errors = write.get("metadata", {}).get("lineErrors")
    if line_errors:
        logger.error("Quickbase write-back errors for %s: %s", label, line_errors)
        raise HTTPException(status_code=502, detail="Quickbase refused the audit results for this record.")

    # D. Save to the history ledger (this is also what the loop guard checks)
    try:
        main.get_supabase().table("safety_audits").insert({
            "company_id": tenant["id"],
            "filename": label,
            "compliance_score": score,
            "raw_text_payload": raw_shop_text[:5000],
            "structured_findings": findings,
        }).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audit written to Quickbase but not saved to history: {str(e)}")

    return {"status": "success", "record_id": payload.recordId, "score_updated": score}
