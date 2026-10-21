# Semper Safe

FastAPI service that reads a shop-log PDF, has Claude audit it for OSHA and equipment risks,
and saves the result to Supabase. Access is gated on an active Stripe subscription.

## Run locally

```bash
cd semper-safe
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # fill in your real keys; .env is git-ignored
uvicorn main:app --reload --port 8000
```

Open http://localhost:8000. Run `schema.sql` once in the Supabase SQL editor first.

## Test

```bash
pytest -q test_main.py
```

The tests mock Stripe, Supabase, and Claude, so they need no keys and no network.

## Endpoints

- `POST /api/v1/audit?stripe_customer_id=cus_...` with form field `file` (PDF)
- `GET /api/v1/audits/history?stripe_customer_id=cus_...`: the company's past audits, newest first
- `POST /api/v1/webhooks/stripe`: point Stripe's subscription events here

## Quickbase integration

`POST /api/v1/integrations/quickbase/webhook` audits a Quickbase record's shop log (field 6)
and writes the score and findings back to fields 12, 13 and 14. Change the field IDs at the
top of `quickbase.py` to match your table.

1. Set `QUICKBASE_REALM`, `QUICKBASE_USER_TOKEN` and `QUICKBASE_WEBHOOK_SECRET` in `.env`.
2. In Quickbase, create a webhook on the table that POSTs JSON to the endpoint above:
   `{"recordId": [Record ID#], "tableId": "<table id>", "appId": "<app id>", "stripe_customer_id": "cus_..."}`
3. Add a custom header `X-Semper-Safe-Token` with the same value as `QUICKBASE_WEBHOOK_SECRET`.
4. Trigger it on **add or modify, only when field 6 changes**. The write-back edits the record too;
   the server skips text it has already audited, but this setting keeps Quickbase from calling at all.
