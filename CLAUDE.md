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

## Standing decisions
- **One area per day, enforced:** Mon Spring · Tue Klein · Wed New Caney & Splendora · Thu Colony Ridge ·
  Fri Cleveland & Plum Grove · Sat make-up only. Bookings on the wrong day are rejected; the route builder drops
  off-area stops.
- **Pay first, then we mow:** while Stripe is set up, bookings are card only (Apple Pay / Google Pay included) and paid
  at booking. Cash bookings are refused, and an unpaid card booking stays off the crew's route (`prepay_required`
  in `app/config.py`; `unpaid_card()` in `app/nightly.py`). The owner screen marks them "Not paid yet".
- **Neighbor discount (option A):** 5% off the mowing with 2–4 customers booked within half a mile, 10% with 5+.
- Pages only for places we actually mow. No near-duplicate town-swap pages.
- The business phone number stays off the site unless the owner sets `BUSINESS_PHONE`.
- Ciro stays in the pending founders list until the owner says otherwise.

## Hard rules
- Never ask the owner to paste secrets in chat (Supabase, Stripe, Twilio, VAPID, Resend, crew token). Secrets live
  only in Render's environment settings.
- The repo is public: never commit customer names, addresses or phone numbers.
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
