#!/usr/bin/env python3
"""Atascocita / Humble DoorDash schedule planner.

Builds a weekly dash schedule from an hour-by-hour demand estimate, warns when a
shift sits in a dead zone, and learns from the earnings you log so next week's
plan follows your real numbers instead of guesses.

Run:  python3 dasher_schedule.py          (menu)
      python3 dasher_schedule.py --plan   (build and print this week's plan)
"""
import json
import os
import sys
from datetime import date, datetime, timedelta

from outlook import CENTRAL, POST_ONE_LAUNCH, Outlook, fetch, mowing_block, to_date

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEDULE_FILE = os.path.join(HERE, "atascocita_schedule.json")
EARNINGS_FILE = os.path.join(HERE, "atascocita_earnings.json")
SETTINGS_FILE = os.path.join(HERE, "atascocita_settings.json")

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Hours we plan in: 6 AM through the 1 AM hour (24 = midnight-1 AM next day).
HOURS = list(range(6, 25))

# Demand estimate, 0 (dead) to 1 (best hour of a normal week). Starting point:
# DoorDash's own peaks (lunch 11-2, dinner 4:30-8), Peak Pay most often 12-1 and
# 6-7 on weekdays, Fri-Sun busiest, late night only where nightlife is active
# (FM 1960 / Atascocita Rd has fast food open late, not a bar district).
# These are estimates, not DoorDash data: log your shifts and the plan corrects itself.
WEEKDAY_CURVE = {
    6: 0.10, 7: 0.20, 8: 0.25, 9: 0.20, 10: 0.35, 11: 0.80, 12: 1.00, 13: 0.70,
    14: 0.30, 15: 0.30, 16: 0.50, 17: 0.85, 18: 1.00, 19: 0.90, 20: 0.65,
    21: 0.45, 22: 0.35, 23: 0.25, 24: 0.15,
}
DAY_FACTOR = {
    "Monday": 0.80, "Tuesday": 0.70, "Wednesday": 0.80, "Thursday": 0.90,
    "Friday": 1.10, "Saturday": 1.15, "Sunday": 1.15,
}
# Day-specific changes on top of the curve (already scaled 0-1, before DAY_FACTOR).
DAY_OVERRIDES = {
    "Friday": {21: 0.60, 22: 0.50, 23: 0.40},
    "Saturday": {9: 0.35, 10: 0.50, 21: 0.65, 22: 0.55, 23: 0.45, 24: 0.30},
    # Sunday runs all day: brunch, then families ordering in, then dinner.
    "Sunday": {9: 0.40, 10: 0.60, 11: 0.85, 12: 1.00, 13: 0.90, 14: 0.70,
               15: 0.70, 16: 0.75, 21: 0.40},
}

DEAD_SCORE = 0.40       # below this an hour is a dead zone for restaurant orders
STANDARD = "Standard Delivery"
SHOP = "Shop & Deliver"
LATE = "Late Night Fast Food"
STRATEGIES = [STANDARD, SHOP, LATE]

# Where to wait in the Atascocita / Humble zone, by strategy.
HOTSPOTS = {
    STANDARD: "FM 1960 & Atascocita Rd corridor (fast casual + chain cluster); "
              "Deerbrook Mall / FM 1960 W in Humble when Atascocita is slow",
    SHOP: "H-E-B and Target on FM 1960 / Atascocita Rd, Walmart on FM 1960 E",
    LATE: "Fast food on FM 1960 near US-59 / I-69 (open-late drive-thrus)",
}

DEFAULT_SETTINGS = {
    "weekly_goal_hours": 50.0,     # your milestone
    "max_hours_per_day": 10.0,
    "min_score": 0.45,             # don't schedule hours weaker than this
    "reference_rate": 25.0,        # $/hr you'd call a great hour (scales learning)
    "car_cost_per_mile": 0.30,     # gas + wear; edit to your car
    "irs_rate_per_mile": 0.725,    # IRS 2026 business rate (Jan); check irs.gov for updates
    # Times you never dash, e.g. family dinner: {"day": "Sunday", "start": "08:00", "end": "11:00"}
    "protected": [],
    "days_off": [],
    # Post One Lawn Co.: from opening day, weekday 8-5 and Saturday 8-2 are mowing, plus the drive home.
    "post_one_launch": POST_ONE_LAUNCH,
    "post_one_buffer_min": 30,
}


