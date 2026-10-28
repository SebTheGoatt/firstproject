"""What changes a given week in Atascocita: Post One work hours, local events, and the weather.

All keyless public sources:
- National Weather Service hourly forecast and active alerts for the Atascocita point (api.weather.gov).
- Humble ISD 2026-27 calendar (board-approved Jan 13, 2026).
- Houston Texans 2026 home dates (City of Houston events page / FOX 26). Kickoff times weren't published
  when this was written, except Thursday night games, which start 7:15 PM Central.
The event factors are estimates; your logged earnings are the real test.
"""
import json
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
NWS_HOURLY = "https://api.weather.gov/gridpoints/HGX/70,105/forecast/hourly"   # Atascocita CDP grid point
NWS_ALERTS = "https://api.weather.gov/alerts/active?point=29.993,-95.1766"
USER_AGENT = "atascocita-dasher-planner (personal use)"

# Post One Lawn Co. working hours (property-dispatch/app/config.py and CLAUDE.md). The test suite fails if they
# drift apart. Opening day is the planned LAUNCH_DATE; change post_one_launch in settings once it's set in Render.
POST_ONE_LAUNCH = "2027-03-01"
POST_ONE_WEEKDAY = "08:00-17:00"
POST_ONE_SATURDAY = "08:00-14:00"

# Dated local events: (first day, last day, hours affected or None for all, demand factor, note).
EVENTS = [
    ("2026-11-19", "2026-11-19", range(17, 23), 1.15, "Texans vs Colts, Thursday night (7:15 PM): pre-game and halftime orders"),
    ("2026-11-23", "2026-11-27", range(10, 15), 1.10, "Humble ISD Thanksgiving break: kids home, weekday lunch picks up"),
    ("2026-11-26", "2026-11-26", range(10, 20), 0.70, "Thanksgiving Day: most families cook; few orders until evening"),
    ("2026-11-27", "2026-11-27", range(11, 21), 1.10, "Black Friday: shoppers order lunch and dinner"),
    ("2026-11-29", "2026-11-29", range(11, 21), 1.10, "Texans vs Ravens at home: game-day orders (kickoff time TBA)"),
    ("2026-12-20", "2026-12-20", range(11, 21), 1.10, "Texans vs Jaguars at home: game-day orders (kickoff time TBA)"),
    ("2026-12-21", "2027-01-01", range(10, 15), 1.10, "Humble ISD winter break: weekday lunch picks up"),
    ("2026-12-24", "2026-12-25", None, 1.00, "Christmas: many restaurants close and few Dashers work; watch the app for Peak Pay"),
    ("2026-12-31", "2026-12-31", range(19, 25), 1.10, "New Year's Eve: parties at home order in"),
    ("2027-01-10", "2027-01-10", range(11, 21), 1.10, "Texans vs Titans at home: game-day orders (kickoff time TBA)"),
]

# NWS alerts that mean stay off the road for the hours they cover.
STOP_ALERTS = {
    "Flash Flood Warning", "Flood Warning", "Tornado Warning", "Hurricane Warning",
    "Tropical Storm Warning", "Severe Thunderstorm Warning", "Ice Storm Warning", "Winter Storm Warning",
}


def to_date(value):
    return value if isinstance(value, date) else date.fromisoformat(value)


def slot_moment(day, hour):
    """The (date, hour) a planning slot really falls on: hour 24 is midnight of the next day."""
    return (day + timedelta(days=1), 0) if hour >= 24 else (day, hour)


def span_hours(text):
    start, end = text.split("-")
    h1, m1 = map(int, start.split(":"))
    h2, m2 = map(int, end.split(":"))
    return h1 + m1 / 60, h2 + m2 / 60


def mowing_block(day, settings):
    """Hours Post One mowing takes on this date (plus the drive home), or None before opening day / on Sundays."""
    launch = settings.get("post_one_launch") or POST_ONE_LAUNCH
    if day < to_date(launch) or day.weekday() == 6:
        return None
    start, end = span_hours(POST_ONE_SATURDAY if day.weekday() == 5 else POST_ONE_WEEKDAY)
    return start, end + settings.get("post_one_buffer_min", 30) / 60


