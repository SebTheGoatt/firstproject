"""Customer payment page ("Pay your way") and the Stripe webhook.

    GET  /api/pay/{token}            what's owed, what's paid
    POST /api/pay/{token}/checkout   start a Stripe Checkout (price + optional donation)
    POST /webhooks/stripe            Stripe → "payment succeeded"

The pay token is a long random secret that only the customer receives (on
their booking confirmation and in the "job done" text), so the page needs
no account or password.
"""

import logging

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .config import Settings
from .models import SERVICE_LABELS, Service
from .payments import PaymentError, StripeClient, clean_donation, verify_webhook

log = logging.getLogger(__name__)


class CheckoutBody(BaseModel):
    donation: float | None = Field(default=0, ge=0)


def register_pay_routes(app: FastAPI, settings: Settings, stripe: StripeClient | None):
    def lookup(request: Request, token: str) -> dict:
        p = request.app.state.repo.get_payment(token) if len(token) >= 16 else None
        if p is None:
            raise HTTPException(status_code=404, detail="We couldn't find that payment link.")
        return p

    @app.get("/api/pay/{token}")
    def pay_info(token: str, request: Request):
        p = lookup(request, token)
        return {
            "business_name": settings.business_name,
            "first_name": p["customer_name"].split()[0],
            "service_label": SERVICE_LABELS[Service(p["service"])],
            "scheduled_date": p["scheduled_date"],
            "job_done": p["status"] == "completed",
            "amount_due": p["amount_due"],
            "subtotal": p.get("subtotal"),
            "tax": p.get("tax_amount"),
            "tax_rate": p.get("tax_rate"),
            "lawn_sqft": p.get("lawn_sqft"),
            "payment_status": p["payment_status"],
            "payment_method": p["payment_method"],
            "amount_paid": p["amount_paid"],
            "donation": p["donation"],
            "card_enabled": stripe is not None,
        }

    @app.post("/api/pay/{token}/checkout")
    def checkout(token: str, body: CheckoutBody, request: Request):
        if stripe is None:
            raise HTTPException(status_code=503, detail="Card payments aren't set up yet. You can pay the crew in cash.")
        p = lookup(request, token)
        if p["payment_status"] == "paid":
            raise HTTPException(status_code=409, detail="This visit is already paid. Thank you!")
        if p["amount_due"] is None:
            raise HTTPException(status_code=409, detail=(
                "Your final price is set when the crew finishes. We'll text you this link then."))
        try:
            donation = clean_donation(body.donation)
            base = str(request.base_url).rstrip("/")
            session = stripe.create_checkout(
                job_id=p["job_id"], service_label=SERVICE_LABELS[Service(p["service"])],
                service_date=str(p["scheduled_date"]), amount_due=p["amount_due"], donation=donation,
                success_url=f"{base}/pay/{token}?done=1", cancel_url=f"{base}/pay/{token}",
                subtotal=p.get("subtotal"), tax=p.get("tax_amount"), tax_rate=p.get("tax_rate"),
            )
        except PaymentError as exc:
            raise HTTPException(status_code=503 if "unavailable" in str(exc) else 422, detail=str(exc))
        request.app.state.repo.record_checkout(p["job_id"], session["id"])
        return {"url": session["url"]}

    @app.post("/webhooks/stripe", include_in_schema=False)
    async def stripe_webhook(request: Request, stripe_signature: str | None = Header(default=None)):
        payload = await request.body()
        try:
            event = verify_webhook(payload, stripe_signature, settings.stripe_webhook_secret)
        except PaymentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        if event.get("type") in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
            obj = event.get("data", {}).get("object", {})
            meta = obj.get("metadata") or {}
            job_id = meta.get("job_id") or obj.get("client_reference_id")
            if obj.get("payment_status") == "paid" and job_id:
                try:
                    newly = request.app.state.repo.mark_paid(
                        job_id, method="card",
                        amount_paid=round(int(obj.get("amount_total") or 0) / 100, 2),
                        donation=round(int(meta.get("donation_cents") or 0) / 100, 2),
                    )
                    log.info("Stripe payment for job %s recorded (new=%s)", job_id, newly)
                except KeyError:
                    log.warning("Stripe payment for unknown job %s", job_id)
        return {"received": True}
