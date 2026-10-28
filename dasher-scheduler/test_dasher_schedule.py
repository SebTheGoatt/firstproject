import pytest

import dasher_schedule as ds


def settings(**over):
    s = dict(ds.DEFAULT_SETTINGS, protected=[], days_off=[])
    s.update(over)
    return s


def all_shifts(schedule):
    return [(day, s) for day, shifts in schedule.items() for s in shifts]


def test_duration_rolls_past_midnight():
    assert ds.duration("22:00", "01:00") == 3
    assert ds.duration("11:30", "13:30") == 2


@pytest.mark.parametrize("bad", ["25:00", "1130", "ab:cd", "12:60"])
def test_bad_times_rejected(bad):
    with pytest.raises(ValueError):
        ds.parse_time(bad)


def test_plan_stays_within_goal_and_daily_cap():
    plan = ds.build_week(settings(weekly_goal_hours=30, max_hours_per_day=6), [])
    hours = {d: sum(ds.duration(s["start"], s["end"]) for s in plan[d]) for d in ds.DAYS}
    assert sum(hours.values()) <= 30
    assert max(hours.values()) <= 6


def test_plan_never_pads_with_dead_hours():
    plan = ds.build_week(settings(weekly_goal_hours=200), [])
    for day, shift in all_shifts(plan):
        for h in ds.slot_hours(shift["start"], shift["end"]):
            assert ds.prior_score(day, h) >= 0.45


def test_auto_plan_has_no_warnings():
    plan = ds.build_week(settings(), [])
    assert all(not ds.shift_warnings(day, s) for day, s in all_shifts(plan))


def test_weekend_dinner_beats_tuesday_afternoon():
    assert ds.prior_score("Saturday", 18) > ds.prior_score("Tuesday", 15)


def test_restaurant_shift_in_afternoon_lull_warns():
    warnings = ds.shift_warnings("Wednesday", {"start": "13:00", "end": "17:00", "strategy": ds.STANDARD})
    assert warnings and "Shop & Deliver" in warnings[0]


def test_shop_and_deliver_in_lull_is_fine():
    assert not ds.shift_warnings("Wednesday", {"start": "14:00", "end": "16:00", "strategy": ds.SHOP})


def test_protected_time_and_days_off_respected():
    s = settings(days_off=["Tuesday"], protected=[{"day": "Saturday", "start": "17:00", "end": "20:00"}])
    plan = ds.build_week(s, [])
    assert plan["Tuesday"] == []
    for shift in plan["Saturday"]:
        start, end = ds.span(shift["start"], shift["end"])
        assert ds.overlap(start, end, 17, 20) == 0


def test_logged_earnings_move_the_plan():
    # Tuesday dinner keeps paying badly; Tuesday lunch keeps paying great.
    logs = [{"day": "Tuesday", "start": "17:00", "end": "20:00", "gross": 15.0, "strategy": ds.STANDARD}] * 6
    logs += [{"day": "Tuesday", "start": "11:00", "end": "14:00", "gross": 90.0, "strategy": ds.STANDARD}] * 6
    rates = ds.observed_rates(logs)
    s = settings()
    assert ds.demand_score("Tuesday", 18, rates, s) < ds.prior_score("Tuesday", 18)
    assert ds.demand_score("Tuesday", 12, rates, s) > ds.prior_score("Tuesday", 12)


def test_earnings_summary():
    logs = [{"day": "Friday", "start": "17:00", "end": "21:00", "gross": 100.0, "miles": 50}]
    s = ds.earnings_summary(logs, settings(car_cost_per_mile=0.30))
    assert s["gross_per_hour"] == 25.0
    assert s["net_per_hour"] == pytest.approx((100 - 15) / 4)
    assert s["per_mile"] == 2.0
