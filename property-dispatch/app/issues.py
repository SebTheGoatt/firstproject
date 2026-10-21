"""Crew problem reports: damage, equipment trouble, no access, running late. Reported on the spot, with a photo.

    POST /api/stops/{stop_id}/issues        crew: report a problem on this stop (kind, note, optional photo)
    GET  /api/owner/issues                  owner: open reports, newest first
    GET  /api/owner/issues/{id}/photo       owner: the report's photo
    POST /api/owner/issues/{id}/resolve     owner: mark handled

Own it fast: the owner hears about damage from the crew, with a photo, before the customer calls. Reports are
private (owner only) and carry no customer name or phone. The owner gets an email too when Resend is set up
(OPERATIONAL_ALERT_EMAIL). Needs supabase/migrations/20261028000000_issues_and_sources.sql; until it's run the
endpoints answer 503 with that instruction instead of failing a crew member mid-route.
"""

import logging
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .config import Settings
from .crew_auth import CrewIdentity
from .media import MediaError, normalize_photo, parse_photo

log = logging.getLogger(__name__)

KINDS = {"damage": "Damage to the property", "equipment": "Equipment broke down", "access": "Couldn't get in",
         "delay": "Running late", "other": "Something else"}
NEEDS_UPDATE = ("Problem reports need the database update: run supabase/migrations/"
                "20261028000000_issues_and_sources.sql in the Supabase SQL editor.")


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
                  "subject": f"Crew reported: {KINDS[issue['kind']]}", "text": text})
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
