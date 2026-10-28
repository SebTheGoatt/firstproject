# Atascocita DoorDash schedule planner

A terminal app that builds a weekly dash schedule for the Atascocita / Humble zone, flags shifts that sit in
dead hours, and learns from the earnings you log. For personal use.

```
python3 dasher_schedule.py          # menu: build week, add/remove shifts, log dashes, report, settings
python3 dasher_schedule.py --plan   # a typical week
python3 dasher_schedule.py --weather          # the next 7 days with the live NWS forecast and alerts
python3 dasher_schedule.py --week 2027-03-01  # any week: local events count
python3 dasher_schedule.py --today [--json]   # just today (the Dash today pane uses this)
python3 -m pytest -q                # tests (pip install pytest)
```

## What changes a real week (`outlook.py`)
- **Weather (National Weather Service, keyless):** a rain chance of 40% or more raises demand 10%, and 70% or
  more raises it 20%. A thunderstorm in the forecast adds a safety note. Flash flood, tornado, tropical and
  severe-storm warnings take their hours off the plan.
- **Local calendar:** Texans home games, Humble ISD Thanksgiving and winter breaks, Thanksgiving Day (quieter),
  Black Friday, Christmas and New Year's Eve. Add next season's dates to `EVENTS` once they're published.

## Around it
- **Dash today pane** (`.claude/mods/dash-today`): today's shifts, where to wait and the day's notes beside the
  chat; `/dash` reopens it.
- **Plan page:** https://claude.ai/artifact/TcAeECPcbXJG8hQKdBhBKU (private), with the next 7 days, a typical week
  and a demand heatmap.

## How it plans
1. Every hour of the week (6 AM to 1 AM) gets a demand score from 0 to 1.
2. The planner picks the strongest hours up to your weekly goal (default 50) with a per-day cap (default 10).
   Hours under the bar (0.45) never get used just to hit the goal, because they drag your $/hr down.
3. Hours are merged into shifts, each with a strategy: restaurants at meal peaks, Shop & Deliver
   (H-E-B / Target / Walmart) in the 2–4 PM lull, fast food after 9 PM.
4. Settings let you block family time and days off; the planner works around them.

## Where the demand scores come from
These are estimates, not DoorDash data. No public source publishes hour-by-hour order volume for Atascocita.
- DoorDash's own Dasher blog: lunch 11 AM–2 PM, dinner 4:30–8 PM, schedule around local peaks.
- Dasher-community consensus: Peak Pay most often 12–1 and 6–7 PM on weekdays; Friday evening through
  Sunday is busiest; late night pays only where nightlife is active. Atascocita has late-night fast food on
  FM 1960, not a bar district, so the late-night scores are kept modest.
- Atascocita is a large suburb (2020 census 88,174; ~104k by the 2024 ACS) on FM 1960 east of Humble,
  so the zone is mostly families ordering dinner, with a big weekend lift.

**Log your dashes** (menu 4). Each logged shift pulls that day and hour toward your real $/hr. After about
3 logs a slot is half your data, half the estimate, and from there your own numbers take over more and more.

## Money settings
- `car_cost_per_mile` (default $0.30) estimates gas and wear for "after car cost" $/hr. Set it to your car.
- `irs_rate_per_mile` is the IRS 2026 business rate (72.5¢, Jan 2026). Some outlets report a mid-year
  change; check irs.gov before you file. Keep a mileage log either way.

Personal files (`atascocita_*.json`) stay on your machine and are not committed.
