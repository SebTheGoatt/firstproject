# Post One Lawn Co. — project notes for Claude

Read this first in every new session. It carries the decisions made in earlier conversations so nothing
has to be re-explained. Keep it current: when the owner makes a new standing decision, add it here.

## The business
- **Post One Lawn Co.**, a d/b/a of **Semper Green LLC** (the legal name stays in the footer and policies until the
  Texas assumed-name filing is done). Veteran-owned lawn mowing based in Spring, TX.
- Lawn mowing is the main service (it matches the Google Business Profile's primary category, "Lawn care service").
  Bin cleaning and gutter cleaning are add-ons to a mowing visit. Holiday lighting is quote-only (Oct 15 – Jan 15).
- Promote the business, not the owner's backstory. No military role-play or jargon in customer copy.
- Live site: https://property-dispatch.onrender.com (Render). The domain postonelawn.com is not bought yet.

## Code map (all code is in `property-dispatch/`)
- FastAPI app: `app/main.py`. Data: Supabase in production, `MemoryRepository` in tests.
- Prices: `app/pricing.py` (yield engine, add-ons). Areas and days: `app/zones.py`. Never hard-code a price,
  day or area in a page; read it from these.
- Server-rendered public pages: `app/local_pages.py` (area + neighborhood pages, sitemap, the shared `layout()`),
  `app/service_pages.py`, `app/about_page.py`, `app/legal_pages.py`.
- Static pages: `static/*.html` (home, book, crew, crew-dashboard, command, team, visit, pay). Spanish: `static/i18n.js`.
- Owner screen: `/owner/command` (`app/command.py` + `static/command.html`). Crew route screen: `/crew/dashboard`.
- Design system: `property-dispatch/DESIGN.md`. Public site = Post Green bands, Big Shoulders uppercase headlines.
  Work app (crew/owner) = bright daylight theme, flat, sentence case. The owner disliked the dark "matrix" look.
- Brand kit (private Claude design system built from the above): https://claude.ai/artifact/WNvx4f5pDcb9LnA5NMCUuc
  Build slides, social posts, ads and print from it. If styles.css or the logos change, re-sync it.

## Speed rules (from the full diagnostic)
- Home page: the area map (MapLibre + tiles) loads only when scrolled near; Google address autocomplete loads on the
  first touch of the address form. Keep heavy third-party scripts off the first paint.
- Nothing render-blocking in `<head>` except styles.css: `i18n.js` loads with `defer` (it translates at
  DOMContentLoaded anyway). Text filled in from an API keeps its space while loading (`.po-card-note.is-pending`),
  and scroll code reads layout in `requestAnimationFrame`, never synchronously during page load.
- Static files: `?v=<hash>` URLs are cached for a year; fonts/images/icons a week. New images get new file names.
- Display pages reuse "bookings that day" counts for 30s (`cached_count`); taking a booking always counts fresh.
- Route planning: exact Held-Karp up to 12 stops (milliseconds); OR-Tools above that with a scaled time budget.
- Crew route map: the day's area comes with the route (`RouteView.areas`, from the stops' zones) and is drawn as a
  solid green edge with a light veil outside, so an off-area stop stands out. 3D buildings from OpenStreetMap were
  dropped (0–3 houses per view in our areas); Overture Maps buildings cover them (1,351 in one Klein view, 358 in
  Colony Ridge) and are used on the owner's dispatch board.
- Owner dispatch board `/owner/dispatch` (`app/dispatch_board.py` + `static/dispatch.html`, "Dispatch" in the owner
  menu): the week (area, bookings vs quota, money), the day's real road path (OSRM multi-stop `route_path()`, kept in
  memory per built route; straight legs if OSRM is down), numbered stops, base, area outline, 3D Overture buildings
  (PMTiles `overturemaps-extras-us-west-2/tiles/<release>/buildings.pmtiles`, keyless, CORS-open; bump the release
  now and then), NOAA radar toggle, finish time vs closing ("Done by 2:37 PM · 2h 23m to spare"), visits not on the
  route with the reason, and Build/Rebuild, Rain day, Manifest and Move. Inspired by TopoExport.
