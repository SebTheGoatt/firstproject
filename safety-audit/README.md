# Safety Audit Engine

FastAPI service that reads a shop-log PDF, has Claude audit it for OSHA and equipment risks,
and saves the result to Supabase. Access is gated on an active Stripe subscription.

## Run locally

```bash
cd safety-audit
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
- `POST /api/v1/webhooks/stripe`: point Stripe's subscription events here
