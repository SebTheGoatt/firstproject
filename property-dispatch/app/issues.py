"""Problem reports: the crew's (damage, equipment trouble, no access, running late, with a photo) and the customer's.

    POST /api/stops/{stop_id}/issues        crew: report a problem on this stop (kind, note, optional photo)
    POST /api/visit/{code}/report           customer: "Something not right?" from their visit page (a short note)
    GET  /api/owner/issues                  owner: open reports, newest first
    GET  /api/owner/issues/{id}/photo       owner: the report's photo
    POST /api/owner/issues/{id}/resolve     owner: mark handled

Own it fast: the owner hears about damage from the crew, with a photo, before the customer calls. Reports are
private (owner only) and carry no customer name or phone. The owner gets an email too when Resend is set up
(OPERATIONAL_ALERT_EMAIL). Needs supabase/migrations/20261028000000_issues_and_sources.sql; until it's run the
endpoints answer 503 with that instruction instead of failing a crew member mid-route. Customer reports also need
supabase/migrations/20261108000000_reminders_and_customer_reports.sql (the "customer" kind).

The customer's button sits next to the Google review button and never replaces it: everyone sees both. Google
doesn't allow sending only happy customers to reviews ("review gating"), so we don't sort people first; an unhappy
customer simply gets a direct, private line to the owner.
"""

import logging
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .config import Settings
from .crew_auth import CrewIdentity
from .media import MediaError, normalize_photo, parse_photo

log = logging.getLogger(__name__)

KINDS = {"damage": "Damage to the property", "equipment": "Equipment broke down", "access": "Couldn't get in",
         "delay": "Running late", "other": "Something else", "customer": "A customer says something's not right"}
NEEDS_UPDATE = ("Problem reports need the database update: run supabase/migrations/"
                "20261028000000_issues_and_sources.sql in the Supabase SQL editor.")
CUSTOMER_UNAVAILABLE = ("We couldn't send that just now. Please reply to any of our text messages and the owner "
                        "will get back to you.")


class CustomerReport(BaseModel):
    note: str = Field(max_length=1000)


class IssueBody(BaseModel):
    kind: Literal["damage", "equipment", "access", "delay", "other"]
    note: str = Field(default="", max_length=1000)
    photo: str | None = Field(default=None, max_length=1_000_000)


def alert_owner(settings: Settings, issue: dict, address: str | None, client: httpx.Client | None = None) -> bool:
    """Email the owner (Resend). Best effort: a report is saved whether or not the email goes out."""
    if not (settings.resend_api_key and settings.operational_alert_email):
        return False
    text = (f"{KINDS[issue['kind']]}\n\nWhere: {address or 'see the owner screen'}\n"
            f"Note: {issue['note'] or '(none)'}\n\nOpen the owner screen to see the photo and mark it handled.")
    try:
        r = (client or httpx.Client(timeout=10)).post(
            "https://api.resend.com/emails", headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": settings.resend_from, "to": [settings.operational_alert_email],
                  "subject": f"{'Customer' if issue['kind'] == 'customer' else 'Crew'} reported: {KINDS[issue['kind']]}",
            "text": text})
        r.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        log.error("Problem report email failed: %s", type(exc).__name__)
        return False


def register_issues(app: FastAPI, settings: Settings, crew_auth, owner) -> None:
    def repo():
        return app.state.repo

    def table(call):
        try:
            return call()
        except HTTPException:
            raise
        except Exception as exc:          # table missing until the migration runs
            log.error("job_issues unavailable: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail=NEEDS_UPDATE)

    @app.post("/api/stops/{stop_id}/issues", status_code=201)
    def report(stop_id: str, body: IssueBody, who: CrewIdentity = Depends(crew_auth)):
        stop = repo().get_stop(stop_id)
        if stop is None:
            raise HTTPException(status_code=404, detail="Stop not found")
        if body.kind != "delay" and not body.note.strip() and not body.photo:
            raise HTTPException(status_code=422, detail="Add a photo or a short note so the owner knows what happened.")
        photo = None
        if body.photo:
            try:
                photo = normalize_photo(body.photo)
            except MediaError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
        issue = table(lambda: repo().add_issue(stop["job_id"], who.member_id, body.kind, body.note.strip(), photo))
        emailed = alert_owner(settings, issue, stop.get("address"))
        return {**issue, "emailed": emailed}

    @app.get("/api/owner/issues", dependencies=[Depends(owner)])
    def open_issues():
        return {"issues": table(lambda: repo().list_issues(open_only=True)), "kinds": KINDS}

    @app.get("/api/owner/issues/{issue_id}/photo", dependencies=[Depends(owner)])
    def issue_photo(issue_id: str):
        data = table(lambda: repo().issue_photo(issue_id))
        try:
            content_type, raw = parse_photo(data or "")
        except MediaError:
            raise HTTPException(status_code=404, detail="No photo")
        return Response(raw, media_type=content_type, headers={"Cache-Control": "private, max-age=3600"})

    @app.post("/api/owner/issues/{issue_id}/resolve", dependencies=[Depends(owner)])
    def resolve(issue_id: str):
        if not table(lambda: repo().resolve_issue(issue_id)):
            raise HTTPException(status_code=404, detail="That report is already handled or doesn't exist.")
        return {"resolved": True}


def register_customer_reports(app: FastAPI, settings: Settings, throttle, report_throttle, normalize_code) -> None:
    """The visit page's "Something not right?" box. Code-gated like the rest of the visit page, and rate-limited
    per visitor so it can't be used to flood the owner's inbox."""

    @app.post("/api/visit/{raw_code}/report", status_code=201)
    def customer_report(raw_code: str, body: CustomerReport, request: Request):
        ip = request.client.host if request.client else "unknown"
        if not throttle.allow(ip):                       # the visit page's code-guessing budget
            raise HTTPException(status_code=429, detail="Too many tries. Please wait a few minutes.")
        code = normalize_code(raw_code)
        v = app.state.repo.get_visit(code) if code else None
        if v is None:
            raise HTTPException(status_code=404, detail="We couldn't find that code. Check it and try again.")
        note = body.note.strip()
        if len(note) < 3:
            raise HTTPException(status_code=422, detail="Tell us in a few words what went wrong.")
        if not report_throttle.allow(ip):                # only real messages count toward the hourly limit
            raise HTTPException(status_code=429, detail="Too many tries. Please wait a few minutes.")
        try:
            issue = app.state.repo.add_issue(v["job_id"], None, "customer", note, None)
        except Exception as exc:      # migration not run yet: the "customer" kind isn't allowed
            log.error("Customer report not saved: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail=CUSTOMER_UNAVAILABLE)
        return {"received": True, "emailed": alert_owner(settings, issue, v.get("address"))}
