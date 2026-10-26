"""Community: sponsored mows for neighbors in need, and where the giving goes. Nothing is free: a sponsored mow is
paid in full by a sponsor (the "Sponsor a neighbor's mow" add-on on their own booking) and is only scheduled against
a paid sponsorship that hasn't been used yet.

    GET  /community                              public: how giving works, real totals, nominate a neighbor
    POST /api/nominations                        public: nominate a neighbor (throttled; private to the owner)
    GET  /api/owner/community                    owner: nominations, sponsorships waiting, totals
    POST /api/owner/nominations/{id}/schedule    owner: book the nominee's mow on their area day (uses a sponsorship)
    POST /api/owner/nominations/{id}/decline     owner: close a nomination
    GET  /owner/community                        the owner's page (static/community-owner.html)

Nominations hold a neighbor's name, address and story, so they are never shown publicly, and the owner calls the
neighbor before scheduling: the mow and the visit texts happen only with their OK. Needs
supabase/migrations/20261029000000_community.sql; until it's run the endpoints answer 503 with that instruction.
"""

import html
import logging
import time
from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .booking import BookingRejected, check_area_day, forget_counts, local_now
from .charity import causes
from .config import Settings, site_url
from .local_pages import dollars, layout, with_share_tags
from .models import Service, normalize_us_phone
from .pricing import ADD_ONS, YIELD_BASE, mow_minutes
from .visit_routes import Throttle, new_access_code
from .zones import SERVICE_ZONES, WEEKDAY_NAMES, find_zone, short_name, zone_by_key

log = logging.getLogger(__name__)
esc = html.escape
NEEDS_UPDATE = ("Sponsored mows need the database update: run supabase/migrations/20261029000000_community.sql "
                "in the Supabase SQL editor.")
SPONSOR = ADD_ONS["sponsor_mow"]


class Nomination(BaseModel):
    zone_key: str = Field(max_length=40)
    nominee_name: str = Field(min_length=1, max_length=120)
    nominee_address: str = Field(min_length=5, max_length=200)
    nominee_phone: str | None = Field(default=None, max_length=30)
    reason: str = Field(min_length=1, max_length=600)
    nominator_name: str = Field(min_length=1, max_length=120)
    nominator_contact: str = Field(min_length=3, max_length=120)
    website: str = ""              # honeypot: people never fill it in


class Schedule(BaseModel):
    day: date
    consent: bool = False          # the owner called the neighbor: they said yes to the mow and the visit texts


