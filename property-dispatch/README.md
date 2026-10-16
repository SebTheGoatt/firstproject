# Property Dispatch

On-demand scheduling and route optimization for a property-service crew
(mowing, bin cleaning, gutters) based in Spring, TX.

```
 Customer ──► Intake form ──► FastAPI ──► Nominatim (geocode) ──► Supabase Postgres
                                                                      │
 5 PM daily  ──► freeze tomorrow ──► OSRM matrix ──► OR-Tools TSP ───┘ routes + route_stops
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
| `app/booking.py` | Runway quota + 5 PM time-window freeze rules |
| `app/geocode.py` | Nominatim geocoder (rate-limited to 1 req/s per its policy) |
| `app/routing/matrix.py` | OSRM driving distance/time matrix, haversine fallback |
| `app/routing/solver.py` | OR-Tools TSP with fixed start (base) and end point |
| `app/nightly.py` | The 5 PM job: load tomorrow → optimize → save route + freeze jobs |
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

The business name on every page comes from `BUSINESS_NAME` (Semper Green Lawn Care). The logo
lives in `static/icons/` (header `logo-64.png`, app icons, `favicon.ico`, and `social.jpg`, the
picture shown when the site is shared in a text or on social media). Brand colors: forest green
`#0B3D2E`, fresh green `#4CAF50`, sunlit green `#A7D129`.

## Address entry: instant area check + optional Google dropdown

As soon as a customer enters an address, the booking form checks it (`POST /api/check-address`,
which saves nothing) and shows "Good news: you're in our Klein area. Mowing is $55.00 per
visit", or the out-of-area message. The check is by **map coordinates against the service
zones**, never by city name: Google and the Postal Service call most Klein addresses
"Spring", and "Spring" also covers Old Town Spring, which isn't served.

**Optional Google address dropdown.** Set `GOOGLE_MAPS_BROWSER_KEY` and the address box
becomes Google's autocomplete (`PlaceAutocompleteElement`, Places API (New)). The older
`google.maps.places.Autocomplete` isn't available to Google accounts created after
March 1, 2025.
1. Google Cloud Console: create a project, add billing, enable **Maps JavaScript API** and
   **Places API (New)**.
2. Credentials → Create API key → restrict it to **Websites** with your address
   (`https://property-dispatch.onrender.com/*`) and to those two APIs.
3. Put it in `GOOGLE_MAPS_BROWSER_KEY` on Render.

If the key is missing, wrong or blocked, the form quietly falls back to the plain address
box. Google's coordinates are only a hint: the server uses them when its own lookups find
just the street (and Google's point is within 1.5 km of it) or nothing at all (brand-new
subdivisions), and never outside Texas.

## Owner dashboard, customer access codes, before/after photos