- Rain radar on the route map ("Rain radar" toggle, remembered per phone; `/crew/dashboard?radar=1` from the owner's
  "Check the radar" link next to Rain day): NOAA nowCOAST WMS, keyless and CORS-open — MRMS base reflectivity
  (~4 min) + NLDN lightning density (~10 min), refreshed every 5 min, credited in the map attribution. Idea taken
  from God's Eye View (bilawalsidhu/gods-eye-view); its camera/flight/satellite layers were left out on purpose.

## Marketing, SEO and GEO
- Marketing hub `/owner/marketing` (`app/marketing.py`, `static/marketing.html`): this week's posts from live data
  (EN/ES), tagged links + QR codes (`?ref=<channel>-<area>`), printable yard sign / door hanger / flyer, and a
  scoreboard of bookings per channel. `static/site.js` keeps the visitor's source (ref, UTM, or Google / ChatGPT /
  Perplexity referrer) 30 days and the booking saves it in `jobs.source`. Only short labels, never personal data.
- Area map cards: `tools/make_area_cards.py` draws every street of each area (OpenFreeMap tiles, Post One colors,
  the mowed area outlined in brass) as `static/img/area-<slug>-<weekday>.jpg` (1200x630, the area and neighborhood
  pages' share image) and `-square.jpg` (posts; downloadable on the marketing hub). Re-run it when an area's boxes
  or day change; `tests/test_area_cards.py` fails until you do. Keep the OpenStreetMap credit on the cards.
- Service map poster: `tools/make_area_poster.py` (18x24 in, 150 dpi, JPEG + PDF) shows every area with its day and a
  QR code to `/?ref=poster`. File name = fingerprint of areas/boxes/days (`poster_path()`); re-run after a schedule
  change or once postonelawn.com is live (pass the new URL), so new prints carry the right link.
- GEO: `/llms.txt` (plain facts for AI assistants, live data), FAQPage data on home (parsed from the visible FAQ) and
  on each area page (`area_faq`), robots.txt welcomes AI search crawlers, `sameAs` from the *_URL profile settings.
- Repeat bookings: after a visit is done, the visit page shows "Book your next mow" → `/book?again=<code>`, which fills
  the form from `GET /api/visit/{code}/again` (name, phone, address, yard choice, yard type, add-ons; the code leaves
  the address bar at once). Price, area check, consent and payment run as for any booking; tagged `source=rebook`
  ("Repeat customer" on the scoreboard). Never put a "book again" pitch in the texts: SMS consent covers booking
  updates only.
- AI prompt pack on the marketing hub (`prompt_pack()` / `business_facts()` in `app/marketing.py`): six copy-ready
  prompts (review reply, customer reply, property-manager email, video caption, Spanish, weekly plan), each carrying
  live areas/days/prices/policy and the claim rules (insurance and background checks only when the settings say so).
  When a policy or fact changes, it changes there too. Inspired by prompts.chat; generic libraries don't know us.
- Crew "Report a problem" (`app/issues.py`): damage / equipment / access / delay with a photo; first item on the owner
  screen; email via Resend when set. Needs `supabase/migrations/20261028000000_issues_and_sources.sql`.

## Standing decisions
- **One area per day, enforced:** Mon Spring · Tue Klein · Wed New Caney & Splendora · Thu Colony Ridge ·
  Fri Cleveland & Plum Grove · Sat make-up only. Bookings on the wrong day are rejected; the route builder drops
  off-area stops.
- **Pay first, then we mow:** while Stripe is set up, bookings are card only (Apple Pay / Google Pay included) and paid
  at booking. Cash bookings are refused, and an unpaid card booking stays off the crew's route (`prepay_required`
  in `app/config.py`; `unpaid_card()` in `app/nightly.py`). The owner screen marks them "Not paid yet".
- **Working hours:** Mon–Fri 8 AM–5 PM, Saturday 8 AM–2 PM (make-ups only), Sunday off. The crew leaves base so
  the first lawn is mowed at 8:00 (`first_mow_time`); the 5 PM booking cutoff and route build stay. Published to
  Google from `weekday_hours` / `saturday_hours` in `app/config.py` — keep the Google Business Profile matching.