def events_on(day):
    return [e for e in EVENTS if to_date(e[0]) <= day <= to_date(e[1])]


class Outlook:
    """Weather and alerts for the coming week. An empty Outlook (no network) changes nothing."""

    def __init__(self, hourly=None, alerts=None, error=None):
        self.hourly = hourly or {}      # (date, hour) -> (rain chance %, short forecast)
        self.alerts = alerts or []      # (start datetime, end datetime, event name)
        self.error = error

    def factor(self, day, hour):
        f = 1.0
        for _, _, hours, factor, _ in events_on(day):
            if hours is None or hour in hours:
                f *= factor
        rain, _ = self.hourly.get(slot_moment(day, hour), (0, ""))
        if rain >= 70:
            f *= 1.20        # people stay in and order; fewer Dashers out
        elif rain >= 40:
            f *= 1.10
        return f

    def stop(self, day, hour):
        """The alert name if a dangerous-weather warning covers this hour."""
        d, h = slot_moment(day, hour)
        start = datetime(d.year, d.month, d.day, h, tzinfo=CENTRAL)
        for a_start, a_end, name in self.alerts:
            if a_start < start + timedelta(hours=1) and start < a_end:
                return name
        return None

    def notes(self, day, settings):
        out = [e[4] for e in events_on(day)]
        block = mowing_block(day, settings)
        if block:
            out.append(f"Post One mowing until {clock(block[1] - settings.get('post_one_buffer_min', 30) / 60)}"
                       " (dash plan starts after you're home)")
        wet = [h for h in range(6, 25) if self.hourly.get(slot_moment(day, h), (0, ""))[0] >= 40]
        for first, last in runs(wet):
            out.append(f"Rain likely {clock(first)}-{clock(last + 1)}: orders usually rise. Slow down, lights on")
        if any(rain >= 30 and "thunder" in text.lower()
               for rain, text in (self.hourly.get(slot_moment(day, h), (0, "")) for h in range(6, 25))):
            out.append("Thunderstorms possible: wait out lightning; never drive into a flooded street")
        names = sorted({self.stop(day, h) for h in range(6, 25)} - {None})
        for name in names:
            out.append(f"{name}: those hours are off the plan. Stay home and stay safe")
        return out


def runs(hours):
    """[17, 18, 19, 22] -> [(17, 19), (22, 22)]."""
    out = []
    for h in sorted(hours):
        if out and h == out[-1][1] + 1:
            out[-1] = (out[-1][0], h)
        else:
            out.append((h, h))
    return out


def clock(hour):
    hour %= 24
    h, m = int(hour), int(round((hour % 1) * 60))
    return f"{(h % 12) or 12}{f':{m:02d}' if m else ''} {'AM' if h < 12 else 'PM'}"


def parse_hourly(periods):
    out = {}
    for p in periods:
        start = datetime.fromisoformat(p["startTime"]).astimezone(CENTRAL)
        rain = (p.get("probabilityOfPrecipitation") or {}).get("value") or 0
        out[(start.date(), start.hour)] = (rain, p.get("shortForecast", ""))
    return out


def parse_alerts(features):
    out = []
    for f in features:
        p = f["properties"]
        if p.get("event") not in STOP_ALERTS:
            continue
        start = p.get("onset") or p.get("effective")
        end = p.get("ends") or p.get("expires")
        if start and end:
            out.append((datetime.fromisoformat(start), datetime.fromisoformat(end), p["event"]))
    return out


def get_json(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch(timeout=15):
    """The NWS forecast (~7 days) and active alerts. Never raises: no network means a plain plan."""
    try:
        hourly = parse_hourly(get_json(NWS_HOURLY, timeout)["properties"]["periods"])
        alerts = parse_alerts(get_json(NWS_ALERTS, timeout).get("features", []))
        return Outlook(hourly, alerts)
    except Exception as e:  # network, proxy, or NWS outage
        return Outlook(error=f"Weather unavailable ({type(e).__name__}); plan uses normal demand")
