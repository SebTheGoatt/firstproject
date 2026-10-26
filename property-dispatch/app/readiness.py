"""Go-live checklist: everything the business needs before real customers book.

    GET /api/owner/readiness   owner only: {"ready": bool, "checks": [{key, label, ok, required, fix}]}
    GET /owner/readiness       the same as a page (uses the crew sign-in saved on the phone)

Read-only: it looks at settings and asks the database harmless questions. It never shows a secret,
only whether each one is set and looks right.
"""

from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI

from . import push
from .booking import local_now
from .config import Settings
from .reviews import review_link

STRONG = 24   # characters, for the owner-made secrets


def checks(settings: Settings, repo, stripe_enabled: bool) -> list[dict]:
    out: list[dict] = []

    def add(key, label, ok, fix, required=True):
        out.append({"key": key, "label": label, "ok": bool(ok), "required": required, "fix": "" if ok else fix})

    def db(fn):
        try:
            fn()
            return True
        except Exception:
            return False

    add("environment", "ENVIRONMENT is production", settings.environment.lower() == "production",
        "Render → Environment: ENVIRONMENT=production")
    add("database", "Real database (Supabase), not test memory", settings.data_backend != "memory",
        "Render → Environment: DATA_BACKEND=supabase with SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
    reachable = settings.data_backend != "memory" and db(lambda: repo.count_active_jobs(local_now(settings).date()))
    add("database_reachable", "Database answers", reachable, "Check SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY in Render")
    if reachable:
        now = datetime.now(timezone.utc)
        add("sql_reviews", "Database has the review-request column", db(lambda: repo.jobs_due_review(now - timedelta(minutes=1), now)),
            "Supabase → SQL Editor: run supabase/migrations/20261027000000_review_requests.sql")
        add("sql_notes", "Database has the crew-notes column",
            db(lambda: repo.stop_notes("00000000-0000-0000-0000-000000000000")),
            "Supabase → SQL Editor: run supabase/migrations/20261026000000_crew_notes.sql")
        add("sql_issues", "Database has crew problem reports and booking sources",
            db(lambda: repo.list_issues(open_only=True, limit=1)) and db(lambda: repo.bookings_by_source(now)),
            "Supabase → SQL Editor: run supabase/migrations/20261028000000_issues_and_sources.sql")
        add("sql_community", "Database has sponsored mows and nominations", db(repo.sponsorships),
            "Supabase → SQL Editor: run supabase/migrations/20261029000000_community.sql")
        mock = 0
        try:
            mock = repo.count_customers_named("MOCK ")
        except Exception:
            pass
        add("no_test_data", "No test (MOCK) bookings left", mock == 0,
            f"{mock} test customers found. Supabase → SQL Editor: delete from customers where name like 'MOCK %';")
    add("stripe_live", "Stripe live keys", stripe_enabled and settings.stripe_secret_key.startswith(("sk_live_", "rk_live_")),
        "Render: STRIPE_SECRET_KEY=sk_live_… and STRIPE_WEBHOOK_SECRET=whsec_… (Stripe → Developers)")
    add("stripe_webhook", "Stripe webhook secret", settings.stripe_webhook_secret.startswith("whsec_"),
        "Stripe → Developers → Webhooks → add <your site>/webhooks/stripe (checkout.session.completed, payment_intent.succeeded); copy its signing secret")
    add("twilio", "Text messages (Twilio)", settings.twilio_enabled,
        "Render: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER (an A2P 10DLC-registered number)")
    add("public_url", "Public site address (https)", settings.public_base_url.startswith("https://"),
        "Render: PUBLIC_BASE_URL=https://your-site (used in texted links)")
    add("secrets", "Crew, webhook and cron secrets are strong",
        all(len(getattr(settings, n)) >= STRONG and getattr(settings, n) != "change-me"
            for n in ("crew_access_token", "webhook_secret", "cron_secret")),
        f"Render: CREW_ACCESS_TOKEN, WEBHOOK_SECRET, CRON_SECRET at least {STRONG} random characters each")
    add("contact", "Business email on the site", settings.business_email, "Render: BUSINESS_EMAIL (your business Gmail)")
    add("phone", "Business phone line on the site", settings.business_phone,
        "Render: BUSINESS_PHONE (a business line such as Google Voice, never a personal cell)", required=False)
    add("maps", "Google address dropdown", settings.google_maps_browser_key, "Render: GOOGLE_MAPS_API_KEY", required=False)
    add("reviews", "Google review link", review_link(settings), "Render: GOOGLE_REVIEW_URL (Google Business Profile → Ask for reviews)",
        required=False)
    add("push", "App notifications", push.keys_status(settings) == "ok", "Make keys at /push-setup; Render: VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY",
        required=False)
    add("manifest_email", "Nightly manifest emailed as a backup", settings.resend_api_key and settings.operational_alert_email,
        "Render: RESEND_API_KEY and OPERATIONAL_ALERT_EMAIL (verify your domain in Resend, then set RESEND_FROM)", required=False)
    # Search engines (do these the day the site goes live): prove ownership, then submit the sitemap.
    add("search_console", "Google Search Console verified",
        settings.google_site_verification,
        "Search Console → Add property → URL prefix (your site) → HTML tag: copy only the content=\"…\" code into "
        "Render: GOOGLE_SITE_VERIFICATION, redeploy, press Verify, then Sitemaps → submit sitemap.xml", required=False)
    add("bing", "Bing Webmaster Tools verified (Bing, Copilot and ChatGPT search use Bing)",
        settings.bing_site_verification,
        "bing.com/webmasters → Add site (or import from Search Console) → HTML meta tag: copy the content code into "
        "Render: BING_SITE_VERIFICATION, redeploy, Verify, then submit sitemap.xml", required=False)
    add("business_profile_link", "Google Business Profile linked to the site", settings.google_business_url,
        "Render: GOOGLE_BUSINESS_URL (your profile's share link), and put the site address on the profile", required=False)
    add("base_yard", "Crew start location set", (settings.base_lat, settings.base_lng) != (30.0799, -95.4172),
        "Render: BASE_YARD_LATITUDE / BASE_YARD_LONGITUDE (where the crew leaves from each morning)", required=False)
    add("charity_names", "Charity names confirmed",
        settings.charity_toys_name != Settings.model_fields["charity_toys_name"].default,
        "Render: CHARITY_TOYS_NAME once the program has said yes (until then a plain description shows)", required=False)
    # The site was renamed; a BUSINESS_NAME left over in Render would keep the old name on every page and text.
    add("brand_name", "Site shows the Post One name", "semper green" not in settings.business_name.lower(),
        f"Render → Environment: BUSINESS_NAME=Post One Lawn Co., or delete it (that's the default). It is now \"{settings.business_name}\"",
        required=False)
    return out


def register_readiness(app: FastAPI, settings: Settings, owner, page) -> None:
    @app.get("/api/owner/readiness", dependencies=[Depends(owner)])
    def readiness():
        items = checks(settings, app.state.repo, app.state.stripe is not None)
        return {"ready": all(c["ok"] for c in items if c["required"]), "checks": items}

    @app.get("/owner/readiness", include_in_schema=False)
    def readiness_page():
        resp = page("readiness.html")
        resp.headers["X-Robots-Tag"] = "noindex"
        return resp
