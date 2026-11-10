"""What a route is worth: savings over booking order, detours, the day as a timeline, and the solver's second pass."""
import random
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.route_insights import insights
from app.routing.matrix import TravelMatrix, haversine_matrix
from app.routing.solver import held_karp, path_cost, polish, solve_tsp

from .test_api_flow import CREW, NOW, TOMORROW, book
from .test_payments import route_stops

TZ = timezone(timedelta(hours=-6))
EIGHT = datetime(2026, 10, 15, 8, 0, tzinfo=TZ)


def line_matrix(xs):
    """Points on a line, 60 s and 1,000 m per unit apart: [base, stops..., end]."""
    d = [[abs(a - b) for b in xs] for a in xs]
    return TravelMatrix([[v * 1000 for v in r] for r in d], [[v * 60 for v in r] for r in d], "osrm")


def stops_for(n, booked, etas, minutes=30, done=()):
    return [{"stop_id": f"s{i}", "booked_at": booked[i - 1], "eta": etas[i - 1], "service_minutes": minutes,
             "done": i in done} for i in range(1, n + 1)]


def test_savings_lawn_share_detours_and_timeline():
    # Base at 0, stops at 1, 2, 3 in route order, back to 0. Bookings came in as stop 2, then 1, then 3.
    m = line_matrix([0, 1, 2, 3, 0])
    etas = [EIGHT, EIGHT + timedelta(minutes=31), EIGHT + timedelta(minutes=62)]
    r = insights(m, stops_for(3, ["b", "a", "c"], etas), close=EIGHT + timedelta(hours=9))
    assert r["drive_min"] == 6                     # 0→1→2→3→0 = 6 units
    assert r["saved_min"] == 2 and r["saved_m"] == 2000     # booking order 0→2→1→3→0 = 8 units
    assert r["lawn_share"] == round(90 / 96, 3)
    assert [d["seconds"] for d in r["detours"]] == [0, 0, 120] and r["over"] is None   # only the far end adds driving
    kinds = [(g["kind"], g["n"]) for g in r["timeline"]]
    assert kinds == [("drive", 1), ("stop", 1), ("drive", 2), ("stop", 2), ("drive", 3), ("stop", 3), ("return", None)]
    assert r["timeline"][0]["start"] == (EIGHT - timedelta(minutes=1)).isoformat()     # leaves base a minute early
    assert r["back_at_base"] == (EIGHT + timedelta(minutes=95)).isoformat()


def test_the_costliest_stop_is_the_one_off_the_path():
    m = line_matrix([0, 1, 9, 2, 0])               # stop 2 is far out of the way
    etas = [EIGHT, EIGHT + timedelta(minutes=40), EIGHT + timedelta(minutes=80)]
    r = insights(m, stops_for(3, ["a", "b", "c"], etas))
    assert r["costliest"]["n"] == 2 and r["costliest"]["seconds"] == (8 + 7 - 1) * 60


def test_a_day_past_closing_says_which_stops_to_move():
    m = line_matrix([0, 1, 9, 2, 0])
    etas = [EIGHT, EIGHT + timedelta(minutes=40), EIGHT + timedelta(minutes=80)]
    close = EIGHT + timedelta(minutes=100)         # the last lawn ends at 8:00 + 110
    r = insights(m, stops_for(3, ["a", "b", "c"], etas), close=close)
    assert r["over"] == {"minutes": 10, "move": [2], "fits": True}        # the far stop first
    done = insights(m, stops_for(3, ["a", "b", "c"], etas, done={2}), close=close)
    assert 2 not in done["over"]["move"]           # never suggests moving a finished lawn


def test_no_stops_or_a_mismatched_matrix_gives_nothing():
    assert insights(line_matrix([0, 0]), []) is None
    assert insights(line_matrix([0, 1, 0]), stops_for(2, ["a", "b"], [EIGHT, EIGHT])) is None


def test_the_second_pass_never_makes_a_route_longer_and_fixes_a_bad_one():
    random.seed(3)
    for n in (5, 9, 14, 22):
        pts = [(30.08, -95.42)] + [(30.0 + random.random() * 0.15, -95.6 + random.random() * 0.2) for _ in range(n)] + [(30.08, -95.42)]
        cost = [[int(v * (1 + 0.2 * random.random())) for v in row] for row in haversine_matrix(pts).durations_s]   # one-way differences
        shuffled = random.sample(range(1, n + 1), n)
        better = polish(cost, shuffled)
        assert sorted(better) == list(range(1, n + 1)) and path_cost(cost, better) <= path_cost(cost, shuffled)
        if n <= 9:      # small days: within 5% of the proven best
            assert path_cost(cost, better) <= path_cost(cost, held_karp(cost)) * 1.05
    assert polish([[0, 1], [1, 0]], []) == [] and path_cost([[0, 1], [1, 0]], []) == 0


def test_big_days_still_visit_every_stop_once():
    random.seed(5)
    pts = [(30.08, -95.42)] + [(30.0 + random.random() * 0.15, -95.6 + random.random() * 0.2) for _ in range(16)] + [(30.08, -95.42)]
    order = solve_tsp(haversine_matrix(pts), "duration", 2)
    assert sorted(order) == list(range(1, 17))


def test_the_dispatch_board_carries_the_scorecard(client, repo, settings):
    with patch("app.main.local_now", return_value=NOW):
        for i, letter in enumerate("EBDAC"):                       # booked in a scattered order
            assert book(client, letter, f"01{i:02d}").status_code == 201
    route_stops(client, repo, settings)
    with patch("app.dispatch_board.local_now", return_value=NOW):
        d = client.get(f"/api/owner/dispatch/{TOMORROW}", headers=CREW).json()
    ins = d["insights"]
    assert ins["source"] == "haversine" and len(ins["detours"]) == 5 and ins["saved_min"] >= 0
    assert 0 < ins["lawn_share"] < 1 and ins["costliest"]["stop_id"] in {s["stop_id"] for s in d["route"]["stops"]}
    assert [g["n"] for g in ins["timeline"] if g["kind"] == "stop"] == [1, 2, 3, 4, 5]
    assert "customer_name" not in str(ins)                         # numbers only
    page = client.get("/owner/dispatch").text
    assert 'id="deck"' in page and 'id="tl-track"' in page and ".hud[hidden]" in page