# ---------- time helpers ----------

def parse_time(time_str):
    """'17:30' -> 17.5. Raises ValueError on bad input."""
    parts = time_str.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Use HH:MM, got {time_str!r}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 24 and 0 <= m < 60) or (h == 24 and m):
        raise ValueError(f"Not a time: {time_str!r}")
    return h + m / 60.0


def span(start, end):
    """Start/end in hours; an end at or before the start rolls past midnight."""
    s, e = parse_time(start), parse_time(end)
    if e <= s:
        e += 24.0
    return s, e


def duration(start, end):
    s, e = span(start, end)
    return e - s


def fmt(hour):
    hour %= 24
    return f"{int(hour):02d}:{int(round((hour % 1) * 60)):02d}"


def fmt12(hour):
    hour %= 24
    h, m = int(hour), int(round((hour % 1) * 60))
    suffix = "AM" if h < 12 else "PM"
    return f"{(h % 12) or 12}:{m:02d} {suffix}"


def overlap(a_start, a_end, b_start, b_end):
    """Hours shared by two spans (all in hours, ends may exceed 24)."""
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def slot_hours(start, end):
    """Whole-hour slots a shift touches, with the fraction of each it covers."""
    s, e = span(start, end)
    out = {}
    h = int(s)
    while h < e:
        part = overlap(s, e, h, h + 1)
        if part > 0:
            out[h] = part
        h += 1
    return out


# ---------- storage ----------

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            print(f"[WARN] Could not read {os.path.basename(path)}; starting fresh.")
    return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    settings.update(load_json(SETTINGS_FILE, {}))
    return settings


def load_schedule():
    data = load_json(SCHEDULE_FILE, {})
    return {day: data.get(day, []) for day in DAYS}


# ---------- demand + learning ----------

def prior_score(day, hour):
    base = DAY_OVERRIDES.get(day, {}).get(hour, WEEKDAY_CURVE.get(hour, 0.0))
    return round(min(1.2, base * DAY_FACTOR[day]), 3)


def observed_rates(earnings):
    """Average gross $/hr per (day, hour) from logged shifts."""
    totals = {}
    for e in earnings:
        dur = duration(e["start"], e["end"])
        if dur <= 0:
            continue
        rate = e["gross"] / dur
        for h, part in slot_hours(e["start"], e["end"]).items():
            pay, hrs, n = totals.get((e["day"], h), (0.0, 0.0, 0))
            totals[(e["day"], h)] = (pay + rate * part, hrs + part, n + 1)
    return {k: (pay / hrs, n) for k, (pay, hrs, n) in totals.items() if hrs}


def demand_score(day, hour, rates, settings):
    """Prior estimate blended with your own logged $/hr (more logs = more weight)."""
    prior = prior_score(day, hour)
    if (day, hour) not in rates:
        return prior
    rate, n = rates[(day, hour)]
    seen = max(0.0, min(1.2, rate / settings["reference_rate"]))
    weight = n / (n + 3.0)
    return round(prior * (1 - weight) + seen * weight, 3)


def strategy_for(day, hour):
    """Restaurants at meal peaks, groceries in the afternoon lull, fast food late."""
    if hour >= 21:
        return LATE
    if 14 <= hour < 16 or (hour == 16 and day not in ("Sunday", "Saturday")):
        return SHOP
    return STANDARD


def is_protected(day, hour, settings, when=None, outlook=None):
    """Days off, family time, Post One mowing (from opening day), and severe-weather warnings."""
    if day in settings["days_off"]:
        return True
    for p in settings["protected"]:
        if p["day"] != day:
            continue
        s, e = span(p["start"], p["end"])
        if overlap(s, e, hour, hour + 1) > 0:
            return True
    if when is not None:
        block = mowing_block(when, settings)
        if block and overlap(block[0], block[1], hour, hour + 1) > 0:
            return True
        if outlook and outlook.stop(when, hour):
            return True
    return False


