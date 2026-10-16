"""
Semper Green — Live visitor feed (backend, v4)
==============================================

Pseudonymous, near-real-time visibility into site activity: visitors,
booking-funnel milestones, bookings (counted server-side only), and
estimated departures.

OWNER-ONLY: the live station's data (/api/live/stats) is gated by the
crew sign-in system — the owner's master code or an owner session token
(X-Crew-Token). Crew members and the public get 403/401. There is no
separate password, and the station is not linked from the public site;
the link lives in the owner's crew-app Dashboard tab.

What it stores: random session ids, page labels (never raw URLs),
funnel milestones, timestamps. Never names, phones, addresses, IPs,
or anything typed into the form.

INSTALL (FastAPI)
-----------------
1. Put this file next to your main app (e.g. app/live_feed.py).
   The dashboard itself lives inside the owner's crew-app Dashboard
   tab (static/crew.html) — there is no separate page to install.
2. In your main app file, after register_crew_routes returns crew_auth:

     from .live_feed import record_booking, register_live_routes
     register_live_routes(app, settings, crew_auth)

   And inside your POST /api/jobs handler, right after the job is saved:

     record_booking(job_id=str(job["id"]))

NOTES / LIMITS (please read)
----------------------------
- Departures are ESTIMATES from browser lifecycle signals:
  - a visitor who closes the tab without a beacon (crash, mobile
    kill) is not counted as a departure — they just age out;
  - a visitor who switches apps without closing the tab is not
    counted as a departure while they stay "online";
  - it cannot tell you why someone left.
- Funnel milestones are activity counts ("reached this step"),
  deduplicated per session, not a strict sequential funnel —
  visitors can fill the form in any order.
- State is in-memory with best-effort JSON persistence, designed
  for a single worker. On Render's free tier the instance sleeps;
  after a cold start counters restore from the file if it survived,
  but the live activity feed starts fresh. This is a live view,
  not an audit log — for durable history, write events to your
  real database.
- The ingest endpoint is allowlisted and rate-limited per session,
  but a determined abuser can mint new session ids; treat the
  numbers as directional, not a source of truth for billing.
- Day rolls over at midnight America/Chicago (your business day).
"""

import json
import os
import re
import secrets
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from .crew_auth import CrewIdentity

_lock = threading.Lock()

HERE = Path(__file__).parent                        # app/
DATA_FILE = Path(os.environ.get("LIVE_DATA_FILE") or HERE.parent / ".live_stats.json")

EVENT_TYPES = {"pageview", "step", "ping", "exit"}
PAGE_LABELS = {"home", "booking", "team", "visit", "other"}
SID_RE = re.compile(r"^[A-Za-z0-9_-]{6,40}$")
TZ = ZoneInfo("America/Chicago")

EXIT_GRACE_SECONDS = 15      # pageview within this window retracts an exit (internal navigation)
ONLINE_WINDOW_SECONDS = 300  # "online now" = active in the last 5 minutes
SESSION_TTL_SECONDS = 1800   # forget idle sessions after 30 minutes
COMMITTED_EXIT_TTL_SECONDS = 7200  # remember committed exit page ids for 2 hours
RATE_LIMIT_PER_MINUTE = 30   # per session id
FUNNEL_MAX_STEP = 4          # client milestones; step 5 (booked) is server-only
BOOKING_DEDUPE_CAP = 5000

FUNNEL_LABELS = {
    1: "Lawn size entered",
    2: "Rate chosen",
    3: "Quote displayed",
    4: "Submit clicked",
    5: "Booked",
}

# --- state (all pseudonymous) ---
_recent = deque(maxlen=400)     # recent activity rows for the live feed
_sessions = {}                  # sid -> last-seen epoch seconds
_session_steps = {}             # sid -> set of milestones reached (independent)
_last_pageview = {}              # sid -> last pageview epoch seconds
_last_pid = {}                   # sid -> page instance id of the latest pageview
_last_exit_pid = {}              # sid -> page instance id of the last exit beacon
_counted_visits = set()          # sids already counted as a visit today
_pending_exits = {}             # sid -> exit row awaiting possible retraction
_committed_exit_pids = {}        # (sid, pid) -> ts of committed departures
_exit_steps = {}                # milestone label -> committed exit count (drop-off)
_rate = {}                      # sid -> [window_start, count]
_booked_jobs = set()            # job ids already counted (bounded)
_day = {"date": None, "visits": 0, "bookings": 0, "exits": 0}
_funnel = [0] * 6              # _funnel[n] = sessions that ever reached milestone n (1..5)
_last_persist = 0.0


# ------------------------------------------------------------------ persistence

