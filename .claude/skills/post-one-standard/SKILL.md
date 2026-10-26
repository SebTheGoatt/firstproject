---
name: post-one-standard
description: >-
  The owner's standard for Post One Lawn Co. work: how to take in anything they send (Instagram or TikTok reels,
  uploaded videos, links, PDFs, screenshots, often with no instruction at all), judge it through the business lens,
  decide adopt / adapt / not now / skip, build it in this repo, prove it, ship it (PR, merge, branch reset) and report
  back in plain, friendly words. Use this skill whenever the owner pastes a link or uploads a file, says "merge",
  "build it", "use this", "yes to both", "make it a skill" or "this is the standard", or asks for any feature, page,
  marketing, pricing, giving or route change for Post One, even when they don't say what to do with it.
---

# The Post One standard

This is how work gets done for Post One Lawn Co. It was reverse-engineered from the sessions the owner was happy
with: they send material, Claude figures out what it's worth to the business, builds what earns its place, proves
it works, ships it, and explains it in a few clear lines. Read the root `CLAUDE.md` first every time: it holds the
standing decisions and hard rules, and this skill doesn't repeat them.

## Who you're working for

- A veteran, husband and father of a toddler who runs the business on limited hours. Lead with the answer, keep it
  short, and keep the tone friendly and reassuring. Never make them scroll back to understand you.
- Business-trained (MBA; coursework in SEO, e-commerce, marketing, strategy, finance, business analysis, legal and
  ethical issues, and AI in business). Reason like a peer: unit economics, positioning, retention, risk. Say it in
  plain words, not jargon.
- They often send a link or a file with no words. That means "evaluate this and do what's useful". A direct request
  ("build it", "merge", "yes") is approval to build and merge; don't ask again.
- They push back plainly ("Free? Ain't nothing for free"). When they do, the correction becomes a standing decision:
  fix the work, then write it into `CLAUDE.md`.

## The loop

Every request runs the same eight steps. Skip a step only when it truly doesn't apply (a question needs no ship).

1. **Intake**: get the real content, not just the title.
2. **Privacy gate**: decide what may never leave the conversation.
3. **Judge**: run it through the business lens.
4. **Decide**: adopt, adapt, not now, or skip, with one honest reason.
5. **Build**: in the repo's own patterns.
6. **Prove**: tests, browser, accessibility, your own eyes on the screenshots.
7. **Ship**: PR, merge, reset the branch.
8. **Report and remember**: the short answer, the owner's to-dos, and updates to `CLAUDE.md`, the reel log and
   this skill.

### 1. Intake

Get what the material actually says. Captions are often bait ("Comment SEO"); the substance is in the frames and
the audio.

- **Instagram reel link**: `python3 .claude/skills/post-one-standard/scripts/fetch_reel.py <url> <scratch>/reel-<code>`
  saves `caption.txt`, `video.mp4` and `meta.json`. It warns when the shortcode is already in the reel log, because the
  owner sometimes resends the same reel with a different `?igsh=` / `?mdxt=` tail. Then say so in one line and point
  to what was done; don't redo the work.
- **Uploaded video** (`/root/.claude/uploads/...mp4`): use it directly.
- **Any video**: `scripts/frames.py <video> <outdir>` makes a 20-frame contact sheet (read it with the Read tool), and
  `scripts/transcribe.py <video> [...]` prints the speech. Use both: on-screen steps plus what's said.
- **PDF**: `pdftotext -layout file.pdf out.txt` (the Read tool can come back empty on encrypted PDFs).
- **Website or repo link**: fetch it and read the README / features; for GitHub, check the license before reusing code.
- If a fetch is blocked, say exactly what you couldn't read and work from what you could. Don't guess at content.

### 2. Privacy gate

The repo is public. Before anything is written to disk in the repo, sort what you learned:

- **Never commit or repeat**: the owner's or anyone's home address, birth date, student or account IDs, grades,
  phone numbers, customer names, nominee details, secrets. A transcript, ID or bank document is context for you only;
  use what it says about skills or goals, and say in the report that the personal details were left out.
- **Secrets** are never asked for in chat. Settings the owner sets go in Render; tell them the variable name.
- Photos go through `normalize_photo()`; claims (insurance, background checks, ratings) appear only when settings say
  they're true.

### 3. Judge: the business lens

Read `references/business-lens.md` for the full lens, and `references/graduate-toolkit.md` for the owner's ten MBA
courses mapped onto Post One (strategy, marketing, managerial economics, corporate finance, business analysis, legal
and ethical, organization, leadership, AI in business, crisis management). Name the course that settles a call and
the KPI on `/owner/numbers` that will show whether it worked. The short version, in the order that usually decides it:

1. **Does it build the line?** More paying customers in our areas (distribution beats building; the site already
   does more than competitors).
2. **Does it keep them?** Repeat bookings, trust, fewer surprises.
3. **Does it save crew time or protect margin?** One area a day, tight routes, pay first, the $75 base.
4. **Is it safe?** Legal and ethical (SMS consent covers booking updates only, no fake claims, privacy, pay-first
   refunds), and it doesn't break a standing decision.
5. **Is it worth its upkeep?** Every feature is code to maintain. Keyless, free, CORS-open services beat accounts and
   API keys.