def week_dates(start):
    """Seven days from `start`, keyed by weekday name."""
    start = to_date(start)
    return {DAYS[(start + timedelta(days=i)).weekday()]: start + timedelta(days=i) for i in range(7)}


# ---------- the planner ----------

def build_week(settings, earnings, start=None, outlook=None, now=None):
    """Pick the strongest hours of the week up to the goal, then merge into shifts.

    With a start date, the plan is for those real days: Post One hours, local events
    and the NWS forecast (outlook) count. Without one it's a typical week.
    Hours below min_score are never used to pad the goal: if the good hours run
    out, the plan comes in under goal and says so.
    """
    rates = observed_rates(earnings)
    dates = week_dates(start) if start else {}
    outlook = outlook or Outlook()
    now = now or datetime.now(CENTRAL)
    candidates = []
    for day in DAYS:
        when = dates.get(day)
        for hour in HOURS:
            if when == now.date() and hour < now.hour:
                continue  # already gone today
            if is_protected(day, hour, settings, when, outlook):
                continue
            score = demand_score(day, hour, rates, settings)
            if when:
                score = round(score * outlook.factor(when, hour), 3)
            if score >= settings["min_score"]:
                candidates.append((score, day, hour))
    candidates.sort(key=lambda c: (-c[0], DAYS.index(c[1]), c[2]))

    picked = {day: set() for day in DAYS}
    total = 0
    for score, day, hour in candidates:
        if total >= settings["weekly_goal_hours"]:
            break
        if len(picked[day]) >= settings["max_hours_per_day"]:
            continue
        picked[day].add(hour)
        total += 1

    schedule = {}
    for day in DAYS:
        shifts = []
        for block in contiguous(sorted(picked[day])):
            # A lone weak hour isn't worth the drive in: keep 1-hour blocks only at real peaks.
            if len(block) == 1 and prior_score(day, block[0]) < 0.8:
                continue
            shifts.extend(split_by_strategy(day, block))
        schedule[day] = shifts
    return schedule


def contiguous(hours):
    blocks, current = [], []
    for h in hours:
        if current and h != current[-1] + 1:
            blocks.append(current)
            current = []
        current.append(h)
    if current:
        blocks.append(current)
    return blocks


def split_by_strategy(day, block):
    shifts = []
    for h in block:
        strat = strategy_for(day, h)
        if shifts and shifts[-1]["strategy"] == strat:
            shifts[-1]["end"] = fmt(h + 1)
        else:
            shifts.append({"start": fmt(h), "end": fmt(h + 1), "strategy": strat})
    return shifts


# ---------- checks ----------

def shift_warnings(day, shift, rates=None, settings=None):
    """Flag restaurant shifts that sit in dead hours, and late-night runs too early."""
    rates = rates or {}
    settings = settings or DEFAULT_SETTINGS
    warnings = []
    covered = slot_hours(shift["start"], shift["end"])
    if shift["strategy"] == STANDARD:
        dead = [h for h in covered if demand_score(day, h, rates, settings) < DEAD_SCORE]
        if dead:
            first, last = min(dead), max(dead) + 1
            warnings.append(f"{fmt(first)}-{fmt(last)} is a dead zone for restaurant orders; "
                            f"switch that part to Shop & Deliver or take a break")
    if shift["strategy"] == LATE and min(covered) < 20:
        warnings.append("Late-night fast food rarely pays before 9 PM; use Standard Delivery first")
    return warnings


# ---------- earnings ----------

def earnings_summary(earnings, settings):
    hours = sum(duration(e["start"], e["end"]) for e in earnings)
    gross = sum(e["gross"] for e in earnings)
    miles = sum(e.get("miles", 0) for e in earnings)
    car = miles * settings["car_cost_per_mile"]
    return {
        "shifts": len(earnings),
        "hours": hours,
        "gross": gross,
        "miles": miles,
        "gross_per_hour": gross / hours if hours else 0.0,
        "net_per_hour": (gross - car) / hours if hours else 0.0,
        "per_mile": gross / miles if miles else 0.0,
        "car_cost": car,
        "irs_deduction": miles * settings["irs_rate_per_mile"],
    }