def _persist_locked():
    global _last_persist
    if time.time() - _last_persist < 20:
        return
    _last_persist = time.time()
    try:
        tmp = DATA_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump({"day": _day, "funnel": _funnel, "exit_steps": _exit_steps}, f)
        os.replace(tmp, DATA_FILE)
    except OSError:
        pass  # ephemeral disk is fine — live view, not an audit log


def _load():
    try:
        data = json.loads(DATA_FILE.read_text())
        if isinstance(data.get("day"), dict):
            _day.update(data["day"])
        saved = data.get("funnel")
        if isinstance(saved, list) and len(saved) == len(_funnel):
            for i, v in enumerate(saved):
                _funnel[i] = int(v)
        if isinstance(data.get("exit_steps"), dict):
            _exit_steps.update({str(k): int(v) for k, v in data["exit_steps"].items()})
    except (OSError, ValueError, TypeError):
        pass


_load()


# ------------------------------------------------------------------ helpers

def _now() -> float:
    return time.time()


def _today() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def _row(sid, kind, text, **extra):
    return {"ts": round(_now()), "sid": (sid or "")[:8], "kind": kind, "text": text, **extra}


def _drop_session_state(sid):
    _sessions.pop(sid, None)
    _session_steps.pop(sid, None)
    _last_pageview.pop(sid, None)
    _last_pid.pop(sid, None)
    _last_exit_pid.pop(sid, None)
    _counted_visits.discard(sid)
    _rate.pop(sid, None)
    # _committed_exit_pids intentionally survives: a replayed exit beacon for
    # a page whose departure already committed must not count twice.


def _prune_locked():
    """Expire stale sessions and committed-exit records; commit un-retracted exits."""
    now = _now()

    for key in [k for k, ts in _committed_exit_pids.items()
               if now - ts > COMMITTED_EXIT_TTL_SECONDS]:
        _committed_exit_pids.pop(key, None)

    for sid in [s for s, t in _sessions.items() if now - t > SESSION_TTL_SECONDS]:
        _drop_session_state(sid)

    # Sessions that departed without a beacon simply age out (no exit is
    # invented for them). Pending exits commit once the grace window passes
    # with no same-session pageview.
    for sid in [s for s, row in _pending_exits.items() if now - row["ts"] > EXIT_GRACE_SECONDS]:
        row = _pending_exits.pop(sid)
        _day["exits"] += 1
        key = ("before booking / other page" if not row.get("step")
               else FUNNEL_LABELS.get(row["step"], f"step {row['step']}"))
        _exit_steps[key] = _exit_steps.get(key, 0) + 1
        _recent.append(row)
        if row.get("pid"):
            _committed_exit_pids[(sid, row["pid"])] = now
        _drop_session_state(sid)


def _rollover_day_locked():
    today = _today()
    if _day.get("date") != today:
        _day.update(date=today, visits=0, bookings=0, exits=0)
        for i in range(len(_funnel)):
            _funnel[i] = 0
        _recent.clear()
        _sessions.clear()
        _session_steps.clear()
        _last_pageview.clear()
        _last_pid.clear()
        _last_exit_pid.clear()
        _counted_visits.clear()
        _pending_exits.clear()
        _committed_exit_pids.clear()
        _exit_steps.clear()
        _rate.clear()
        _booked_jobs.clear()


# ------------------------------------------------------------------ public API for your app

def record_booking(job_id: str | None = None):
    """
    The ONLY booking counter. Call inside your POST /api/jobs handler,
    right after a job is successfully saved:

        from live_feed import record_booking
        ...
        record_booking(job_id=str(job.id))

    Pass the job id when you have one: the same job is then counted
    once even if your endpoint retries or replays. The browser
    tracker never reports bookings, so there is no client-side
    double count.
    """
    with _lock:
        _prune_locked()
        _rollover_day_locked()          # roll over FIRST so the day's first
        if job_id:                      # booking isn't wiped by its own dedupe id
            if job_id in _booked_jobs:
                return
            _booked_jobs.add(job_id)
            if len(_booked_jobs) > BOOKING_DEDUPE_CAP:
                _booked_jobs.pop()   # bounded memory; a same-day retry after this is unlikely

        _day["bookings"] += 1
        _funnel[5] += 1
        _recent.append(_row("server", "booked", "New booking received"))
        _persist_locked()


# ------------------------------------------------------------------ routes

class TrackEvent(BaseModel):
    event: str
    sid: str
    pid: str | None = None
    path: str | None = None
    step: int | None = None
    dwell_ms: int | None = None
    ref: str | None = None


