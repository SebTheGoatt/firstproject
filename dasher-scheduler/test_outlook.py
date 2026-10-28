import os
import re
from datetime import date, datetime

import dasher_schedule as ds
import outlook as ol

CONFIG = os.path.join(os.path.dirname(__file__), "..", "property-dispatch", "app", "config.py")


def settings(**over):
    s = dict(ds.DEFAULT_SETTINGS, protected=[], days_off=[])
    s.update(over)
    return s


def shift_spans(plan, day):
    return [ds.span(s["start"], s["end"]) for s in plan[day]]


def test_post_one_hours_match_the_lawn_app():
    text = open(CONFIG).read()
    assert re.search(r'weekday_hours: str = "([^"]+)"', text).group(1) == ol.POST_ONE_WEEKDAY
    assert re.search(r'saturday_hours: str = "([^"]+)"', text).group(1) == ol.POST_ONE_SATURDAY


def test_no_dashing_during_post_one_hours_after_opening_day():
    plan = ds.build_week(settings(), [], start="2027-03-01")       # a Monday after launch
    for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
        assert all(start >= 17.5 for start, _ in shift_spans(plan, day)), day
    assert all(start >= 14.5 for start, _ in shift_spans(plan, "Saturday"))
    assert plan["Sunday"]                                            # Sunday stays open


def test_before_opening_day_weekdays_are_open():
    plan = ds.build_week(settings(), [], start="2026-11-02")
    assert any(start < 14 for start, _ in shift_spans(plan, "Monday"))


def test_thanksgiving_day_is_quieter_than_black_friday():
    o = ol.Outlook()
    assert o.factor(date(2026, 11, 26), 12) < 1 < o.factor(date(2026, 11, 27), 12)


def test_rain_raises_demand_and_notes_it():
    day = date(2026, 11, 3)
    o = ol.Outlook(hourly={(day, 18): (80, "Rain"), (day, 19): (80, "Rain")})
    assert o.factor(day, 18) > o.factor(day, 12)
    assert any("Rain likely 6 PM-8 PM" in n for n in o.notes(day, settings()))


def test_slight_chance_of_thunder_is_not_a_warning():
    day = date(2026, 11, 3)
    o = ol.Outlook(hourly={(day, 15): (17, "Slight Chance Showers And Thunderstorms")})
    assert not any("Thunder" in n for n in o.notes(day, settings()))


def test_flash_flood_warning_takes_hours_off_the_plan():
    alert = {"properties": {"event": "Flash Flood Warning", "onset": "2026-11-07T16:00:00-06:00",
                            "ends": "2026-11-07T22:00:00-06:00"}}
    o = ol.Outlook(alerts=ol.parse_alerts([alert, {"properties": {"event": "Heat Advisory"}}]))
    assert len(o.alerts) == 1
    plan = ds.build_week(settings(), [], start="2026-11-02", outlook=o)
    for start, end in shift_spans(plan, "Saturday"):
        assert ds.overlap(start, end, 16, 22) == 0


def test_parse_nws_hourly_period():
    got = ol.parse_hourly([{"startTime": "2026-10-31T18:00:00-05:00",
                            "probabilityOfPrecipitation": {"value": 60}, "shortForecast": "Showers"}])
    assert got == {(date(2026, 10, 31), 18): (60, "Showers")}


def test_hours_already_gone_today_are_skipped():
    now = datetime(2026, 11, 2, 15, 0, tzinfo=ol.CENTRAL)
    plan = ds.build_week(settings(), [], start="2026-11-02", now=now)
    assert all(start >= 15 for start, _ in shift_spans(plan, "Monday"))


def test_no_network_means_a_plain_plan(monkeypatch):
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(ol, "get_json", boom)
    o = ol.fetch()
    assert o.error and o.factor(date(2026, 11, 3), 12) == 1.0