def best_blocks(earnings, top=5):
    """Your best and worst (day, strategy) blocks by real $/hr."""
    groups = {}
    for e in earnings:
        key = (e["day"], e.get("strategy", STANDARD))
        pay, hrs = groups.get(key, (0.0, 0.0))
        groups[key] = (pay + e["gross"], hrs + duration(e["start"], e["end"]))
    ranked = sorted(((pay / hrs, day, strat, hrs) for (day, strat), (pay, hrs) in groups.items() if hrs),
                    reverse=True)
    return ranked[:top], ranked[-top:][::-1] if len(ranked) > top else []


# ---------- screens ----------

def clear_screen():
    if sys.stdout.isatty():
        os.system("cls" if os.name == "nt" else "clear")


def plan_days(schedule, settings, start=None, outlook=None):
    """The week in calendar order: day, date, shifts and that day's notes."""
    dates = week_dates(start) if start else {}
    order = sorted(DAYS, key=lambda d: dates[d]) if dates else DAYS
    outlook = outlook or Outlook()
    return [{
        "day": day,
        "date": dates[day].isoformat() if day in dates else None,
        "shifts": schedule.get(day, []),
        "hours": sum(duration(s["start"], s["end"]) for s in schedule.get(day, [])),
        "notes": outlook.notes(dates[day], settings) if day in dates else [],
    } for day in order]


def render_plan(schedule, settings, earnings, auto=False, start=None, outlook=None):
    rates = observed_rates(earnings)
    title = f"WEEK OF {to_date(start):%b %d, %Y}" if start else "TYPICAL WEEK"
    lines = ["=" * 72, f" ATASCOCITA / HUMBLE DOORDASH PLAN: {title}", "=" * 72]
    if outlook and outlook.error:
        lines.append(f" ({outlook.error})")
    total = 0.0
    for entry in plan_days(schedule, settings, start, outlook):
        day, shifts, day_hours = entry["day"], entry["shifts"], entry["hours"]
        total += day_hours
        label = f"{day.upper()} {to_date(entry['date']):%b %d}" if entry["date"] else day.upper()
        lines.append(f"\n{label}  ({day_hours:.1f} hrs)")
        for note in entry["notes"]:
            lines.append(f"  * {note}")
        if not shifts:
            lines.append("  Off")
            continue
        for i, s in enumerate(shifts, 1):
            s_h, e_h = span(s["start"], s["end"])
            lines.append(f"  [{i}] {fmt12(s_h):>8} - {fmt12(e_h):<8} {s['strategy']:<21} "
                         f"| wait near: {HOTSPOTS[s['strategy']].split(';')[0]}")
            for w in shift_warnings(day, s, rates, settings):
                lines.append(f"      ! {w}")
    goal = settings["weekly_goal_hours"]
    lines += ["", "=" * 72,
              f" PLANNED HOURS: {total:.1f} of {goal:.0f}-hr goal ({total / goal * 100:.0f}%)" if goal else
              f" PLANNED HOURS: {total:.1f}"]
    if auto and total < goal:
        lines.append(f" The rest of the week is below your {settings['min_score']:.2f} demand bar;"
                     " those hours would pull your $/hr down.")
    if earnings:
        s = earnings_summary(earnings, settings)
        lines.append(f" YOUR NUMBERS: ${s['gross_per_hour']:.2f}/hr gross, "
                     f"${s['net_per_hour']:.2f}/hr after car cost, {s['shifts']} shifts logged")
    lines.append("=" * 72)
    return "\n".join(lines)


def ask(prompt, cast=str, default=None):
    raw = input(prompt).strip()
    if not raw and default is not None:
        return default
    return cast(raw)


def ask_day():
    day = input("Day (e.g. Friday): ").strip().capitalize()
    if day not in DAYS:
        raise ValueError(f"Not a day: {day!r}")
    return day


def ask_times():
    start = input("Start (24h, e.g. 17:00): ").strip()
    end = input("End (24h, e.g. 21:00; 00:30 = past midnight): ").strip()
    duration(start, end)  # validates
    return start, end


def ask_strategy():
    for i, s in enumerate(STRATEGIES, 1):
        print(f"  {i}. {s}")
    choice = ask("Strategy (1-3): ", int)
    return STRATEGIES[choice - 1]


