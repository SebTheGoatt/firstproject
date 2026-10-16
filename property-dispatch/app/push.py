"""Web push notifications: "crew is on the way" and "all done", sent to phones that opted in.

A customer taps "Get updates on this phone" on their visit page; the phone's push address is
saved against that one booking. Messages go only to the people on that booking, only for those
two events, and a failure here never stops a booking, route or completion.

Keys: make a pair at /push-setup and put them in Render as VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY.
"""

import base64
import json
import logging

from cryptography.hazmat.primitives import serialization
from pywebpush import Vapid, WebPushException, webpush

from .config import Settings

log = logging.getLogger("push")

MESSAGES = {
    "on_the_way": {
        "en": "Your crew is on the way. Tap to see your arrival time.",
        "es": "Tu equipo va en camino. Toca para ver tu hora de llegada.",
    },
    "done": {
        "en": "All done! Tap to see your before & after photos and receipt.",
        "es": "¡Listo! Toca para ver tus fotos de antes y después y tu recibo.",
    },
}


ACTION = {"en": "View my visit", "es": "Ver mi visita"}


def _vapid(private_key: str) -> Vapid:
    """Accepts the 32-byte private key from /push-setup (base64url) or a standard PEM/DER key."""
    key = private_key.strip()
    if "BEGIN" not in key:
        try:
            raw = base64.urlsafe_b64decode(key + "=" * (-len(key) % 4))
            if len(raw) == 32:
                return Vapid.from_raw(key.encode())
        except ValueError:
            pass
    return Vapid.from_string(key)


# What went wrong, in words the crew app can show. The "problem" codes are safe to show (no keys, no addresses).
PROBLEMS = {
    "key_mismatch": "The push service rejected our key. The two notification keys in Render don't match (make ONE pair at /push-setup).",
    "key_invalid": "The private notification key in Render isn't valid. Make a new pair at /push-setup.",
    "phone_gone": "That phone's sign-up expired or was turned off. Ask the customer to tap Get updates again.",
    "service_busy": "The phone notification service didn't answer. Try again in a minute.",
    "rejected": "The push service refused the message.",
}


def _problem(exc: Exception) -> str:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (401, 403):
        return "key_mismatch"
    if status in (404, 410):
        return "phone_gone"
    if status is None or status == 429 or status >= 500:
        return "service_busy"
    return "rejected"


def keys_status(settings: Settings) -> str:
    """'off' (not set up), 'ok' (the two keys are a matching pair), 'key_mismatch' or 'key_invalid'.

    A phone signs up with the PUBLIC key, and every message is signed with the PRIVATE key. If they came
    from two different clicks of "Make my keys", the push service rejects everything, so catch it up front."""
    if not settings.push_enabled:
        return "off"
    try:
        derived = _vapid(settings.vapid_private_key).public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    except Exception:
        return "key_invalid"
    wanted = settings.vapid_public_key.strip()
    return "ok" if base64.urlsafe_b64encode(derived).decode().rstrip("=") == wanted.rstrip("=") else "key_mismatch"


def send_to_job(repo, settings: Settings, job_id: str, kind: str) -> dict:
    """Push `kind` ('on_the_way' or 'done') to every phone subscribed to this booking.

    Returns {"sent": n, "failed": n, "problem": code or None}. Never raises."""
    report = {"sent": 0, "failed": 0, "problem": None}
    if not settings.push_enabled or kind not in MESSAGES:
        return report
    status = keys_status(settings)
    if status != "ok":              # don't even try: every send would be refused
        try:
            has_phones = bool(repo.list_push_subscriptions(job_id))
        except Exception:
            has_phones = False
        if has_phones:
            log.error("Notification keys problem (%s): fix VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY in Render", status)
            report.update(failed=1, problem=status)
        return report
    try:
        subs = repo.list_push_subscriptions(job_id)
        if not subs:
            return report
        vapid = _vapid(settings.vapid_private_key)
    except Exception:
        log.exception("Push setup failed for job %s", job_id)
        report.update(failed=1, problem="key_invalid")
        return report

    for sub in subs:
        lang = sub["lang"] if sub["lang"] in ("en", "es") else "en"
        payload = json.dumps({"title": settings.business_name, "body": MESSAGES[kind][lang], "url": sub["visit_path"],
                              "action": ACTION[lang]})
        try:
            webpush(subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                    data=payload, vapid_private_key=vapid,
                    vapid_claims={"sub": settings.vapid_subject or settings.public_base_url}, ttl=3600, timeout=5)
            report["sent"] += 1
        except WebPushException as exc:
            problem = _problem(exc)
            report["failed"] += 1
            report["problem"] = report["problem"] or problem
            if problem == "phone_gone":          # the customer turned notifications off or removed the app
                log.info("Push address for job %s is gone; forgetting it", job_id)
                repo.delete_push_subscription(sub["endpoint"])
            else:
                log.warning("Push to job %s failed (%s): %s", job_id, problem, exc)
        except Exception as exc:
            report["failed"] += 1
            report["problem"] = report["problem"] or "service_busy"
            log.exception("Push to job %s failed", job_id)
    return report


def notify_job(repo, settings: Settings, job_id: str, kind: str) -> int:
    """Like send_to_job, but just the number of phones reached."""
    return send_to_job(repo, settings, job_id, kind)["sent"]
