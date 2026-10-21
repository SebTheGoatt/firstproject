---
version: 1
name: Post-One-Lawn-Co
description: >
  Post One Lawn Co. is a veteran-owned lawn mowing business around Spring, TX. The brand reads like a
  well-run post: a deep Post Green ground, a single Fresh Blade green for the one action that matters, thin
  Dress Brass edges, and condensed uppercase Big Shoulders Display headlines over plain Public Sans text.
  Two surfaces share one palette: the public site (dark green bands, display headlines, big friendly
  buttons) and the work app for the crew and owner (bright, flat, sentence case, colour only on data).

colors:
  post-green: "#0F2B22"        # brand ground: header, hero bands, footer cards
  field-green: "#2E7D4F"       # primary buttons and links on light; the one data hue in the app
  field-green-strong: "#1F5A3C" # green text on light green tints
  field-green-soft: "#E6F1EA"  # selected states, "on the route" pills
  fresh-blade: "#9BD15A"       # the main action on dark grounds only; never text on light
  dress-brass: "#C9A227"       # thin edges and rules on dark; never body text on light
  ink: "#14201B"               # text on light
  muted: "#4A5650"             # secondary text (7:1 on white)
  parade-ground: "#F5F6F1"     # page ground
  surface: "#FFFFFF"           # cards and sheets
  border: "#D9DED6"
  border-strong: "#B9C2BC"     # inputs and choice tiles
  on-dark: "#F5F6F1"
  on-dark-muted: "#C9D3CD"
  dark-raised: "#17382C"       # cards on Post Green
  dark-line: "#24483A"         # borders on Post Green
  danger: "#B42318"
  warn: "#7A5300"
  warn-soft: "#FFF4D6"

typography:
  display:
    fontFamily: "'Big Shoulders Display', 'Arial Narrow', system-ui, sans-serif"
    fontWeight: 800
    textTransform: uppercase
    letterSpacing: "0.01em"
    lineHeight: 1.05
  body:
    fontFamily: "'Public Sans', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontSize: 16px
    lineHeight: 1.5
  numbers:
    fontVariantNumeric: tabular-nums
  files: static/fonts (self-hosted woff2, OFL licenses alongside)

rounded:
  button: 10px
  card: 14px
  pill: 999px

spacing:
  gutter: "16px phone / 20px tablet / 32px desktop"
  section-y: "44px phone / 64px desktop"
  container: 1150px
  tap-target: "44px minimum (48px in the crew route screen)"
---

# Post One Lawn Co. design system

The source of truth is `static/styles.css` (tokens on `:root`) and the server-rendered page shell in
`app/local_pages.py` (`layout()`). This file describes them so new pages can be built on brand without
reading the whole stylesheet. If the two ever disagree, the stylesheet wins. Fix this file.

## Overview

- **Voice:** plain, short, confident. "On post. On time." / "Every yard gets Post One attention." No jargon,
  no military role-play, no claims the business can't back up (insurance, ratings and background checks
  appear only when the owner's settings say they're true).