- **Refunds (terms effective Oct 22, 2026):** cancel free until the "crew on the way" text (the app closes online
  cancel then); after it, no refund. Light rain: we mow; lightning/heavy rain/soft ground → make-up day (usually
  Saturday) or full refund. Locked out (gate, loose pet, blocked lawn): unreached parts not refunded. Hazards we
  find: return visit or partial refund. Price is locked: never charge a card more on site without the customer's OK.
- **Neighbor discount (option A):** 5% off the mowing with 2–4 customers booked within half a mile, 10% with 5+.
- Pages only for places we actually mow. No near-duplicate town-swap pages.
- The business phone number stays off the site unless the owner sets `BUSINESS_PHONE`.
- Ciro stays in the pending founders list until the owner says otherwise.

## Hard rules
- Never ask the owner to paste secrets in chat (Supabase, Stripe, Twilio, VAPID, Resend, crew token). Secrets live
  only in Render's environment settings.
- The repo is public: never commit customer names, addresses or phone numbers.
- Photos never keep camera metadata (GPS would reveal a customer's home): `normalize_photo()` in `app/media.py`
  strips EXIF/XMP/text on every upload. Any new photo route must go through it.
- No claims that can't be backed up: insurance, background checks and ratings show only when the owner's settings
  say they're true. No fake stats, reviews or addresses.
- No model names in commits, PRs or code.

## How work ships
- Develop on `claude/property-service-routing-jntyoz`; open the PR into `claude/veteran-gibill-platform-NAd4k`.
  When the owner says "Merge" (or gives a direct request), create the PR, merge it, then reset the branch:
  `git fetch origin claude/veteran-gibill-platform-NAd4k && git checkout -B claude/property-service-routing-jntyoz origin/claude/veteran-gibill-platform-NAd4k && git push -f origin claude/property-service-routing-jntyoz`
- Before shipping: `cd property-dispatch && python3 -m pytest -q` (all tests must pass). For page changes, also check
  the page in a browser at 1440 / 768 / 390px and run an axe-core accessibility pass.
- Test convention: `tests/conftest.py` relaxes the area-day rule unless a test is marked `area_days`.

## Owner's open to-dos (outside the code)
- Render env: `LIABILITY_COVERAGE` only once insured; `BUSINESS_EMAIL`, Stripe and Twilio keys.
- File the Texas assumed-name certificate (Form 503) for Post One Lawn Co.
- Buy postonelawn.com and point it at Render.
- Google Search Console: add the site and submit `/sitemap.xml`. Google Business Profile: primary category
  "Lawn care service", website link, ask first customers for reviews.
- Stripe public business name and statement descriptor → Post One.
- Delete the mock bookings from testing.
- Run `supabase/migrations/20261028000000_issues_and_sources.sql` (problem reports + booking sources).
- Claim the same name, hours, site and service area on Bing Places, Apple Business Connect, Yelp and Nextdoor (AI
  assistants pull from these); set the *_URL profile settings in Render as each one goes live.

## Market notes (Oct 2026 research, public sources)
- Houston-area mowing commonly quotes ~$35–$55 a visit for typical lots (marketplaces advertise "from $19"; GreenPal
  shows ~$39 average in Cleveland). Post One's base is $75 before tax: position on reliability (set day, upfront
  price, texts, photos, pay-first refunds) or revisit the base price — owner's call.
- Competitors are mostly solo crews on directories plus marketplaces (LawnStarter, GreenPal, Lawn Love). "Texas
  Veteran Lawn Service" also brands as veteran-owned in Spring. Colony Ridge / Plum Grove have no dedicated
  providers online, and Spanish-language marketing is an open lane there.
- Lessons from failed home-service startups (startupgraveyard.io): Homejoy kept ~25% of customers past month one and
  <10% past six, lost workers to clients going direct, expanded too fast and was sued over worker classification;
  Exec had high worker turnover, spiky demand and tried to do too many things. Post One's answers: repeat bookings in
  one tap, one area a day, mowing first, no expansion beyond our areas. Crew pay/classification is the owner's call.