def community_html(settings: Settings, version: str, totals: dict | None) -> str:
    areas = "".join(f'<option value="{z.key}">{esc(short_name(z))} · {WEEKDAY_NAMES[z.service_weekday]}s</option>'
                    for z in sorted(SERVICE_ZONES, key=lambda z: z.service_weekday))
    cause_rows = "".join(f'<li><strong>{esc(c["name"])}</strong><span>{esc(c["blurb"])}</span></li>' for c in causes(settings))
    done = str(totals["sponsored_done"]) if totals else "0"
    given = dollars_cents(totals["given"]) if totals else "$0"
    body = f"""
    <section class="sp-hero" aria-labelledby="community-title">
      <div class="site-wrap sp-hero-grid">
        <div class="sp-hero-copy">
          <p class="eyebrow">Community · Veteran-owned · Spring, TX</p>
          <h1 id="community-title">Mow it <span>forward.</span></h1>
          <p class="lede">Every paid mow gives to a local cause. And when a neighbor can't mow their own lawn (a senior,
            a disabled neighbor, a veteran, a family going through a hard stretch), a sponsor pays for their mow and our
            crew does it on that area's day.</p>
          <div class="hero-actions">
            <a class="btn btn-lg sp-btn-fresh" href="/book?addon=sponsor_mow">Sponsor a mow</a>
            <a class="btn btn-lg sp-btn-line" href="#nominate">Nominate a neighbor</a>
          </div>
        </div>
        <div class="sp-card cm-totals" aria-label="Given so far">
          <p class="sp-kicker">Given so far · from our books</p>
          <div class="cm-figs">
            <div><strong>{done}</strong><span>sponsored mows done</span></div>
            <div><strong>{given}</strong><span>to local causes</span></div>
          </div>
          <p class="hint">Real totals only, counted from paid visits. They grow with every mow.</p>
        </div>
      </div>
    </section>

    <section class="section" aria-labelledby="how-title">
      <div class="site-wrap">
        <h2 id="how-title">Three ways every mow gives back</h2>
        <ol class="sp-pillars cm-ways">
          <li><span class="sp-num">01</span><p class="sp-kicker">Your mow gives</p><h3>Pick a cause</h3>
            <p>Part of every paid mow goes to the cause you pick when you book. Your receipt shows the dollars.</p></li>
          <li><span class="sp-num">02</span><p class="sp-kicker">Round up</p><h3>Round up your total</h3>
            <p>When you pay, round your total up to the next $5. Every cent of the difference goes to your cause.</p></li>
          <li><span class="sp-num">03</span><p class="sp-kicker">Sponsor a neighbor</p><h3>Pay for their mow</h3>
            <p>Add a sponsored mow ({dollars(SPONSOR["price"])} plus tax) to your booking and we mow for a nominated
              neighbor on their area's day. We never share who or where.</p></li>
        </ol>
      </div>
    </section>

    <section class="section" aria-labelledby="causes-title">
      <div class="site-wrap cm-split">
        <div>
          <h2 id="causes-title">The causes</h2>
          <ul class="cm-causes">{cause_rows}</ul>
          <p class="hint">Every dollar is logged per visit and passed on to the named organization.</p>
        </div>
        <form class="card cm-form" id="nominate" novalidate aria-labelledby="nominate-title">
          <h2 id="nominate-title">Nominate a neighbor</h2>
          <p class="hint">Someone in our areas who can't mow right now. We call them first and only mow with their OK.
            Nominations are private: we never post names or addresses.</p>
          <div class="alert alert-error" id="cm-err" role="alert" hidden></div>
          <div class="alert alert-ok" id="cm-ok" role="status" hidden></div>
          <label for="cm-area">Their area</label>
          <select id="cm-area" required>{areas}</select>
          <label for="cm-name">Their name</label>
          <input id="cm-name" type="text" required maxlength="120" autocomplete="off">
          <label for="cm-address">Their address</label>
          <input id="cm-address" type="text" required maxlength="200" autocomplete="off">
          <label for="cm-phone">Their phone, if you know it <span class="optional">(optional)</span></label>
          <input id="cm-phone" type="tel" maxlength="30" autocomplete="off">
          <label for="cm-reason">Why them? A sentence is plenty.</label>
          <textarea id="cm-reason" required maxlength="600" rows="3"></textarea>
          <label for="cm-you">Your name</label>
          <input id="cm-you" type="text" required maxlength="120" autocomplete="name">
          <label for="cm-contact">Your phone or email, so we can follow up</label>
          <input id="cm-contact" type="text" required maxlength="120" autocomplete="email">
          <input id="cm-website" type="text" class="cm-hp" tabindex="-1" autocomplete="off" aria-hidden="true">
          <button class="btn btn-primary btn-lg btn-block" type="submit">Send nomination</button>
        </form>
      </div>
    </section>
    <script>
      document.getElementById("nominate").addEventListener("submit", async (e) => {{
        e.preventDefault();
        const $ = (id) => document.getElementById(id), err = $("cm-err"), ok = $("cm-ok");
        err.hidden = ok.hidden = true;
        const body = {{ zone_key: $("cm-area").value, nominee_name: $("cm-name").value.trim(),
          nominee_address: $("cm-address").value.trim(), nominee_phone: $("cm-phone").value.trim() || null,
          reason: $("cm-reason").value.trim(), nominator_name: $("cm-you").value.trim(),
          nominator_contact: $("cm-contact").value.trim(), website: $("cm-website").value }};
        if (!body.nominee_name || body.nominee_address.length < 5 || !body.reason || !body.nominator_name || body.nominator_contact.length < 3) {{
          err.textContent = "Please fill in every box except their phone."; err.hidden = false; return;
        }}
        const btn = e.target.querySelector("button"); btn.disabled = true;
        try {{
          const res = await fetch("/api/nominations", {{ method: "POST", headers: {{ "Content-Type": "application/json" }}, body: JSON.stringify(body) }});
          const out = await res.json().catch(() => ({{}}));
          if (!res.ok) throw new Error(out.detail || "That didn't go through. Please try again.");
          e.target.reset(); ok.textContent = "Thank you. We'll reach out to them, and to you if we have questions."; ok.hidden = false;
        }} catch (x) {{ err.textContent = x.message; err.hidden = false; }}
        btn.disabled = false;
      }});
    </script>"""
    return layout(settings, version, title=f"Community: Mow It Forward | {settings.business_name}",
                  description=("Every paid mow gives to a local cause, customers can round up, and sponsors pay for "
                               "mows for neighbors in need. Real totals, from our books."),
                  body=body, page="community")


def dollars_cents(amount: float) -> str:
    return f"${amount:,.0f}" if float(amount).is_integer() else f"${amount:,.2f}"