def menu_auto(schedule, settings, earnings):
    print("Checking the National Weather Service forecast for Atascocita...")
    start, outlook = today(), fetch()
    new = build_week(settings, earnings, start, outlook)
    print(render_plan(new, settings, earnings, auto=True, start=start, outlook=outlook))
    if input("\nReplace your current schedule with this plan? (y/n): ").strip().lower() == "y":
        schedule.clear()
        schedule.update(new)
        save_json(SCHEDULE_FILE, schedule)
        print("[SAVED]")


def menu_add(schedule, settings, earnings):
    day = ask_day()
    start, end = ask_times()
    shift = {"start": start, "end": end, "strategy": ask_strategy()}
    s, e = span(start, end)
    for other in schedule[day]:
        if overlap(s, e, *span(other["start"], other["end"])) > 0:
            raise ValueError(f"Overlaps your {other['start']}-{other['end']} shift")
    schedule[day].append(shift)
    schedule[day].sort(key=lambda x: parse_time(x["start"]))
    save_json(SCHEDULE_FILE, schedule)
    for w in shift_warnings(day, shift, observed_rates(earnings), settings):
        print(f"[WARN] {w}")
    print("[SAVED]")


def menu_remove(schedule, settings, earnings):
    day = ask_day()
    if not schedule[day]:
        print("Nothing scheduled that day.")
        return
    for i, s in enumerate(schedule[day], 1):
        print(f"  {i}. {s['start']}-{s['end']} {s['strategy']}")
    idx = ask("Remove which (0 = all): ", int)
    if idx == 0:
        schedule[day] = []
    else:
        schedule[day].pop(idx - 1)
    save_json(SCHEDULE_FILE, schedule)
    print("[SAVED]")


def menu_log(schedule, settings, earnings):
    print("Log a finished dash (numbers from the Dasher app's earnings screen).")
    date = input("Date (YYYY-MM-DD): ").strip()
    day = ask_day()
    start, end = ask_times()
    entry = {
        "date": date, "day": day, "start": start, "end": end,
        "strategy": ask_strategy(),
        "gross": ask("Total earned incl. tips ($): ", float),
        "miles": ask("Miles driven (dash start to end): ", float, 0.0),
        "deliveries": ask("Deliveries: ", int, 0),
    }
    earnings.append(entry)
    save_json(EARNINGS_FILE, earnings)
    rate = entry["gross"] / duration(start, end)
    print(f"[SAVED] ${rate:.2f}/hr this dash. The planner will weigh it next build.")


def menu_report(schedule, settings, earnings):
    if not earnings:
        print("No dashes logged yet. Log a few and this report fills in.")
        return
    s = earnings_summary(earnings, settings)
    print(f"\nShifts: {s['shifts']}   Hours: {s['hours']:.1f}   Miles: {s['miles']:.0f}")
    print(f"Gross: ${s['gross']:.2f}   ${s['gross_per_hour']:.2f}/hr   ${s['per_mile']:.2f}/mile")
    print(f"After car cost (${settings['car_cost_per_mile']:.2f}/mi): ${s['net_per_hour']:.2f}/hr")
    print(f"Mileage deduction at IRS ${settings['irs_rate_per_mile']:.3f}/mi: ${s['irs_deduction']:.2f} "
          "(keep a mileage log; ask a tax pro)")
    best, worst = best_blocks(earnings)
    print("\nBest blocks:")
    for rate, day, strat, hrs in best:
        print(f"  {day:<10} {strat:<21} ${rate:.2f}/hr over {hrs:.1f} hrs")
    if worst:
        print("Weakest blocks (consider dropping):")
        for rate, day, strat, hrs in worst:
            print(f"  {day:<10} {strat:<21} ${rate:.2f}/hr over {hrs:.1f} hrs")