async def _track(ev: TrackEvent):
    # --- allowlist and bound every field (public endpoint) ---
    if ev.event not in EVENT_TYPES:
        raise HTTPException(status_code=400)
    sid = ev.sid or ""
    if not SID_RE.match(sid):
        raise HTTPException(status_code=400)
    pid = ev.pid or ""
    if pid and not SID_RE.match(pid):
        raise HTTPException(status_code=400)
    step = ev.step if ev.step in (1, 2, 3, 4) else None
    dwell = ev.dwell_ms if isinstance(ev.dwell_ms, int) and 0 <= ev.dwell_ms <= 86_400_000 else None
    label = ev.path if ev.path in PAGE_LABELS else "other"
    ref = (ev.ref or "")[:100] if ev.ref else None

    with _lock:
        _prune_locked()
        _rollover_day_locked()

        # per-session rate limit (sliding one-minute window)
        now = _now()
        win = _rate.get(sid)
        if win is None or now - win[0] >= 60:
            _rate[sid] = [now, 1]
        else:
            win[1] += 1
            if win[1] > RATE_LIMIT_PER_MINUTE:
                return {"ok": True}   # silently drop floods

        if ev.event == "pageview":
            # A pageview right after a pending exit means they clicked into
            # another page of the site, not off of it: retract the exit.
            _pending_exits.pop(sid, None)
            # Visit rule (independent of exit processing): one visit per
            # session, counted on its first pageview of the day. Internal
            # navigation — in any beacon order — never adds visits.
            if sid not in _counted_visits:
                _counted_visits.add(sid)
                _day["visits"] += 1
                _recent.append(_row(sid, "visit", label))
            _last_pageview[sid] = now
            _last_pid[sid] = pid
            _sessions[sid] = now

        elif ev.event == "ping":
            _sessions[sid] = now

        elif ev.event == "step" and step:
            _sessions[sid] = now
            reached_set = _session_steps.setdefault(sid, set())
            if step not in reached_set:
                reached_set.add(step)
                _funnel[step] += 1
                _recent.append(_row(sid, "step", FUNNEL_LABELS.get(step, f"step {step}"), step=step))

        elif ev.event == "exit":
            # Deterministic, no timing guesswork: every beacon carries the
            # page instance id (pid) it belongs to.
            #  - beacon's pid != latest pageview's pid: it belongs to an older
            #    page, and the visitor already opened a newer page — internal
            #    navigation, not a departure. (The newer pageview already
            #    retracted any pending exit; visits are unaffected.)
            #  - pid matches the latest pageview: the visitor left the site
            #    from the current page — a real (estimated) departure.
            if pid and _last_pid.get(sid) and pid != _last_pid[sid]:
                pass   # stale beacon from an older page — ignore entirely
            elif sid not in _pending_exits and pid != _last_exit_pid.get(sid):
                # Record as pending; a same-session pageview within the grace
                # window retracts it (handled in the pageview branch). Keep
                # the milestone dedupe state in case it IS retracted. Duplicate
                # beacons for the same page instance are ignored — including
                # replays of any exit whose departure already committed.
                if (sid, pid) not in _committed_exit_pids:
                    _last_exit_pid[sid] = pid
                    _pending_exits[sid] = _row(
                        sid, "exit", "Left the site (estimated)",
                        step=step, dwell_ms=dwell, pid=pid)
                    _sessions.pop(sid, None)   # no longer "online"

        _persist_locked()

    return {"ok": True}


async def _stats():
    with _lock:
        _prune_locked()
        _rollover_day_locked()

        now = _now()
        online = sum(1 for t in _sessions.values() if now - t < ONLINE_WINDOW_SECONDS)

        return {
            "online": online,
            "today": dict(_day),
            "funnel": [
                {"step": i, "label": FUNNEL_LABELS[i], "count": _funnel[i]}
                for i in range(1, 6)
            ],
            "drop_off": dict(_exit_steps),
            "recent": list(_recent)[-60:][::-1],   # newest first
        }


# ------------------------------------------------------------------ registration

def register_live_routes(app: FastAPI, settings, crew_auth) -> None:
    """
    Adds the live-station routes to the app.

    The dashboard itself lives INSIDE the owner's crew-app Dashboard
    tab (static/crew.html) — there is no standalone /live page and no
    link from the public site. /api/live/stats is OWNER-ONLY: it
    requires the owner's master code or an owner session token
    (X-Crew-Token). Crew members get 403; the public gets 401.
    """

    def owner_only(who: CrewIdentity = Depends(crew_auth)) -> CrewIdentity:
        if not who.is_owner:
            raise HTTPException(status_code=403, detail="Only the owner can view the live station.")
        return who

    @app.post("/api/track", include_in_schema=False)
    async def track(ev: TrackEvent):
        return await _track(ev)

    @app.get("/api/live/stats", include_in_schema=False)
    async def live_stats(_owner=Depends(owner_only)):
        return await _stats()
