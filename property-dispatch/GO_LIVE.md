# Going live: Post One Lawn Co.

The app checks itself: sign in as the owner, open **Crew app → Dashboard → Go-live checklist**
(`/owner/readiness`). Every ❌ shows exactly what to set. When it says **✓ Ready to go live**, you are.

## One-time setup (in this order)
1. **Supabase**: SQL Editor → run `supabase/migrations/20261026000000_crew_notes.sql` and
   `supabase/migrations/20261027000000_review_requests.sql`, then
   `supabase/migrations/20261028000000_issues_and_sources.sql` (crew problem reports and booking sources).
   All safe to re-run.
   Then remove test bookings: `delete from customers where name like 'MOCK %';`
2. **Render → Environment**: fill in every value from `.env.production.example` (web service, and the
   `property-dispatch-nightly` cron job for the database, base yard and Resend values).
3. **Stripe** (live mode): API keys → `STRIPE_SECRET_KEY`; Webhooks → add `<site>/webhooks/stripe` with
   `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `payment_intent.succeeded`
   → `STRIPE_WEBHOOK_SECRET`. Turn on email receipts (Settings → Customer emails).
4. **Twilio**: buy a 936 number, register it for **A2P 10DLC** (brand + "customer care" campaign; use the
   booking form's consent text and your /privacy and /terms links as the opt-in proof), then set the three
   `TWILIO_` values.
5. **Google**: Business Profile (service-area business, hide the address) → review link → `GOOGLE_REVIEW_URL`;
   Search Console → submit `<site>/sitemap.xml`; Maps key restricted to your site → `GOOGLE_MAPS_API_KEY`.
6. **Resend** (optional backup): verify your domain, set `RESEND_API_KEY`, `OPERATIONAL_ALERT_EMAIL`, `RESEND_FROM`.
7. **Push notifications**: open `/push-setup`, copy the key pair into Render.
8. **Legal**: have a Texas attorney review /privacy, /terms (damage policy) and /refunds. Set
   `LIABILITY_COVERAGE` / `CREW_BACKGROUND_CHECKED` only once they're true.

## Brand
The public name is **Post One Lawn Co.**; the legal name stays **Semper Green LLC** (the policy pages read
"Semper Green LLC, doing business as Post One Lawn Co.").
- **Render → Environment**: if `BUSINESS_NAME` was set, change it to `Post One Lawn Co.` (or delete it; that's the
  default). The go-live checklist flags a leftover old name.
- **Texas assumed name**: file an assumed name certificate (Form 503) with the Texas Secretary of State for
  Semper Green LLC d/b/a Post One Lawn Co. (required when the LLC does business under another name).

## The day you open
- Make one real test booking with your own card, refund it in Stripe, then delete it from your visit page.
- Build tomorrow's route from the owner dashboard and print the manifest.
- Walk one stop on the crew dashboard (START ROUTE TRANSIT → ARRIVED ON SITE → COMPLETE).
