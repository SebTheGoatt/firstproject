"""Ask customers for a Google review a little after the crew leaves.

About 20 minutes after a job is marked done (window: 15 minutes to 24 hours), each customer gets ONE
request: an app/browser notification if they turned those on, and a text when Twilio is set up. Their
visit page also shows a "Leave a Google review" button. Nothing is sent until GOOGLE_REVIEW_URL is set.

Google's review rules: ask every customer the same way, never offer anything for a review (no discounts,
no donations tied to it), and never ask only for 5 stars. The wording below follows them.

Runs off the request path: a small background loop in the web process (every few minutes), plus
POST /internal/review-requests for a cron job. Each job is claimed before anything is sent, so two
runs never message the same customer twice.
"""

import logging
from datetime import datetime, timedelta

from . import push
from .notify import send_text

log = logging.getLogger("reviews")

DELAY = timedelta(minutes=20)       # after the crew marks the job done
LOOKBACK = timedelta(hours=24)      # older finished jobs are left alone


def review_link(settings) -> str:
    """The owner's Google review link, or "" when it isn't set (or isn't an https link)."""
    url = (settings.google_review_url or "").strip()
    return url if url.startswith("https://") else ""


def review_message(first_name: str, business: str, visit_url: str, review_url: str, lang: str = "en") -> str:
    if lang == "es":
        photos = f"Tu recibo y tus fotos de antes y después están aquí: {visit_url} . " if visit_url else ""
        return (f"Hola {first_name}, gracias por elegir a {business}. {photos}Si hicimos un buen trabajo, ¿nos dejas "
                f"una reseña en Google? Ayuda mucho a un negocio local de veteranos: {review_url} . "
                f"Responde STOP para no recibir más mensajes.")
    photos = f"Your receipt and before & after photos are here: {visit_url} . " if visit_url else ""
    return (f"Hi {first_name}, thanks for choosing {business}. {photos}If we did a good job, would you leave us a "
            f"quick Google review? It means a lot to a veteran-owned local business: {review_url} . Reply STOP to opt out.")


def send_due_review_requests(repo, settings, sms, now: datetime, base_url: str, asked: set | None = None) -> dict:
    """Send the review request for every job finished 20 min-24 h ago that hasn't had one. Never raises."""
    report = {"asked": 0, "pushed": 0, "texted": 0, "mode": "off"}
    url = review_link(settings)
    if not url:
        return report
    since, until = now - LOOKBACK, now - DELAY
    try:
        due = repo.jobs_due_review(since, until)
        claim = repo.mark_review_requested                    # saved on the job: survives restarts
        report["mode"] = "saved"
    except Exception:
        # The review column isn't in the database yet: remember in memory, and only look at a short window
        # so a restart can't re-send yesterday's.
        log.warning("review_requested_at missing; run the latest Supabase SQL (reviews). Using memory for now.")
        asked = asked if asked is not None else set()
        try:
            due = [j for j in repo.jobs_completed_between(now - DELAY - timedelta(minutes=20), until) if j["id"] not in asked]
        except Exception:
            log.exception("Couldn't read finished jobs for review requests")
            return report
        claim = lambda job_id: (job_id not in asked, asked.add(job_id))[0]   # noqa: E731
        report["mode"] = "memory"
    for job in due:
        try:
            if not claim(job["id"]):
                continue                                       # another run got it first
            report["asked"] += 1
            # Opens their visit page, where the "Leave a Google review" button is waiting.
            report["pushed"] += push.send_to_job(repo, settings, job["id"], "review", link_suffix="?review=1")["sent"]
            if sms is not None and job.get("phone"):
                code = (job.get("access_code") or "").replace("-", "")
                visit_url = f"{base_url}/visit/{code}" if base_url and code else ""
                text = review_message(job["customer_name"].split()[0], settings.business_name, visit_url, url,
                                      job.get("lang") or "en")
                report["texted"] += bool(send_text(sms, job["phone"], text).get("sent"))
        except Exception:
            log.exception("Review request for job %s failed", job.get("id"))
    if report["asked"]:
        log.info("Review requests: %s", report)
    return report
