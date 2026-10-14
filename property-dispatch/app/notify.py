"""'You're next' SMS via Twilio, fired when the crew completes a stop."""

import logging
from datetime import datetime

import httpx

from .config import Settings
from .db import Repository
from .models import SERVICE_LABELS, Service

log = logging.getLogger(__name__)


class TwilioClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=10)

    def send_sms(self, to: str, body: str) -> str:
        s = self.settings
        resp = self.client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}/Messages.json",
            data={"To": to, "From": s.twilio_from_number, "Body": body},
            auth=(s.twilio_account_sid, s.twilio_auth_token),
        )
        resp.raise_for_status()
        return resp.json()["sid"]


def next_customer_message(stop: dict, settings: Settings) -> str:
    first = stop["customer_name"].split()[0]
    service = SERVICE_LABELS[Service(stop["service"])].lower()
    minutes = max(5, round(stop["leg_duration_s"] / 60))
    return (
        f"Hi {first}, this is {settings.business_name}. Our crew just finished the previous job "
        f"and is heading your way for your {service} service, about {minutes} minutes out. "
        f"Reply STOP to opt out."
    )


def notify_next_customer(
    repo: Repository, settings: Settings, completed_stop: dict, sms: TwilioClient | None
) -> dict:
    """Text the next unfinished stop on the route. Never sends twice for one stop."""
    nxt = repo.next_open_stop(completed_stop["route_id"], completed_stop["sequence"])
    if nxt is None:
        return {"notified": False, "reason": "route_complete"}

    if not repo.claim_notification(nxt["stop_id"]):
        return {"notified": False, "reason": "already_notified", "stop_id": nxt["stop_id"]}

    body = next_customer_message(nxt, settings)
    if sms is None:
        log.info("Twilio not configured; would text %s: %s", nxt["phone"], body)
        return {"notified": False, "reason": "twilio_disabled", "stop_id": nxt["stop_id"], "preview": body}

    try:
        sid = sms.send_sms(nxt["phone"], body)
    except httpx.HTTPError as exc:
        repo.release_notification(nxt["stop_id"])  # allow a retry
        log.error("Twilio send failed for stop %s: %s", nxt["stop_id"], exc)
        return {"notified": False, "reason": "send_failed", "stop_id": nxt["stop_id"]}

    return {"notified": True, "stop_id": nxt["stop_id"], "message_sid": sid, "sent_at": datetime.now().isoformat()}
