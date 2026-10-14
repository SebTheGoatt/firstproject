# Property Dispatch

On-demand scheduling and route optimization for a property-service crew
(mowing, bin cleaning, gutters) based in Spring, TX.

```
 Customer ──► Intake form ──► FastAPI ──► Nominatim (geocode) ──► Supabase Postgres
                                                                      │
 8 PM nightly ──► freeze tomorrow ──► OSRM matrix ──► OR-Tools TSP ───┘ routes + route_stops
                                                                      │
 Crew phone ◄── /crew dashboard ◄── optimized stops + Apple/Google Maps deep links
     │
     └── "Mark complete" ──► next customer gets a Twilio SMS
```

## What's in here

| Path | Purpose |
|---|---|
| `supabase/migrations/…_init.sql` | Schema: `customers`, `jobs`, `routes`, `route_stops`, `save_route()` transaction, RLS |
| `app/main.py` | FastAPI app: pages, intake API, crew API, webhooks |
| `app/zones.py` | Geo-fenced service zones + mowing rates |
| `app/booking.py` | Runway quota + 8 PM time-window freeze rules |
| `app/geocode.py` | Nominatim geocoder (rate-limited to 1 req/s per its policy) |
| `app/routing/matrix.py` | OSRM driving distance/time matrix, haversine fallback |
| `app/routing/solver.py` | OR-Tools TSP with fixed start (base) and end point |
| `app/nightly.py` | The 8 PM job: load tomorrow → optimize → save route + freeze jobs |
| `app/deeplinks.py` | Google Maps / Apple Maps navigation URLs |
| `app/notify.py` | Twilio "crew is heading your way" text, never sent twice |
| `app/db.py` | Supabase repository + in-memory repository (demo/tests) |
| `static/index.html` | Customer intake form (mobile-first) |
| `static/crew.html` | Crew dispatch dashboard (mobile-first) |

## Website and installable app

