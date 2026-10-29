# The graduate toolkit

The owner's MBA courses, turned into the frameworks this business runs on. Use the course that fits the decision in
front of you, say which one in a few plain words ("break-even says…", "the payback is…"), and point at the number
in the app that will show whether it worked. Every feature should name the KPI it moves (business analysis).

## Contents
1. Strategic management · 2. Marketing management · 3. Managerial economics · 4. Corporate finance ·
5. Business analysis · 6. Legal and ethical issues · 7. Organizational management · 8. Leadership ·
9. AI practices in business · 10. AI and crisis management

## 1. Strategic management: where we win and how we grow
- **Position:** differentiate on reliability (a set day, a locked price, texts and photos, pay-first refunds), not
  on price. Competitors are solo crews and marketplaces; none owns "the same day every week, never a surprise".
- **Moat:** route density. One area a day means more lawns per hour and less driving than anyone who drives
  everywhere. Growth comes from more homes on the same streets, never from new towns (Homejoy expanded too fast).
- **Forces to watch:** low barriers to entry (anyone with a mower), price-shopping on marketplaces, and the
  weather. The answer to all three is density plus repeat customers.
- **In the app:** the one-area-a-day rule, the dispatch board, the neighbor discount. **Watch:** crew time on lawns
  and lawns per area day on `/owner/numbers`.

## 2. Marketing management: who, what, where
- **Segment, target, position:** owner-lived single-family homes, higher incomes, older owners and busy families
  (`/owner/targets` ranks every block). Position: "Your lawn, the same day every week, at the price you saw."
- **The 4 Ps:** product = the mow plus add-ons; price = value-based $75 base with the neighbor discount;
  place = our five areas on their days; promotion = door hangers, mail, posts and reviews, every link tagged.
- **Customer lifetime value:** about 20 mows a year × the average ticket. Spend to win a customer only while the
  cost stays under a third of their first-year contribution (from `/owner/numbers`).
- **Watch:** bookings per channel (marketing scoreboard), repeat customers, reviews (68% of people need 4 stars+).

## 3. Managerial economics: what a mow really earns
- **Contribution margin:** price minus giving, card fee, crew pay (drive and lawn time), truck miles and supplies.
  It pays the fixed costs; break-even = fixed costs ÷ contribution per mow.
- **Marginal cost:** an extra stop on a street we already mow costs a few minutes, not a trip. That's why the
  neighbor discount pays for itself, and why filling an area day beats adding a day.
- **Price:** a $10 cut needs many more mows to cover the same costs (the price check on `/owner/numbers`); local
  quotes are $35–$55, so compete on reliability.
- **Capacity:** the daily limit is the constraint. A day near the limit is a reason to raise the price or add a
  crew, not to accept far-away stops.

## 4. Corporate finance: cash, capital and risk
- **Working capital:** pay first, then mow, so customers fund the work and there are no receivables to chase.
  Keep it.
- **Capital budgeting:** buy equipment when it pays back within a season (about 40 weeks of mowing) at the current
  pace ("Should I buy it?" on `/owner/numbers`). Faster gear also fits more lawns into an area day.
- **Fixed costs and reserves:** know the monthly fixed costs, keep a cash cushion for the winter slowdown (Houston
  mowing restarts mid-to-late March) and for storm weeks.
- **Giving is a cost line:** the cause share comes out of every mow; sponsorships and round-ups are paid by
  customers on top (nothing is free).

## 5. Business analysis: measure, then decide
- **The KPIs:** visits a week, average ticket, repeat customers, crew time on lawns, earned per crew hour, next 4
  weeks booked, cancellations, giving. All on `/owner/numbers`.
- **Requirements first:** before building, write the problem, who has it and which KPI should move. If no KPI moves,
  it's a "not now".
- **Root cause:** when a number slips, find the cause (an area's drive time, a channel's no-shows) before adding a
  feature.

## 6. Legal and ethical issues: stay clean
- **Texting:** consent covers booking updates only; no promotions in texts (TCPA). Service changes during a storm
  are booking updates.
- **Truth in advertising:** no claim without proof (insurance, background checks, ratings show only when settings
  say they're true; no fake stats or reviews).
- **Privacy:** no customer data in the public repo; photos stripped of location; delete-my-data honored.
- **Texas:** lawn services are taxable (tax shown before booking); d/b/a certificate for Post One; published
  refund terms. **Crew pay and classification** is the owner's call; Homejoy was sued over it, so get advice early.
- **Accessibility:** every page passes an axe-core check at three widths.
- **Second-chance hiring:** the Work Opportunity Tax Credit covers hires who are veterans or have a felony record
  (pre-screen and certify with the Texas Workforce Commission within 28 days of the start date). The Federal Bonding
  Program gives free fidelity bonds for justice-involved hires. If background checks are ever run, follow the Fair
  Credit Reporting Act (written consent, adverse-action notices). Customer copy about the crew shows only what's true
  and what the owner chose to say.

## 7. Organizational management: how the work is organized
- Standard work beats heroics: the crew app (route, notes, photos, "Report a problem"), the nightly manifest, and
  the owner's screens split who does what. Write a short SOP before hiring the first crew member.
- Keep the span small: one crew, one area, one day. Add a crew before adding an area.

## 8. Leadership: people stay where they're respected
- **The mission is the workforce:** jobs for veterans and formerly incarcerated people rebuilding their lives. Design
  for that: predictable days (one area a day), clear standards, fair pay, a path to crew lead.
- Exec failed partly on crew turnover. Clear standards (the visit checklist and photos), recognition (crew profiles
  on the team page) and fair, predictable days keep people.
- If there's a bonus, tie it to what customers feel: on-time arrivals, photos sent, reviews, no damage reports.

## 9. AI practices in business: AI drafts, people decide
- AI writes from live facts (the prompt pack, `business_facts()`), never invented ones, and a person reviews before
  anything goes out. Route optimization and transcription are AI doing the tedious part.
- Every AI output that reaches a customer must be true, kind and in our voice.

## 10. AI and crisis management: plan before the storm
- **Houston risks:** hurricanes and tropical storms (June–November), lightning and flooding (radar and Rain day),
  freezes, extreme heat (Saturday make-ups end at 2 PM), a crew injury, a data or payment outage.
- **Playbook:** watch the radar and the forecast; move the day with Rain day (customers get the booking-update
  text); for a multi-day event, pause new bookings with storm mode and say so on the site; keep the nightly manifest
  emailed as an offline backup; refunds follow the published terms.
- **After:** check on customers' yards only as a booking update, log what happened, and adjust the plan.
