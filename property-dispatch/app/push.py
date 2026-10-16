"""Web push notifications: "crew is on the way" and "all done", sent to phones that opted in.

A customer taps "Get updates on this phone" on their visit page; the phone's push address is
saved against that one booking. Messages go only to the people on that booking, only for those
two events, and a failure here never stops a booking, route or completion.

Keys: make a pair at /push-setup and put them in Render as VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY.
"""

import base64
import json
import logging

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


def notify_job(repo, settings: Settings, job_id: str, kind: str) -> int:
    """Push `kind` ('on_the_way' or 'done') to every phone subscribed to this booking. Returns how many sent."""
    if not settings.push_enabled or kind not in MESSAGES:
        return 0
    try:
        subs = repo.list_push_subscriptions(job_id)
        if not subs:
            return 0
        vapid = _vapid(settings.vapid_private_key)
    except Exception:
        log.exception("Push setup failed for job %s", job_id)
        return 0

    sent = 0
    for sub in subs:
        lang = sub["lang"] if sub["lang"] in ("en", "es") else "en"
        payload = json.dumps({"title": settings.business_name, "body": MESSAGES[kind][lang], "url": sub["visit_path"],
                              "action": ACTION[lang]})
        try:
            webpush(subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                    data=payload, vapid_private_key=vapid,
                    vapid_claims={"sub": settings.vapid_subject or settings.public_base_url}, ttl=3600, timeout=5)
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):             # the customer turned notifications off or removed the app
                log.info("Push address for job %s is gone (HTTP %s); forgetting it", job_id, status)
                repo.delete_push_subscription(sub["endpoint"])
            else:
                log.warning("Push to job %s failed: %s", job_id, exc)
        except Exception:
            log.exception("Push to job %s failed", job_id)
    return sent
