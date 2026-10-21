import os
import json
from functools import lru_cache
from fastapi import FastAPI, UploadFile, File, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import stripe
import anthropic
from anthropic import AsyncAnthropic
from supabase import create_client, Client
import pypdf
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Semper Safe Enterprise Core Engine", version="1.0.0")

# Cross-Origin Guardrails
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

AUDIT_MODEL = "claude-sonnet-5-5"


# External clients are built on first use so the app (and its tests) can import
# without live credentials in the environment.
@lru_cache
def get_supabase() -> Client:
    return create_client(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_KEY", ""))


@lru_cache
def get_anthropic() -> AsyncAnthropic:
    # Reads ANTHROPIC_API_KEY from the environment
    return AsyncAnthropic()


# Rigid System Command Mapping
SYSTEM_ARCHITECTURE_PROMPT = (
    "You are an elite enterprise industrial safety coordinator and senior OSHA compliance auditor.\n"
    "Analyze the provided daily operations shop log text. Identify safety anomalies, equipment wear signs, "
    "and protocol non-compliance factors.\n\n"
    "complianceScore is an integer from 0 to 100 representing the raw yard or floor safety rating.\n"
    "criticalViolations lists clear and present hazards or OSHA non-conformance findings.\n"
    "equipmentRisks lists signs of machinery fatigue, leaks, calibration variances, or anomalies mentioned.\n"
    "actionableSteps lists clear, prescriptive mitigation commands for the facility operations director.\n"
    "Only report what the log text supports; use an empty list when a category has no findings."
)

# Structured outputs guarantee the response matches this shape, so no
# "please output only JSON" prompting or markdown stripping is needed.
AUDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "complianceScore": {"type": "integer"},
        "criticalViolations": {"type": "array", "items": {"type": "string"}},
        "equipmentRisks": {"type": "array", "items": {"type": "string"}},
        "actionableSteps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["complianceScore", "criticalViolations", "equipmentRisks", "actionableSteps"],
    "additionalProperties": False,
}


# Relational Verification Filter
async def verify_active_tenant(stripe_customer_id: str):
    if not stripe_customer_id:
        raise HTTPException(status_code=401, detail="Authentication token missing.")

    try:
        # Check active status straight inside Supabase cache layer
        company_query = get_supabase().table("companies").select("*").eq("stripe_customer_id", stripe_customer_id).execute()
        company = company_query.data[0] if company_query.data else None
        if company and company["account_status"] == "active":
            return company

        # Fallback direct check against the Stripe live endpoint
        subscriptions = stripe.Subscription.list(
            customer=stripe_customer_id,
            status="active",
            limit=1
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Account validation failure: {str(e)}")

    if len(subscriptions.data) == 0:
        raise HTTPException(status_code=403, detail="Access denied. Active subscription required.")
    return company


async def run_claude_audit(extracted_text: str) -> dict:
    response = await get_anthropic().beta.messages.create(
        model=AUDIT_MODEL,
        max_tokens=16000,
        system=SYSTEM_ARCHITECTURE_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": AUDIT_SCHEMA}},
        # If a safety classifier declines, the API retries on a fallback model in the same call
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[
            {"role": "user", "content": f"Analyze this operation payload text:\n\n{extracted_text}"}
        ],
    )

    if response.stop_reason == "refusal":
        raise HTTPException(status_code=422, detail="AI engine declined to audit this document.")
    if response.stop_reason == "max_tokens":
        raise HTTPException(status_code=502, detail="AI engine response was cut off before completion.")

    raw_ai_string = next(block.text for block in response.content if block.type == "text")
    audit = json.loads(raw_ai_string)
    audit["complianceScore"] = max(0, min(100, audit["complianceScore"]))
    return audit


# Primary Processing Engine
@app.post("/api/v1/audit")
async def execute_compliance_audit(
    stripe_customer_id: str,
    file: UploadFile = File(...)
):
    # Enforce active commercial account verification
    tenant = await verify_active_tenant(stripe_customer_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Corporate footprint profile not found.")

    if not (file.filename or "").lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Invalid data transmission format. PDF required.")

    try:
        # Extract content out of file binary stream
        pdf_reader = pypdf.PdfReader(file.file)
        extracted_text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                extracted_text += page_text + "\n"
    except Exception:
        raise HTTPException(status_code=400, detail="Processing aborted. File could not be read as a PDF.")

    if not extracted_text.strip():
        raise HTTPException(status_code=400, detail="Processing aborted. Document contains no readable string data.")

    try:
        parsed_audit_data = await run_claude_audit(extracted_text)
    except HTTPException:
        raise
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Critical structural parsing error. AI engine output malformed JSON.")
    except anthropic.RateLimitError:
        raise HTTPException(status_code=503, detail="AI engine is busy. Retry shortly.")
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"AI engine error: {e.message}")

    try:
        # Record result inside immutable database history logs
        get_supabase().table("safety_audits").insert({
            "company_id": tenant['id'],
            "filename": file.filename,
            "compliance_score": parsed_audit_data["complianceScore"],
            "raw_text_payload": extracted_text[:5000],  # Keep reference slice to manage storage footprints
            "structured_findings": parsed_audit_data
        }).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audit completed but could not be saved: {str(e)}")

    return {"success": True, "data": parsed_audit_data}


# Historical Log Audit Enumeration Endpoint
@app.get("/api/v1/audits/history")
async def retrieve_audit_history(stripe_customer_id: str, limit: int = 50):
    tenant = await verify_active_tenant(stripe_customer_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Corporate profile footprint missing.")

    try:
        history_query = get_supabase().table("safety_audits")\
            .select("id, filename, compliance_score, structured_findings, created_at")\
            .eq("company_id", tenant['id'])\
            .order("created_at", desc=True)\
            .limit(max(1, min(limit, 200)))\
            .execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database ledger readout failure: {str(e)}")

    return {"success": True, "history": history_query.data}


# Stripe subscription statuses that keep a tenant's access on
ACTIVE_STRIPE_STATUSES = {"active", "trialing"}


# Real-Time Operational Webhook Port
@app.post("/api/v1/webhooks/stripe")
async def process_lifecycle_event(request: Request, stripe_signature: str = Header(None)):
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, os.getenv("STRIPE_WEBHOOK_SECRET")
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook Authentication Error: {str(e)}")

    event_type = event['type']
    event_object = event['data']['object']

    # Sync downstream client operational states with billing real-time loops
    if event_type in ("customer.subscription.created", "customer.subscription.updated"):
        is_active = event_object.get("status") in ACTIVE_STRIPE_STATUSES
        description = (event_object.get("description") or "").lower()
        get_supabase().table("companies").update({
            "account_status": "active" if is_active else "inactive",
            "tier": "enterprise" if "enterprise" in description else "starter"
        }).eq("stripe_customer_id", event_object['customer']).execute()

    elif event_type == "customer.subscription.deleted":
        get_supabase().table("companies").update({
            "account_status": "suspended"
        }).eq("stripe_customer_id", event_object['customer']).execute()

    return {"status": "event_processed_successfully"}


# Integrations register before the "/" static mount, which would otherwise catch their paths
from quickbase import qb_router  # noqa: E402
app.include_router(qb_router)

# Mount public directory web interface
app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "public"), html=True), name="public")