- **Two surfaces, one palette:**
  - **Public site** (`/`, `/book`, `/services`, `/local`, `/about`, policies): Post Green hero bands and
    footer, Parade Ground sections, uppercase display headlines, Fresh Blade main button on dark.
  - **Work app** (`/crew`, `/crew/dashboard`, `/owner/command`): daylight theme. White sheets on Parade
    Ground, Ink text, 1px rules, no shadows, sentence-case Public Sans titles. Field Green only on data
    (progress, the stop you're on, the selected day) and the one main action.

## Colors

### Brand
| Token | Hex | Use |
|---|---|---|
| Post Green | `#0F2B22` | Header, hero bands, footer, the dark CTA band |
| Field Green | `#2E7D4F` | Primary buttons and links on light grounds |
| Fresh Blade | `#9BD15A` | The main action on dark grounds (e.g. "Book online" in a hero) |
| Dress Brass | `#C9A227` | Thin top edges on cards and bands over dark; never body text |

### Surface and text
Parade Ground `#F5F6F1` for the page, white for cards. Ink `#14201B` for text, Muted `#4A5650` for secondary
text. On Post Green use `#F5F6F1` and `#C9D3CD`.

### Rules
- Text contrast is 4.5:1 or better everywhere. Fresh Blade and Dress Brass are never text on light.
- One filled button per view. Everything else is outline or quiet.
- Red (`#B42318`) means something is wrong (a booking on the wrong area day, a missing photo), never decoration.

## Typography

- **Big Shoulders Display 800, uppercase** for h1–h3 on the public site. It is condensed, so set it larger
  than a body face: hero h1 roughly 56–88px desktop, section h2 roughly 36–54px.
- **Public Sans 400–700** for everything else, 16px base. Work-app titles are Public Sans 700, sentence case,
  about 24px. No uppercase display type inside the app.
- Money, counts and times use `font-variant-numeric: tabular-nums`.
- No monospace except codes the user has to read back (visit access codes).

## Layout

- Container 1150px, centered, gutter 16 / 20 / 32px.
- Sections stack with 44px (phone) to 64px (desktop) vertical padding.
- Public pages: dark hero band → content sections on Parade Ground → dark CTA band → dark footer.
- Area, neighborhood and service pages share one shell (`layout()`), breadcrumbs, one JSON-LD block and a
  canonical link.

## Elevation and shape

- Cards: white, 1px `#D9DED6` border, 14px radius, a very soft shadow on the public site, no shadow in the app.
- Buttons: 10px radius, 44px minimum height (52px for `btn-lg`).
- Pills and chips: 999px radius, 1px border.
- A 4px Dress Brass top edge marks the featured card on a dark band (next open day, CTA band).

## Components

### Buttons
- `btn-primary`: Field Green fill, white text. On dark bands the main action uses Fresh Blade fill with Post
  Green text instead.
- `btn-outline`: white with a green-tinted border; secondary actions.
- `btn-quiet` / line buttons on dark: transparent with a muted border.
- Press feedback: `transform: scale(0.97)` on `:active`, 120ms ease-out. Respect `prefers-reduced-motion`.

### Cards and lists
- `.card` for forms and price tables. `.local-list` for label + value tiles. `.area-links` for pill links.
- FAQ: `<details>` cards with a `+` that turns into `×` when open.

### Forms
- Labels above inputs, hint text under them, errors in a `role="alert"` box at the top of the form.
- Choice tiles (yard type, add-ons) are real controls: `role="checkbox"` or radio inputs, never a div with
  a hidden input inside.

### Navigation
- Public header: Post Green bar, logo mark + two-line wordmark, Services / Service areas / Meet the crew /
  About, Book now on the right.
- Work app: white top bar, the mark and name, the current screen as a grey pill.

### Signature pieces
- **Logo A:** shield with a "1", Post Green fill, Dress Brass edge, Fresh Blade numeral
  (`static/brand/`). Never recolor the shield.
- **One area a day:** the week shown as one column per day, each day naming its area.
- **Price shown before booking:** every price on the site is read from `app/pricing.py`, never typed into a page.

## Do's and don'ts

**Do**
- Lead with lawn mowing. Bins, gutters and holiday lighting are add-ons to a mowing visit.
- Write prices, days and areas from the data (`app/pricing.py`, `app/zones.py`), not by hand.
- Keep every claim checkable against the terms, refund policy and owner settings.
- Use drawn SVG icons with `aria-hidden="true"`.

**Don't**
- Don't use emoji as icons, gradient text, glass blur or glowing borders.
- Don't add pages for places we don't mow, or near-duplicate pages with only the town name swapped.
- Don't publish customer names, addresses or phone numbers on any public page.
- Don't copy another company's look; Post One's palette and type are the brand.

## Responsive behavior

- Breakpoints used in the stylesheet: 400px, 640–680px, 760px, 900px, 1040–1100px.
- Every public page is checked at 1440, 768 and 390px wide with no sideways scrolling.
- Phones: one column, the week strip scrolls sideways, a sticky "Book a mow" bar on the home page.
- Tap targets 44px minimum; 48px on the crew route screen for gloved hands.

## Iteration guide

1. Start from the shell in `app/local_pages.py` (`layout()`, `crumbs()`, `cta_band()`) for any new public page.
2. Reuse existing classes before adding CSS. New CSS goes at the end of `static/styles.css` under a
   `/* ===== name (Post One) ===== */` header.
3. Run `pytest` and an accessibility pass (axe-core, WCAG 2 AA) before shipping.
