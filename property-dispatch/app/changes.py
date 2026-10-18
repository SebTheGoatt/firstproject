"""Changing a booking after it's made: the customer cancels, or the owner cancels / moves visits (rain days).

    POST /api/visit/{code}/cancel          customer: cancel before the crew is on the way (refund policy)
    POST /api/owner/jobs/{job_id}/cancel   owner: cancel one visit
    POST /api/owner/jobs/{job_id}/move     owner: move one visit to another day      {"day": "2026-10-21"}
    POST /api/owner/days/{day}/rain        owner: move every unstarted visit that day to the next service day

A cancelled card payment is refunded in full through Stripe automatically; if Stripe refuses, the reply says so
and the owner refunds it by hand. Customers get one text about each change (they agreed to booking texts).
Visits come off any route already built for that day, and the stops are renumbered.
"""

import logging
from datetime import date, timedelta

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from .booking import local_now
from .config import Settings
from .notify import day_words, send_text
from .payments import PaymentError

log = logging.getLogger(__name__)


class Confirm(BaseModel):
    confirm: bool


class MoveTo(BaseModel):
    day: date


def first(name: str) -> str:
    return (name or "there").split()[0]


def cancelled_text(b: dict, business: str, refund: str) -> str:
    es = (b.get("lang") or "en") == "es"
    money = {"started": (" Tu reembolso completo ya está en camino a tu tarjeta (5 a 10 días hábiles)." if es else
                         " Your full refund is on its way to your card (5 to 10 business days)."),
             "failed": (" Te devolveremos el pago con tarjeta en persona en los próximos días." if es else
                        " We'll refund your card payment by hand within a few days.")}.get(refund, "")
    if es:
        return f"Hola {first(b['customer_name'])}, tu visita de {business} del {day_words(b['scheduled_date'], 'es')} fue cancelada.{money} Responde STOP para no recibir más mensajes."
    return f"Hi {first(b['customer_name'])}, your {business} visit on {day_words(b['scheduled_date'], 'en')} is cancelled.{money} Reply STOP to opt out."


def moved_text(b: dict, business: str, day: date, weather: bool) -> str:
    es = (b.get("lang") or "en") == "es"
    why = (" por el clima" if es else " because of the weather") if weather else ""
    if es:
        return (f"Hola {first(b['customer_name'])}, movimos tu visita de {business}{why} al {day_words(day, 'es')}. "
                "Si ese día no te sirve, responde y te devolvemos todo. Responde STOP para no recibir más mensajes.")
    return (f"Hi {first(b['customer_name'])}, we moved your {business} visit{why} to {day_words(day, 'en')}. "
            "If that day doesn't work, reply and you get a full refund. Reply STOP to opt out.")


def register_change_routes(app: FastAPI, settings: Settings, owner, throttle, normalize_code) -> None:
    def repo():
        return app.state.repo

    def text(b: dict, body: str) -> None:
        try:
            send_text(app.state.sms, b["phone"], body)
        except Exception:
            log.exception("Change text failed")

    def cancel(b: dict) -> dict:
        """Cancel and refund. Never charges or refunds twice: the cancel is conditional on the visit still being open."""
        if not repo().cancel_job(b["id"]):
            raise HTTPException(status_code=409, detail="That visit can't be cancelled anymore.")
        refund = "none"
        if b["payment_method"] == "card" and b["payment_status"] == "paid":
            refund = "failed"
            if app.state.stripe is not None and b.get("stripe_session_id"):
                try:
                    app.state.stripe.refund_checkout(b["stripe_session_id"])
                    refund = "started"
                except PaymentError:
                    log.error("Refund for cancelled job %s needs to be done by hand in Stripe", b["id"])
            else:
                log.error("Refund for cancelled job %s needs to be done by hand in Stripe", b["id"])
        text(b, cancelled_text(b, settings.business_name, refund))
        return {"cancelled": True, "refund": refund}

    def next_service_day_after(day: date) -> date:
        return max(day + timedelta(days=1), local_now(settings).date() + timedelta(days=1))

    # ---------- Customer ----------
    @app.post("/api/visit/{raw_code}/cancel")
    def customer_cancel(raw_code: str, body: Confirm, request: Request):
        if not throttle.allow(request.client.host if request.client else "unknown"):
            raise HTTPException(status_code=429, detail="Too many tries. Please wait a few minutes.")
        code = normalize_code(raw_code)
        v = repo().get_visit(code) if code else None
        if v is None:
            raise HTTPException(status_code=404, detail="We couldn't find that code. Check it and try again.")
        if not body.confirm:
            raise HTTPException(status_code=422, detail="Please confirm the cancellation.")
        b = repo().job_brief(v["job_id"])
        if b["status"] not in ("pending", "scheduled") or b.get("notified_at") or b.get("stop_completed_at"):
            raise HTTPException(status_code=409, detail=("The crew is already on the way, so this visit can't be "
                                                         "cancelled online. Call or text us and we'll sort it out."))
        return cancel(b)

    # ---------- Owner ----------
    def brief_or_404(job_id: str) -> dict:
        b = repo().job_brief(job_id)
        if b is None:
            raise HTTPException(status_code=404, detail="No such booking.")
        return b

    @app.post("/api/owner/jobs/{job_id}/cancel", dependencies=[Depends(owner)])
    def owner_cancel(job_id: str):
        b = brief_or_404(job_id)
        if b.get("stop_completed_at"):
            raise HTTPException(status_code=409, detail="That visit is already done.")
        return cancel(b)

    @app.post("/api/owner/jobs/{job_id}/move", dependencies=[Depends(owner)])
    def owner_move(job_id: str, body: MoveTo):
        b = brief_or_404(job_id)
        if body.day <= local_now(settings).date():
            raise HTTPException(status_code=422, detail="Pick a day after today.")
        if not repo().move_job(job_id, body.day):
            raise HTTPException(status_code=409, detail="That visit is done or cancelled, so it can't move.")
        text(b, moved_text(b, settings.business_name, body.day, weather=False))
        return {"moved": True, "day": body.day}

    @app.post("/api/owner/days/{day}/rain", dependencies=[Depends(owner)])
    def rain_day(day: date):
        """Weather: every visit that day that hasn't started moves to the next service day, with a text to each."""
        to = next_service_day_after(day)
        moved = 0
        for j in repo().list_jobs(day):
            if j["status"] not in ("pending", "scheduled") or j.get("completed_at") or j.get("on_the_way_at"):
                continue
            b = repo().job_brief(j["job_id"])
            if b and not b.get("notified_at") and repo().move_job(j["job_id"], to):
                text(b, moved_text(b, settings.business_name, to, weather=True))
                moved += 1
        return {"moved": moved, "to": to}