Check the reel log (`references/reel-log.md`) so the same idea isn't judged twice, and so a "not now" can be picked
up when its trigger arrives.

### 4. Decide

Pick one, and give the reason in a sentence:

- **Adopt**: it fits as-is; build it.
- **Adapt**: take the one piece that helps (God's Eye View → only the NOAA radar). Say what was left out and why.
- **Not now**: useful later; name the trigger ("once postonelawn.com is live").
- **Skip**: doesn't fit, duplicates what we have, or costs more than it's worth.
- **No code needed**: sometimes the honest answer is a plan, not a build ("the line is the valuable part": point
  the owner at customers with the tools that already exist). Saying so is part of the standard.

When it touches a decision that is only the owner's (price, policy, who gets paid what), give a recommendation
and ask once, with the options. Otherwise act.

### 5. Build

Follow the code map in `CLAUDE.md`. The patterns that keep coming up:

- Prices, days and areas come from `app/pricing.py` and `app/zones.py`; never hard-code them in a page.
- Public pages: server-rendered with `layout()` (`app/local_pages.py`), Post Green bands, Big Shoulders headlines, and
  added to the header/footer nav and `/sitemap.xml` if public. Owner and crew pages: the daylight work-app look, linked
  in every owner nav (`static/command.html`, `dispatch.html`, `community-owner.html`, `marketing.html`).
- Spanish: add the visible strings to `static/i18n.js` (ES for exact phrases, PATTERNS for text with numbers).
- Database change = four places: a new `supabase/migrations/<timestamp>_<name>.sql`, the same SQL appended to
  `supabase/setup_all.sql`, a line in `GO_LIVE.md`, and a check in `app/readiness.py` so the go-live page shows it.
  Endpoints answer 503 with "run the migration" until it's run, never a crash.
- New module: `register_<name>(app, settings, ...)` called from `app/main.py`, with a module docstring listing its
  routes.
- Tests live in `property-dispatch/tests/`. Helpers: `CREW`, `NOW`, `TOMORROW`, `book()` from `test_api_flow.py`,
  `booked()` from `test_visit_owner.py`; the fake geocoder knows "100 A–E Example Rd". `conftest.py` turns the
  one-area-a-day rule off unless a test is marked `area_days`; a new module that imports `check_area_day` needs its
  own `monkeypatch.setattr` line there.
- Maps: MapLibre 4.7.1 + OpenFreeMap; 3D buildings from Overture PMTiles; respect `prefers-reduced-motion`.

### 6. Prove

Nothing ships on "it should work".

- `cd property-dispatch && python3 -m pytest -q`: every test passes, new behavior has its own tests (including the
  rule it must refuse, not just the happy path).
- Page changes: start the app with made-up demo data on a **new port** each time (never `pkill`; it kills the shell):
  `python3 .claude/skills/post-one-standard/scripts/demo_server.py --port <port>` (run it in the background; it
  prints the demo day and a pay page), then
  `python3 .claude/skills/post-one-standard/scripts/page_check.py --base http://127.0.0.1:<port> --paths /x /y`
  (adds `--token` for owner pages, `--webgl` for maps, `--reduced` for the reduced-motion pass). It reports page
  errors, sideways scroll and axe-core violations at 1440 / 768 / 390 px and saves screenshots.
- Look at the screenshots yourself. Collapsed inputs, overlapping labels and covered credits only show up there.
- Re-read the diff for anything personal or secret before committing.

### 7. Ship

From `/home/user/firstproject`:

1. Commit on `claude/property-service-routing-jntyoz` with a plain subject line, a short body of bullets, and the
   attribution lines the session asks for. No model names anywhere in the commit, PR or code.
2. Push, open a PR into `claude/veteran-gibill-platform-NAd4k` (body: what changed, how it was verified, then the
   session's PR attribution lines), and merge it, passing the full 40-character head sha as `expectedHeadSha`.
3. Reset the branch:
   `git fetch -q origin claude/veteran-gibill-platform-NAd4k && git checkout -q -B claude/property-service-routing-jntyoz origin/claude/veteran-gibill-platform-NAd4k && git push -q -f origin claude/property-service-routing-jntyoz`

Ship each finished piece on its own; don't let three ideas ride one PR.

### 8. Report and remember

Use this shape, and keep it scannable on a phone:

```
<One line: what it was and the verdict.>  (e.g. "That reel is a 10-step SEO checklist. We had most of it; I added the rest and merged it (PR #87).")

<Optional table when mapping someone's checklist onto Post One: step | where we stand.>

**What I built:** 2–5 bullets, each a thing the owner can see or use, with where to find it.

**What you need to do:** numbered steps with exact clicks and the exact Render variable names. Only what's left.

<Honest call or one recommendation, if there is one. At most one question, only for an owner-only decision.>
```

Then remember, so the next session starts where this one ended:

- A new standing decision or owner to-do → `CLAUDE.md`.
- Every reel or link judged → one row in `references/reel-log.md` (shortcode or URL, what it was, verdict, PR).
- When the owner says "make it a skill" or "this is the standard" → reverse-engineer the steps that produced the
  result they liked and save them as a skill under `.claude/skills/` (or improve this one). Ask at most two or three
  questions, and only if there's a real gap. Add a line about it to `CLAUDE.md`.
