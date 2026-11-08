"""Day-before reminder: one text the evening before a visit, sent when the route is built.

"We mow tomorrow, likely between 9 and 11 AM. Please unlock the gate, bring pets inside and pick up toys and
hoses." Most lost visits in lawn care are a locked gate or a dog in the yard; the crew can't fix those on the
spot, and the customer still pays for the parts we couldn't reach. One plain reminder the night before fixes most
of them, and it reminds the customer they can still cancel free online until the "on the way" text.

Rules it keeps:
- It is a booking update (the SMS consent covers those): no promotions, no "book again", STOP opt-out included.
- Only visits on the built route get it (paid, in the day's area), in the language the customer booked in.
- Once per booking (`jobs.reminded_at`), even when the owner rebuilds the route. Without that column (migration
  not run yet) nothing is sent, so a rebuild can never text someone twice.
- Only between 8 AM and 9 PM local time (texting quiet hours), and only for a visit 1-3 days away.
- Never blocks the route: every failure is logged and skipped.
"""

import logging
from datetime import date, datetime, timedelta

from . import push
from .booking import local_now
from .notify import day_words, send_text, sentence, service_words

log = logging.getLogger("reminders")

QUIET_BEFORE, QUIET_FROM = 8, 21     # local hours: no texts before 8 AM or from 9 PM


def _hour(h: int, lang: str) -> str:
    if lang == "es":
        return f"{h}:00"
    return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


def arrival_window(eta: datetime | None, first_mow_hour: int, lang: str = "en") -> str:
    """A two-hour window around the planned arrival: 'between 9 and 11 AM'. The crew can run early or late,
    so it never promises a minute; it starts no earlier than the first mow of the day."""
    if eta is None:
        return ""
    start = max((eta - timedelta(minutes=30)).hour, first_mow_hour)
    end = start + 2
    if lang == "es":
        return f"entre las {_hour(start, lang)} y las {_hour(end, lang)}"
    if (start < 12) == (end < 12):                 # same half of the day: "between 9 and 11 AM"
        return f"between {start % 12 or 12} and {_hour(end, lang)}"
    return f"between {_hour(start, lang)} and {_hour(end, lang)}"


def reminder_message(first_name: str, business: str, service: str, when: str, window: str, visit_url: str,
                     lang: str = "en") -> str:
    if lang == "es":
        hora = f", probablemente {window}" if window else ""
        link = f"¿Necesitas cancelar? Es gratis hasta nuestro mensaje de \"vamos en camino\": {visit_url} . " if visit_url else ""
        return (f"Hola {first_name}, te recuerda {sentence(business)} Vamos {when} ({service}){hora}. "
                f"Por favor abre el portón, mete a tus mascotas y recoge juguetes y mangueras del césped. "
                f"{link}Responde STOP para no recibir más mensajes.")
    window = f", likely {window}" if window else ""
    link = f"Need to cancel? It's free until our on-the-way text: {visit_url} . " if visit_url else ""
    return (f"Hi {first_name}, a reminder from {sentence(business)} We're coming {when} for your {service}{window}. "
            f"Please unlock the gate, bring pets inside and pick up toys and hoses from the lawn. "
            f"{link}Reply STOP to opt out.")


def send_day_before(repo, settings, sms, day: date, stops: list[dict], now: datetime | None = None,
                    base_url: str | None = None) -> dict:
    """Text each customer on `day`'s route. `stops` = [{"job_id", "eta"}]. Never raises."""
    report = {"reminded": 0, "texted": 0, "pushed": 0, "skipped": None}
    now = now or local_now(settings)
    ahead = (day - now.date()).days
    if not 1 <= ahead <= 3:
        report["skipped"] = "not_upcoming"         # a same-day rebuild, or a day far out: no "tomorrow" text
        return report
    if not QUIET_BEFORE <= now.hour < QUIET_FROM:
        report["skipped"] = "quiet_hours"
        return report
    base = (base_url if base_url is not None else settings.public_base_url or "").rstrip("/")
    first_hour = int(settings.first_mow_time.split(":")[0])
    for stop in stops:
        try:
            if not repo.mark_reminded(stop["job_id"]):
                continue                             # already reminded (an earlier build of this route)
        except Exception:
            log.warning("reminded_at missing: run supabase/migrations/20261108000000_reminders_and_customer_reports.sql")
            report["skipped"] = "needs_migration"
            return report
        try:
            b = repo.job_brief(stop["job_id"])
            if b is None or b.get("status") not in ("pending", "scheduled"):
                continue
            lang = b.get("lang") or "en"
            eta = stop.get("eta")
            eta = datetime.fromisoformat(eta) if isinstance(eta, str) else eta
            when = ("mañana" if lang == "es" else "tomorrow") if ahead == 1 else (
                f"el {day_words(day, lang)}" if lang == "es" else f"on {day_words(day, lang)}")
            code = (b.get("access_code") or "").replace("-", "")
            visit_url = f"{base}/visit/{code}" if base and code else ""
            text = reminder_message(b["customer_name"].split()[0], settings.business_name,
                                    service_words(b["service"], b.get("add_ons"), lang), when,
                                    arrival_window(eta.astimezone(settings.tz) if eta else None, first_hour, lang),
                                    visit_url, lang)
            report["reminded"] += 1
            report["texted"] += bool(send_text(sms, b["phone"], text).get("sent"))
            report["pushed"] += push.send_to_job(repo, settings, stop["job_id"], "reminder")["sent"]
        except Exception:
            log.exception("Reminder for job %s failed", stop.get("job_id"))
    if report["reminded"]:
        log.info("Day-before reminders for %s: %s", day, report)
    return report