**Owner dashboard** (`/crew` → Owner sign-in → **Dashboard**, the owner's first tab):
- a 7-day strip with bookings per day against `DAILY_JOB_QUOTA` and expected revenue;
- the selected day's totals: bookings, expected, collected, donations, still owed;
- route status, with **Build route now** / **Rebuild route** (refused once any stop on
  that day is finished, so the crew's route never changes under them);
- every booking as soon as it's made (before the route exists), with status, payment,
  phone, and the customer's access code to copy.

**Customer access codes.** Every booking gets an 8-character code such as `K7MX-3QPA`
(no look-alike characters). It's shown on the booking confirmation and texted with a link
to `/visit/{code}`, where the customer sees their status (booked → route planned → on the
way → done), arrival window, the crew member who did the job, payment (with a pay link for
card customers), and their **before and after photos**. Lookups are rate-limited per IP.

**Before/after photos.** On each stop the crew taps **Before photo** on arrival; when
finishing, the **after photo** goes to the customer's visit page. These photos are private
to that customer's code (`/media/visit/{id}?code=…`). A crew member can tick "Also show it
on my public profile" to add the after photo to their public portfolio.

## Pricing and Texas sales tax

**Mowing price (the calculator).** Subtotal = **$35 base service fee** (once per visit, the same in
every area) **+ lawn square feet × the rate the customer picks**; sales tax is added at checkout.
The customer must enter a real lawn size (whole square feet, 100 to 87,120) and must pick a rate;
nothing is preselected and no size is ever guessed. The tiers are prices only: the work is the same.

| Rate | Per sq ft | Share given to charity | 5,000 sq ft before tax |
|---|---|---|---|
| Standard | $0.009 | 2% of the price | $80.00 |
| Plus | $0.010 | 7% | $85.00 |
| Premium | $0.012 | 12% | $95.00 |

The booking page shows a live estimate (base fee, lawn size, rate, lawn size charge, subtotal,
"Sales tax: Calculated at checkout") that updates as the customer types. Once the address is known,
the server prices the order with that service area's tax rate and shows the itemized total; the
confirmation, pay page and Stripe Checkout all use the server's numbers, so the amount charged
always equals the total shown. The browser's numbers are never trusted. Rates are `PACKAGES` in
`app/pricing.py` (keys `standard`, `supporter`, `hero` stay the same on stored bookings), the $35
is `FLAT_FEE` in `app/zones.py`, and the size limits are `MIN_SQFT`/`MAX_SQFT`.

**Add-ons (with a mow only).** Every booking is a mowing visit; customers can add:

| Add-on | Price | Extra time on site | When |
|---|---|---|---|
| Bin cleaning | $15 | 15 min | all year |
| Gutter cleaning | $15 | 30 min | all year |
| Holiday lighting | **Custom quote: free, never charged online** | 10 min look | service dates Oct 15 – Jan 15 |

Add-ons are part of the order: they're taxed and the rate tier's charity share applies to
the whole order. They're itemized on the order summary, pay page, visit page and Stripe receipt,
the crew's stop card reads e.g. "Mowing + Gutter cleaning", and the route allows the extra time.
Prices, times and the season live in `ADD_ONS` in `app/pricing.py`. Bin- or gutter-only bookings
are refused; any made before add-ons existed are still priced on site by the crew.
Holiday lighting is a quote request: ticking it adds "Holiday lighting quote" to the booking (the
crew sees it on the stop) at no charge, and it never appears on the Stripe receipt. The home page's
"Get a Quote", "Add Bin Cleaning" and "Add Gutter Cleaning" buttons open the booking page with that
add-on already ticked (`/book?addon=…`). An add-on can only be on an order once.

- **Lawn size at booking.** Customers pick Small (~2,500 sq ft), Medium (~4,500), Large
  (~8,000) or X-Large (~12,500), or type an exact size. They see the price, tax and total
  before they book. Skipping the size books at the flat fee.
- **Crew confirms on site.** The finish panel shows the booked size; if the lawn is
  bigger or smaller, the crew types the real size and the price, tax, total and the
  cash amount update live. The price can only change while the job is unpaid.
- **Bin cleaning and gutters** are priced on site: the crew enters the price before tax
  when finishing, and tax is added the same way.
- **Texas sales tax** is added to all three services at 8.25% (6.25% state + up to 2%
  local), set per zone in `app/zones.py` (`tax_rate`). Donations are never taxed.
  Customers see "price + Texas sales tax = total" on the booking page, confirmation,
  visit page, pay page and Stripe receipt. The owner dashboard shows **Sales tax
  collected** for each day so it's easy to set aside for your Comptroller filing.
  - Lawn mowing is a taxable service in Texas
    ([Comptroller Pub. 94-112](https://www.comptroller.texas.gov/taxes/publications/94-112.php)).
    Gutter and bin cleaning are most likely taxable as building/real-property services;
    confirm both with a tax professional.
  - Local rates vary by address. Check each area's exact rate with the Comptroller's
    [sales tax rate locator](https://gis.cpa.texas.gov/search/) and update `tax_rate`
    if it's lower than 8.25%.
  - Bookings made before this change keep their original price with no tax added.

## Pay your way (cash or card) and donations

**Where donations go.** Package giving (above) and every voluntary donation are each split **33% Veterans of Foreign Wars, 33% NICU
(neonatal intensive care) families, 34% at-risk youth programs** (`app/charity.py`). The split
is worked out to the cent when the donation is paid (leftover cents go to the largest
remainders, so the shares always add up exactly) and saved on the job, so the ledger never
changes later. Customers see the split on the booking page, live on the pay page ("Where your
$10.00 goes"), as separate lines on their Stripe receipt, and on their visit page. The crew's
finish screen previews the split when cash is over the total, and the owner dashboard shows
**Package giving** and **To pass on** per cause for each day (package giving + donations, paid jobs only).

- Rename the causes to the specific organizations you give to (no code change):
  `CHARITY_VFW_NAME`, `CHARITY_NICU_NAME`, `CHARITY_YOUTH_NAME` in Render's environment.
- Donations are collected by the business and passed on, so they aren't tax-deductible for
  the customer (the pay page says so). Keep records of each payout to match the ledger, and
  ask the VFW post / hospital before using their name publicly.
- Donations recorded before this feature have no split (they went to the business).

At booking, customers choose **Cash to the crew** or **Card in the app**.

- **Cash:** when finishing a job the crew enters the cash they were handed.
  Anything over the price is recorded as a donation.
- **Card:** customers get a private link (`/pay/{token}`) on their booking confirmation,
  and by text when the job is done. The page shows the price, offers optional donation
  buttons ("No tip necessary. Donations are always welcome. We're a veteran-owned
  business."), and sends them to **Stripe Checkout** to pay. We never see card numbers.
  Stripe's signed webhook marks the job paid.
- **Quoted services** (bin cleaning, gutters): the crew enters the final price when
  finishing; card customers are then texted their pay link.

**Turning on card payments** (until then the card option stays hidden):
1. Create a Stripe account and finish its business verification.
2. Stripe → Developers → API keys: copy the **Secret key** into `STRIPE_SECRET_KEY`.
3. Stripe → Developers → Webhooks → **Add endpoint**: URL `https://<your-app>/webhooks/stripe`,
   events `checkout.session.completed` and `checkout.session.async_payment_succeeded`.
   Copy its **Signing secret** into `STRIPE_WEBHOOK_SECRET`.
4. Set `PUBLIC_BASE_URL` to your site's address.

## Visit notifications (optional)

On their visit page, customers can tap **Get updates on this phone**. They then get a notification when
the crew is on the way and when the visit is done, in their language, and nothing else. A phone is saved
against that one booking (`push_subscriptions`, migration 20261025) and forgotten if the customer turns
notifications off. iPhones only allow this from the Home Screen app, and the page says so.

The crew app has an **On my way** button on every open stop (it also happens automatically for the next
stop when you finish a job). It sends app/browser notifications only, never a text, and it marks the visit
page "on the way". A visit page that is open also checks for news every minute, so customers who never
turned on notifications still see "on the way" and "done" appear by themselves.

To turn it on: open `/push-setup` on your site, tap **Make my keys** (they are made in your browser and
never leave it), put them in Render as `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` (optionally
`VAPID_SUBJECT`, a `mailto:` address; it defaults to `PUBLIC_BASE_URL`), and deploy. Without the keys
the button simply doesn't appear. There is deliberately no public "send a push" endpoint.

## En español (Spanish)

The customer pages (home, booking, pay, visit) are available in Spanish. `static/i18n.js` translates
the page in the browser and picks the language in this order: `?lang=es` in the link, the visitor's
last choice, then their phone or browser language. A **Español / English** button in the header
switches at any time. Dates, error messages from the server and prices are shown in Spanish too.

The language is saved on the booking (`jobs.lang`, migration 20261024), so the booking confirmation,
"crew is on the way" and payment-link texts go out in the customer's language. The crew app stays
in English. To add or fix a phrase, edit the `ES` dictionary (exact text) or `PATTERNS` (text with
names, dates or amounts) in `static/i18n.js`. A native speaker should review the wording before launch.

## Crew app: personal sign-in, profiles, portfolios

- **Sign-in:** `/crew` shows "Who's working today?" with each crew member's photo. They tap
  themselves and enter their personal code. Codes are stored only as salted hashes, and
  repeated wrong guesses are blocked for 15 minutes.
- **Owner:** "Owner sign-in" uses `CREW_ACCESS_TOKEN` (the master code). The owner's
  **Crew** tab adds people, issues new codes, and deactivates anyone who leaves (which
  signs them out everywhere). Changing `CREW_ACCESS_TOKEN` signs every phone out.
- **Each crew member gets** a personal header in their own color, their stats (jobs this
  week, all-time, work photos), today's route, **My profile** (photo, title, service branch,
  years, bio, specialties, color) and **My work** (portfolio photos, including one taken
  when finishing a job). Photos are resized on the phone before upload.
- **Public pages:** `/team` and `/team/{name}` show the crew's profiles and work. The home
  page shows a "Meet the crew" section once profiles exist. The "on the way" text names the
  crew member: "Hi Maria, this is Sam from …".

## How the rules work

**Freeze.** A service day locks at `FREEZE_HOUR` (default 17:00, close of business,
America/Chicago) on the day before. After 5 PM today, tomorrow can't be booked; the form's
date picker automatically starts at the earliest open day.

**Quota.** Each day accepts at most `DAILY_JOB_QUOTA` active jobs; the next
booking gets "That day is fully booked."

**Service zones.** `app/zones.py` defines geo-fenced bounding boxes, each with a
flat mowing fee and a sales tax rate. Colony Ridge (Liberty County, east of Plum Grove) has its own zone. A zone can have extra boxes: Plum Grove is
served from the Cleveland hub this way. After geocoding, an address outside every zone is turned away; inside
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
pytest

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
4. **Already set up (through 20261018)?** Open `supabase/upgrade_2026-10_packages.sql`, copy **all of its
   text** (not the file name), paste it into a new SQL Editor query and click **Run**. It adds
   migrations 20261019 to 20261024 at once, is safe to run twice, and ends with a check that lists 15 rows.
5. Otherwise, run only the migrations you haven't run yet, once each and in order:
   open each new file in `supabase/migrations/` (for example
   `20261019000000_access_codes_and_job_photos.sql`, then
   `20261020000000_pricing_and_sales_tax.sql`, then
   `20261021000000_rate_choice_and_donation_split.sql`, then
   `20261022000000_packages_and_charity_giving.sql`), paste it into the SQL Editor, and click **Run**.

### 2. Twilio (SMS)
1. Buy a local (281/832/346) number in the Twilio console.
2. **Register for A2P 10DLC** (Messaging → Regulatory Compliance). US carriers
   block unregistered business texting from 10-digit numbers. Approval usually
   takes a few days, so start this first.
3. Copy the Account SID, Auth Token, and the number in E.164 form (`+12815550000`).

### 3. Render (web app + 5 PM cron), using `render.yaml` at the repo root
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

**Why the cron runs hourly 22:00-02:00 UTC:** cron schedules are in UTC, and 5 PM
Central is 22:00 UTC during daylight time but 23:00 UTC in winter. Each run exits
before 5 PM local, builds tomorrow's route at or after it, and does nothing if the
route already exists. The first run after 5 PM does the work; the later ones catch
up if that run was missed (host outage or maintenance). The last run is 9 PM
Central at the latest, so it never crosses midnight. The first stop is planned for
`CREW_START_TIME` (default 07:00). Texas has no statewide lawn-hours law; cities and
HOAs set noise rules, so adjust it if a neighborhood requires a later start.

**After changing the schedule in `render.yaml`:** a Blueprint only re-reads the file
when it syncs. In Render open the Blueprint and click **Manual sync** (or turn on
auto-sync), then check the cron job's schedule shows `0 22,23,0,1,2 * * *`.

The app refuses to start in `supabase` mode if any of the three secrets is
empty or still `change-me`.

### Alternative scheduler: Supabase pg_cron
If you'd rather not run a cron service, enable the `pg_cron` and `pg_net`
extensions and have Postgres call the HTTP trigger:

```sql
select cron.schedule('route-build-cdt', '0 22 * * *', $$
  select net.http_post(
    url     := 'https://<your-app>/internal/nightly',
    headers := '{"X-Cron-Secret": "<CRON_SECRET>"}'::jsonb)
$$);
-- plus an identical '0 23 * * *' job named 'route-build-cst'
```

The HTTP endpoint doesn't do the 5 PM check (it always builds tomorrow), so
during daylight time disable the 23:00 job, and in winter disable the 22:00 job.
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
| POST | `/api/quote` | none | price, tax and total for an address, service, lawn size and package |
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