The same server is both a public website and an installable app
(a Progressive Web App, so there's no App Store):

| URL | Who | What |
|---|---|---|
| `/` | Customers, search engines | Home page: services, service areas with mowing prices, next open day, how it works |
| `/book` | Customers | Booking form |
| `/crew` | Crew | Route dashboard (hidden from search engines via `robots.txt` and `noindex`) |

**Installing on a phone:**
- **iPhone (Safari):** Share → **Add to Home Screen**. The pages show this hint automatically.
- **Android (Chrome):** an **Install** button appears on the page, or use menu → **Install app**.

Customers who install from `/` get the booking app. Crew members who install from
`/crew` get a separate **Crew Route** app that opens straight to the dashboard.

**Offline (crew):** the service worker keeps the last route each phone loaded.
If the crew loses signal, the app still opens and shows the day's stops, with a
"No signal" banner; *Mark complete* asks them to retry once they're back in
coverage. Signing out deletes the saved route from the phone.

**Updates:** every deploy changes a version hash of the static files, so
installed apps pick up the new version on their next launch. You don't
need to reinstall.

The business name on every page comes from `BUSINESS_NAME`.

## How the rules work

**Freeze.** A service day locks at `FREEZE_HOUR` (default 20:00, America/Chicago)
on the day before. After 8 PM tonight, tomorrow can't be booked; the form's
date picker automatically starts at the earliest open day.

**Quota.** Each day accepts at most `DAILY_JOB_QUOTA` active jobs; the next
booking gets "That day is fully booked."

**Service zones.** `app/zones.py` defines geo-fenced bounding boxes, each with a
mowing rate. After geocoding, an address outside every zone is turned away; inside
one, the job stores its `zone_key` and (for mowing) the `quoted_price`. Boxes are
`(min_lng, min_lat, max_lng, max_lat)`, and the app refuses to start if a box is
inverted, out of range, or overlaps another. To change a zone, edit that file and redeploy.
The home page draws every zone on an interactive map (MapLibre + OpenFreeMap tiles:
free, no API key, commercial use allowed) with price pins, so a new or resized
zone shows up on the map automatically.

**Nightly run.** Loads tomorrow's `pending`/`scheduled` jobs, builds a driving
matrix from OSRM (falls back to straight-line × 1.3 if OSRM is down), solves
the TSP with OR-Tools (`PATH_CHEAPEST_ARC` + `GUIDED_LOCAL_SEARCH`) starting at
the base and ending at `END_LAT/END_LNG` (defaults to the base), computes ETAs
from `CREW_START_TIME` plus drive and on-site time (mowing 45 min, bins 15,
gutters 60), then saves the route and marks jobs `scheduled` in one transaction.
Re-running it for the same day is safe.

**Completion → SMS.** When the crew taps *Mark complete*, the stop and job
are marked done and the **next unfinished stop** on the route gets a text.
`route_stops.notified_at` is claimed atomically, so retries, double-taps, and
webhook + button firing together never send a duplicate.

## Run it locally (no database needed)

```bash
cd property-dispatch
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                                     # 46 tests

export DATA_BACKEND=memory CREW_ACCESS_TOKEN=crew CRON_SECRET=cron \
       GEOCODER_USER_AGENT="property-dispatch/1.0 (you@yourbusiness.com)"
uvicorn app.main:get_app --factory --reload
```

- Book a few jobs for tomorrow at http://localhost:8000/
- Build the route: `curl -X POST localhost:8000/internal/nightly -H "X-Cron-Secret: cron"`
- Open http://localhost:8000/crew, enter `crew`, and pick tomorrow's date

Without Twilio credentials the "next customer" text is logged instead of sent.

## Deploy to production

### 1. Supabase (database)
1. Create a project at [supabase.com](https://supabase.com).
2. **SQL Editor → New query**: paste the whole contents of `supabase/setup_all.sql`
   (all migrations combined, in order) and click **Run** once.
   (Or with the CLI: `supabase link --project-ref <ref> && supabase db push`.)
3. **Settings → API Keys**: copy the **secret** key (`sb_secret_…`), and copy the **Project URL**
   from the **Connect** button. The secret key bypasses RLS, so keep it on the server and
   never put it in the browser. It goes in `SUPABASE_SERVICE_ROLE_KEY`. If the app logs
   "Invalid API key", use the legacy `service_role` key from the same page instead.

### 2. Twilio (SMS)
1. Buy a local (281/832/346) number in the Twilio console.
2. **Register for A2P 10DLC** (Messaging → Regulatory Compliance). US carriers
   block unregistered business texting from 10-digit numbers. Approval usually
   takes a few days, so start this first.
3. Copy the Account SID, Auth Token, and the number in E.164 form (`+12815550000`).

### 3. Render (web app + 8 PM cron), using `render.yaml` at the repo root
1. Push this repo to GitHub.
2. Render → **New → Blueprint** → select the repo. It creates:
   - `property-dispatch`: the web service (Docker)
   - `property-dispatch-nightly`: the cron job running `python -m app.nightly`
3. Fill in the values Render asks for: `BUSINESS_NAME`, `SUPABASE_URL` and
   `SUPABASE_SERVICE_ROLE_KEY` (asked once per service), `GEOCODER_USER_AGENT` (must
   include a real contact email, because Nominatim returns 403 for placeholders), and
   the three `TWILIO_*` values (leave blank to launch without texting).
   `CREW_ACCESS_TOKEN`, `WEBHOOK_SECRET`, and `CRON_SECRET` are generated for you;
   copy `CREW_ACCESS_TOKEN` out of the dashboard for the crew.
4. On the crew's phones, open `https://<your-app>.onrender.com/crew` → enter the code →
   Share → **Add to Home Screen**.

**Why the cron runs hourly 01:00-04:00 UTC:** cron schedules are in UTC, and 8 PM
Central is 01:00 UTC during daylight time but 02:00 UTC in winter. Each run exits
before 8 PM local, builds tomorrow's route at or after it, and does nothing if the
route already exists. The first run after 8 PM does the work; the later ones catch
up if that run was missed (host outage or maintenance). The last run is 11 PM
Central at the latest, so it never crosses midnight.

The app refuses to start in `supabase` mode if any of the three secrets is
empty or still `change-me`.

### Alternative scheduler: Supabase pg_cron
If you'd rather not run a cron service, enable the `pg_cron` and `pg_net`
extensions and have Postgres call the HTTP trigger:

```sql
select cron.schedule('nightly-route-cdt', '0 1 * * *', $$
  select net.http_post(
    url     := 'https://<your-app>/internal/nightly',
    headers := '{"X-Cron-Secret": "<CRON_SECRET>"}'::jsonb)
$$);
-- plus an identical '0 2 * * *' job named 'nightly-route-cst'
```

The HTTP endpoint doesn't do the 8 PM check (it always builds tomorrow), so
during daylight time disable the 02:00 job, and in winter disable the 01:00 job.
Or simply use the Render cron above, which handles daylight time on its own.

### Optional: completion webhook from other systems
`POST /webhooks/job-completed` with header `X-Webhook-Secret` accepts any of:

```json
{ "stop_id": "…" }
{ "job_id": "…" }
{ "type": "UPDATE", "table": "jobs", "record": { "id": "…", "status": "completed" } }
```

The third shape is what a **Supabase Database Webhook** sends. Point one at
this URL (on `UPDATE` of `jobs`, with the secret header), and anyone who marks a
job `completed` directly in the Supabase table editor also triggers the text.
Updates that aren't completions are ignored.

## API reference

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/booking-info` | none | earliest/latest bookable dates, services |
| POST | `/api/jobs` | none | `409` frozen/full · `422` bad input/unknown address · `503` geocoder down |
| GET | `/api/routes/{YYYY-MM-DD}` | `X-Crew-Token` | stops in order with ETAs and map URLs |
| POST | `/api/stops/{id}/complete` | `X-Crew-Token` | idempotent; returns notification result |
| POST | `/webhooks/job-completed` | `X-Webhook-Secret` | see above |
| POST | `/internal/nightly?day=` | `X-Cron-Secret` | HTTP version of the nightly run |
| GET | `/healthz` | none | |

## Known limits and upgrade paths

- **Geocoding accuracy.** Nominatim sometimes knows only the street, not the house number,
  and returns the street's midpoint (the form shows the matched address so the customer can
  spot this). For rooftop accuracy, swap `NominatimGeocoder` for Mapbox, Google, or the
  free U.S. Census geocoder; the interface is one `geocode(address) -> GeoPoint` method.
- **OSRM public server** is a free demo with no SLA and a 100-point table limit.
  Self-host OSRM with the Texas extract, or point `OSRM_URL` at a paid provider, if
  you outgrow it. Either way, the haversine fallback keeps the nightly run working.
- **Map links.** Google Maps gets a full-route link (split into chained parts of up to
  9 waypoints, the app's limit). Apple's URL scheme supports only one destination, so
  Apple Maps uses per-stop buttons, which suits turn-by-turn work stop to stop anyway.
- **One crew.** The solver is single-vehicle. Adding trucks means passing
  `num_vehicles > 1` to `RoutingIndexManager` plus a `crew_id` on `routes`.
- **Intake abuse.** The booking form is public; put Cloudflare Turnstile or a rate
  limiter in front of `POST /api/jobs` before advertising it widely.