def menu_settings(schedule, settings, earnings):
    print(json.dumps(settings, indent=2))
    print("\n1. Weekly goal hours  2. Max hours/day  3. Add protected time  "
          "4. Clear protected time  5. Days off  6. Car cost/mile  7. Back")
    c = input("Choice: ").strip()
    if c == "1":
        settings["weekly_goal_hours"] = ask("Goal hours: ", float)
    elif c == "2":
        settings["max_hours_per_day"] = ask("Max hours per day: ", float)
    elif c == "3":
        day = ask_day()
        start, end = ask_times()
        settings["protected"].append({"day": day, "start": start, "end": end})
    elif c == "4":
        settings["protected"] = []
    elif c == "5":
        raw = input("Days off, comma separated (blank = none): ")
        days = [d.strip().capitalize() for d in raw.split(",") if d.strip()]
        bad = [d for d in days if d not in DAYS]
        if bad:
            raise ValueError(f"Not days: {bad}")
        settings["days_off"] = days
    elif c == "6":
        settings["car_cost_per_mile"] = ask("Car cost per mile ($): ", float)
    else:
        return
    save_json(SETTINGS_FILE, settings)
    print("[SAVED]")


MENU = [
    ("Build my week (auto)", menu_auto),
    ("Add a shift", menu_add),
    ("Remove a shift / clear a day", menu_remove),
    ("Log a finished dash", menu_log),
    ("Earnings report", menu_report),
    ("Settings (goal, family time, days off)", menu_settings),
]


def today():
    return datetime.now(CENTRAL).date()


def today_plan(schedule, settings, earnings, outlook):
    """Today's shifts (your saved schedule if it has any, else the auto plan) and notes."""
    start = today()
    day = DAYS[start.weekday()]
    auto = not schedule.get(day)
    plan = build_week(settings, earnings, start, outlook) if auto else schedule
    entry = plan_days(plan, settings, start, outlook)[0]
    return dict(entry, source="auto plan" if auto else "your schedule",
                weather_error=outlook.error, hotspots={s["strategy"]: HOTSPOTS[s["strategy"]] for s in entry["shifts"]})


def main(argv):
    import argparse
    parser = argparse.ArgumentParser(description="Atascocita DoorDash schedule planner")
    parser.add_argument("--plan", action="store_true", help="print the auto plan and exit")
    parser.add_argument("--week", help="plan the 7 days from this date (YYYY-MM-DD): events + Post One hours")
    parser.add_argument("--weather", action="store_true", help="plan the next 7 days with the NWS forecast")
    parser.add_argument("--today", action="store_true", help="just today's shifts and notes")
    parser.add_argument("--json", action="store_true", help="machine-readable output (for the pane and page)")
    args = parser.parse_args(argv)

    settings = load_settings()
    earnings = load_json(EARNINGS_FILE, [])
    schedule = load_schedule()

    if args.today:
        result = today_plan(schedule, settings, earnings, fetch())
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"{result['day']} {result['date']} ({result['source']}):")
            for s in result["shifts"]:
                print(f"  {fmt12(span(s['start'], s['end'])[0])}-{fmt12(span(s['start'], s['end'])[1])}  {s['strategy']}")
            for n in result["notes"]:
                print(f"  * {n}")
            if not result["shifts"]:
                print("  Off today.")
        return 0

    if args.plan or args.week or args.weather:
        start = to_date(args.week) if args.week else (today() if args.weather else None)
        outlook = fetch() if args.weather else Outlook()
        plan = build_week(settings, earnings, start, outlook)
        if args.json:
            print(json.dumps({
                "start": start.isoformat() if start else None,
                "goal_hours": settings["weekly_goal_hours"],
                "weather_error": outlook.error,
                "days": plan_days(plan, settings, start, outlook),
                "hotspots": HOTSPOTS,
                "demand": {day: {h: prior_score(day, h) for h in HOURS} for day in DAYS},
            }, indent=2))
        else:
            print(render_plan(plan, settings, earnings, auto=True, start=start, outlook=outlook))
        return 0

    while True:
        clear_screen()
        print(render_plan(schedule, settings, earnings))
        for i, (label, _) in enumerate(MENU, 1):
            print(f" {i}. {label}")
        print(f" {len(MENU) + 1}. Exit")
        choice = input("Select: ").strip()
        if choice == str(len(MENU) + 1):
            print("\nDrive safe on FM 1960.")
            return 0
        if choice.isdigit() and 1 <= int(choice) <= len(MENU):
            try:
                MENU[int(choice) - 1][1](schedule, settings, earnings)
            except (ValueError, IndexError) as e:
                print(f"[ERROR] {e}")
        input("\nPress Enter to continue...")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
