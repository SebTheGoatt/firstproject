# Inky & Me Coloring Club

A $0-startup digital coloring book business starring **Inky**, an original
blob-buddy character. Tagline: *We color together.*

## What's in here
| File | What it is |
|---|---|
| `BUSINESS_PLAN.md` | Strategy, product ladder, revenue math, 90-day roadmap |
| `AI_ART_PLAYBOOK.md` | Character sheets, prompts, cleanup, and the rules that keep you safe |
| `product/sampler.pdf` | **Ready-to-upload** free 5-page sampler + certificate |
| `product/build-sampler.mjs` | Rebuilds the sampler (edit pages here) |
| `product/listings.md` | Copy-paste listings for every product, plus KDP keywords |
| `marketing/pinterest-pins.md` | 30 pins, 8 boards, keyword bank |
| `marketing/email-sequence.md` | 5-email welcome sequence + weekly/seasonal templates |
| `marketing/video-scripts.md` | 15 faceless video scripts + a 30-day posting calendar |
| `site/index.html` | Landing page (one file, no cost to host) |

## Launch checklist (about 1 week at 10 hrs)

**Day 1: claim the brand**
- [ ] Check that `inkyandme` is free on Pinterest, TikTok, Instagram, YouTube and Gumroad. Grab them all, or use a backup name.
- [ ] Search tmsearch.uspto.gov for "Inky" in children's books.
- [ ] Create a new Gmail just for the business.

**Day 2: store + email**
- [ ] Create a free Gumroad (or Payhip) account.
- [ ] Upload `product/sampler.pdf` as a $0+ product, using the copy in `product/listings.md`. Gumroad collects buyer emails, so this is your email list from day one.
- [ ] Optional: a free MailerLite account for the welcome sequence in `marketing/email-sequence.md` (export Gumroad emails into it weekly).

**Day 3: landing page (free hosting, pick one)**
- [ ] **Easiest:** go to app.netlify.com/drop and drag the `site` folder in. You get a free URL in seconds.
- [ ] **Or GitHub Pages:** create a new public repo called `inkyandme`, upload `site/index.html` to it, then turn on Settings → Pages → Deploy from branch.
- [ ] Find-and-replace the placeholder links (`SAMPLER_LINK`, `CLUB_LINK`, etc.) with your real Gumroad links. Links for products you haven't made yet can point to the sampler until then.

**Days 4-6: first paid pack**
- [ ] Make 25 pages for *Inky's Big Day Pack* with `AI_ART_PLAYBOOK.md`.
- [ ] List it at $4.99.

**Day 7: start marketing**
- [ ] Set up Pinterest Business with the 8 boards; schedule the first 10 pins.
- [ ] Film and post videos #1 and #3 from `marketing/video-scripts.md`.

## Rebuilding the sampler
```
cd product
NODE_PATH=$(npm root -g) node build-sampler.mjs
```
Needs Node and Playwright with Chromium. If you don't have them, just use
the committed `sampler.pdf`.

## Rules that never bend
- Original characters only. No Bluey, Mickey, SpongeBob, Venom, or any brand
  name in art, titles, tags, pins or file names.
- Disclose AI-generated content wherever a platform asks (KDP does).
- Never show your child's face, name or location in content.
