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

from .charity import causes as charity_causes, chosen_cause, describe as describe_charities, ledger, route_donation
from .config import Settings, site_url
from .models import SERVICE_LABELS, Service, order_label
from . import push
from .pricing import PACKAGES, bracket_label, bracket_profile
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
            "service_label": order_label(p["service"], p.get("add_ons")),
            "add_ons": p.get("add_ons") or [], "add_on_total": p.get("add_on_total") or 0.0,
            "scheduled_date": p["scheduled_date"],
            "job_done": p["status"] == "completed",
            "amount_due": p["amount_due"],
            "subtotal": p.get("subtotal"),
            "tax": p.get("tax_amount"),
            "tax_rate": p.get("tax_rate"),
            "lawn_sqft": p.get("lawn_sqft"),
            "package_label": PACKAGES[p["package"]]["label"] if p.get("package") in PACKAGES else None,
            "charity_rate": p.get("charity_rate"), "charity_amount": p.get("charity_amount"),
            "payment_status": p["payment_status"],
            "payment_method": p["payment_method"],
            "amount_paid": p["amount_paid"],
            "donation": p["donation"],
            "donation_ledger": ledger(settings, p.get("donation_split")) if p.get("donation_split") else [],
            "charities": describe_charities(settings),
            "charity_choice_name": next((c["name"] for c in charity_causes(settings)
                                         if c["key"] == chosen_cause(p.get("giving_split"))), None),
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
            base = site_url(settings, request)   # https, so Stripe accepts the return links
            session = stripe.create_checkout(
                job_id=p["job_id"], service_label=SERVICE_LABELS[Service(p["service"])], add_ons=p.get("add_ons"),
                service_date=str(p["scheduled_date"]), amount_due=p["amount_due"], donation=donation,
                success_url=f"{base}/pay/{token}?done=1", cancel_url=f"{base}/pay/{token}",
                subtotal=p.get("subtotal"), tax=p.get("tax_amount"), tax_rate=p.get("tax_rate"),
                charities=charity_causes(settings) if chosen_cause(p.get("giving_split")) else describe_charities(settings),
                charity_choice=chosen_cause(p.get("giving_split")),
                audit=payment_audit(request.app.state.repo, p),
                package_label=PACKAGES[p["package"]]["label"] if p.get("package") in PACKAGES else None,
                charity_rate=p.get("charity_rate"), charity_amount=p.get("charity_amount"),
            )
        except PaymentError as exc:
            raise HTTPException(status_code=503 if "unavailable" in str(exc) else 422, detail=str(exc))
        request.app.state.repo.record_checkout(p["job_id"], session["id"])
        return {"url": session["url"]}

    def payment_audit(repo, p: dict) -> dict:
        """What Stripe records with the payment: lot profile (+ yard/full), size bracket, tier, giving lane, route stop."""
        scope = next((a["label"] for a in p.get("add_ons") or [] if a.get("scope")), None)
        stop_id = repo.stop_id_for_job(p["job_id"])
        stop = repo.get_stop(stop_id) if stop_id else None
        return {
            "property_profile": bracket_profile(p.get("lawn_sqft")) + (f" · {scope}" if scope else ""),
            "size_bracket": bracket_label(p.get("lawn_sqft")),
            "service_track": PACKAGES[p["package"]]["label"] if p.get("package") in PACKAGES else "Older booking",
            "charity_lane": chosen_cause(p.get("giving_split")) or "split_33_33_34",
            "crew_route_id": f"{p['scheduled_date']}#{stop['sequence']}" if stop else f"{p['scheduled_date']}#not-routed",
        }

    def record_card_payment(request: Request, job_id: str, amount_cents, meta: dict) -> None:
        donation = round(int(meta.get("donation_cents") or 0) / 100, 2)
        repo = request.app.state.repo
        try:
            newly = repo.mark_paid(job_id, method="card", amount_paid=round(int(amount_cents or 0) / 100, 2),
                                   donation=donation, donation_split=route_donation(donation, meta.get("charity_choice") or None))
        except KeyError:
            log.warning("Stripe payment for unknown job %s", job_id)
            return
        log.info("Stripe payment for job %s recorded (new=%s)", job_id, newly)
        if newly:      # first time only: Stripe sends both checkout.session.completed and payment_intent.succeeded
            push.send_to_job(repo, settings, job_id, "paid")

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
                record_card_payment(request, job_id, obj.get("amount_total"), meta)
        elif event.get("type") == "payment_intent.succeeded":
            obj = event.get("data", {}).get("object", {})
            meta = obj.get("metadata") or {}
            if meta.get("job_id"):          # only our own payments carry a job id
                record_card_payment(request, meta["job_id"], obj.get("amount_received"), meta)
        return {"received": True}