def register_community(app: FastAPI, settings: Settings, owner, page, version: str = "") -> None:
    throttle = Throttle(limit=5, window_s=3600)
    cached: dict = {"at": 0.0, "totals": None}

    def repo():
        return app.state.repo

    def table(call):
        try:
            return call()
        except HTTPException:
            raise
        except Exception as exc:                       # table or enum missing until the migration runs
            log.error("community data unavailable: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail=NEEDS_UPDATE)

    def totals() -> dict | None:
        if time.monotonic() - cached["at"] > 300:      # public page: five-minute totals, never a failing page
            try:
                cached["totals"] = repo().community_totals()
            except Exception:
                log.warning("Community totals unavailable (run the 20261029 database update)")
            cached["at"] = time.monotonic()
        return cached["totals"]

    @app.get("/community", include_in_schema=False)
    def community(request: Request):
        return HTMLResponse(with_share_tags(community_html(settings, version, totals()), site_url(settings, request), "/community"),
                            headers={"Cache-Control": "no-cache"})

    @app.post("/api/nominations", status_code=201)
    def nominate(body: Nomination, request: Request):
        if body.website:                                # a bot filled the hidden box: say thanks, keep nothing
            return {"ok": True}
        if not throttle.allow(request.client.host if request.client else "unknown"):
            raise HTTPException(status_code=429, detail="Too many nominations from here. Please try again later.")
        if zone_by_key(body.zone_key) is None:
            raise HTTPException(status_code=422, detail="Pick one of our areas.")
        fields = body.model_dump(exclude={"website"})
        fields = {k: (v.strip() if isinstance(v, str) else v) for k, v in fields.items()}
        table(lambda: repo().add_nomination(fields))
        return {"ok": True}

    @app.get("/api/owner/community", dependencies=[Depends(owner)])
    def owner_community():
        s = table(lambda: repo().sponsorships())
        return {"nominations": table(lambda: repo().list_nominations()), "sponsorships": {**s, "waiting": max(0, s["paid"] - s["used"])},
                "totals": table(lambda: repo().community_totals()), "price": float(SPONSOR["price"]),
                "areas": [{"key": z.key, "name": short_name(z), "weekday": z.service_weekday} for z in SERVICE_ZONES]}

    @app.post("/api/owner/nominations/{nomination_id}/decline", dependencies=[Depends(owner)])
    def decline(nomination_id: str):
        if not table(lambda: repo().set_nomination(nomination_id, "declined")):
            raise HTTPException(status_code=404, detail="No such nomination.")
        return {"status": "declined"}

    @app.post("/api/owner/nominations/{nomination_id}/schedule", dependencies=[Depends(owner)])
    def schedule(nomination_id: str, body: Schedule):
        n = table(lambda: repo().get_nomination(nomination_id))
        if n is None:
            raise HTTPException(status_code=404, detail="No such nomination.")
        if n["status"] != "new":
            raise HTTPException(status_code=409, detail="That nomination is already scheduled or closed.")
        if not body.consent:
            raise HTTPException(status_code=422, detail=("Call them first: tick the box once they've said yes to the "
                                                         "mow and to texts about the visit."))
        if not n.get("nominee_phone"):
            raise HTTPException(status_code=422, detail="Add their phone number first: the crew texts before arriving.")
        s = table(lambda: repo().sponsorships())
        if s["paid"] - s["used"] <= 0:
            raise HTTPException(status_code=409, detail=("No paid sponsorship is waiting. A sponsored mow is booked "
                                                         "once someone sponsors one."))
        if body.day <= local_now(settings).date():
            raise HTTPException(status_code=422, detail="Pick a day after today.")
        try:
            geo = app.state.geocoder.geocode(n["nominee_address"])
        except Exception:
            raise HTTPException(status_code=503, detail="Couldn't look up that address right now. Try again.")
        zone = find_zone(geo.lat, geo.lng) if geo else None
        if zone is None:
            raise HTTPException(status_code=422, detail="That address isn't in one of our areas.")
        try:
            check_area_day(body.day, zone)
        except BookingRejected as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        try:
            phone = normalize_us_phone(n["nominee_phone"])
        except ValueError:
            raise HTTPException(status_code=422, detail="That phone number doesn't look right.")
        job = repo().create_job(
            name=n["nominee_name"], phone=phone, address=n["nominee_address"], geo=geo, service=Service.MOWING,
            scheduled_date=body.day, service_minutes=mow_minutes(zone.yard_sqft), zone_key=zone.key,
            quoted_price=float(YIELD_BASE), payment_method="cash", access_code=new_access_code(), amount_due=0.0,
            subtotal=0.0, tax_rate=0.0, tax_amount=0.0, add_ons=[], add_on_total=0.0)
        repo().mark_paid(job["id"], method="sponsored", amount_paid=0.0, donation=0.0)   # the sponsor already paid
        repo().set_nomination(nomination_id, "scheduled", job["id"])
        forget_counts(repo())
        return {"status": "scheduled", "job_id": job["id"], "day": body.day.isoformat(), "area": short_name(zone)}

    @app.get("/owner/community", include_in_schema=False)
    def community_page():
        resp = page("community-owner.html")
        resp.headers["X-Robots-Tag"] = "noindex"
        return resp
