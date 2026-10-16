"""'You're next' SMS via Twilio, fired when the crew completes a stop."""

import logging
from datetime import datetime

import httpx

from .config import Settings
from .db import Repository
from .models import SERVICE_LABELS, Service, order_label

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


# Texts go out in the language the customer booked in ("en" or "es").
ES_LABELS = {"Mowing": "corte de césped", "Bin Cleaning": "limpieza de botes", "Gutters": "canaletas",
             "Bin cleaning": "limpieza de botes de basura", "Gutter cleaning": "limpieza de canaletas",
             "Holiday lighting quote": "cotización de luces navideñas"}
ES_DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
ES_MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def service_words(service: str, add_ons: list | None, lang: str) -> str:
    label = order_label(service, add_ons)
    if lang != "es":
        return label.lower()
    return " + ".join(ES_LABELS.get(part, part.lower()) for part in label.split(" + "))


def day_words(day, lang: str) -> str:
    """'Friday, Oct 16' or 'viernes 16 de oct'."""
    if lang == "es":
        return f"{ES_DAYS[day.weekday()]} {day.day} de {ES_MONTHS[day.month - 1]}"
    # ``%-d`` is not supported by Windows' strftime implementation. Build the
    # unpadded date explicitly so confirmation texts work on every host.
    return f"{day.strftime('%A, %b')} {day.day}"


def next_customer_message(stop: dict, settings: Settings, crew_name: str | None = None) -> str:
    first = stop["customer_name"].split()[0]
    lang = stop.get("lang") or "en"
    service = service_words(stop["service"], stop.get("add_ons"), lang)
    minutes = max(5, round(stop["leg_duration_s"] / 60))
    if lang == "es":
        who = f"{crew_name.split()[0]} de {settings.business_name}" if crew_name else settings.business_name
        return (
            f"Hola {first}, te saluda {who}. Acabamos de terminar el trabajo anterior y vamos en camino "
            f"para tu servicio de {service}; llegamos en unos {minutes} minutos. "
            f"Responde STOP para no recibir más mensajes."
        )
    who = f"{crew_name.split()[0]} from {settings.business_name}" if crew_name else settings.business_name
    return (
        f"Hi {first}, this is {who}. We just finished the previous job "
        f"and are heading your way for your {service} service, about {minutes} minutes out. "
        f"Reply STOP to opt out."
    )


def booking_message(first_name: str, settings: Settings, service_label: str, day_label: str,
                    code: str, visit_url: str, lang: str = "en") -> str:
    if lang == "es":
        return (
            f"Hola {first_name}, tu cita con {settings.business_name} quedó reservada: {service_label} el {day_label}. "
            f"Tu código de acceso es {code}. Sigue tu visita y mira tus fotos de antes y después: {visit_url} . "
            f"Responde STOP para no recibir más mensajes."
        )
    return (
        f"Hi {first_name}, you're booked with {settings.business_name} for {service_label.lower()} on {day_label}. "
        f"Your access code is {code}. Track your visit and see your before & after photos: {visit_url} . "
        f"Reply STOP to opt out."
    )


def send_text(sms: TwilioClient | None, to: str, body: str) -> dict:
    if sms is None:
        log.info("Twilio not configured; would text %s: %s", to, body)
        return {"sent": False, "reason": "twilio_disabled", "preview": body}
    try:
        return {"sent": True, "message_sid": sms.send_sms(to, body)}
    except httpx.HTTPError as exc:
        log.error("Text to %s failed: %s", to, exc)
        return {"sent": False, "reason": "send_failed"}


def pay_link_message(stop: dict, settings: Settings, pay_url: str) -> str:
    first = stop["customer_name"].split()[0]
    lang = stop.get("lang") or "en"
    service = service_words(stop["service"], stop.get("add_ons"), lang)
    if lang == "es":
        return (
            f"Hola {first}, terminamos tu servicio de {service}. ¡Gracias por elegir a {settings.business_name}! "
            f"Puedes pagar de forma segura aquí: {pay_url} . No se necesita propina. Las donaciones son bienvenidas y van para "
            f"VFW, familias de NICU y jóvenes en riesgo. Responde STOP para no recibir más mensajes."
        )
    return (
        f"Hi {first}, your {service} is done. Thanks for choosing {settings.business_name}! "
        f"You can pay securely here: {pay_url} . No tip necessary. Donations are welcome and go to "
        f"the VFW, NICU families and at-risk youth. Reply STOP to opt out."
    )


def send_pay_link(settings: Settings, stop: dict, pay_url: str, sms: TwilioClient | None) -> dict:
    body = pay_link_message(stop, settings, pay_url)
    if sms is None:
        log.info("Twilio not configured; would text %s: %s", stop["phone"], body)
        return {"sent": False, "reason": "twilio_disabled", "preview": body}
    try:
        return {"sent": True, "message_sid": sms.send_sms(stop["phone"], body)}
    except httpx.HTTPError as exc:
        log.error("Pay-link text failed for job %s: %s", stop["job_id"], exc)
        return {"sent": False, "reason": "send_failed"}


def notify_next_customer(
    repo: Repository, settings: Settings, completed_stop: dict, sms: TwilioClient | None
) -> dict:
    """Text the next unfinished stop on the route. Never sends twice for one stop."""
    nxt = repo.next_open_stop(completed_stop["route_id"], completed_stop["sequence"])
    if nxt is None:
        return {"notified": False, "reason": "route_complete"}

    if not repo.claim_notification(nxt["stop_id"]):
        return {"notified": False, "reason": "already_notified", "stop_id": nxt["stop_id"]}

    body = next_customer_message(nxt, settings, completed_stop.get("completed_by_name"))
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
