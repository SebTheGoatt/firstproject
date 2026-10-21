import itertools

import httpx
import pytest

from app.routing import haversine_matrix, optimize_route, solve_tsp
from app.routing.matrix import TravelMatrix, build_matrix

BASE = (30.0799, -95.4172)


def brute_force_cost(matrix: TravelMatrix, cost_key: str) -> int:
    cost = getattr(matrix, cost_key)
    n = len(cost)
    best = None
    for perm in itertools.permutations(range(1, n - 1)):
        path = [0, *perm, n - 1]
        c = sum(cost[a][b] for a, b in zip(path, path[1:]))
        best = c if best is None else min(best, c)
    return best


def path_cost(matrix: TravelMatrix, order: list[int], cost_key: str) -> int:
    cost = getattr(matrix, cost_key)
    path = [0, *order, len(cost) - 1]
    return sum(cost[a][b] for a, b in zip(path, path[1:]))


def test_points_on_a_line_are_visited_in_order():
    # Stops due north of the base, given scrambled. Start and end at base.
    stops = [(30.20, -95.4172), (30.10, -95.4172), (30.15, -95.4172)]
    result = optimize_route(BASE, BASE, stops, osrm_url=None, time_limit_s=1)
    visited = [r.stop_index for r in result.order]
    assert visited in ([1, 2, 0], [0, 2, 1])  # out-and-back either way is optimal


@pytest.mark.parametrize("cost_key", ["durations_s", "distances_m"])
def test_solver_matches_brute_force(cost_key):
    stops = [(30.13, -95.45), (30.045, -95.38), (30.11, -95.44), (30.06, -95.39), (30.09, -95.41), (30.02, -95.47)]
    end = (30.05, -95.50)  # distinct end point
    m = haversine_matrix([BASE, *stops, end])
    order = solve_tsp(m, "duration" if cost_key == "durations_s" else "distance", time_limit_s=1)
    assert sorted(order) == list(range(1, len(stops) + 1))
    assert path_cost(m, order, cost_key) == brute_force_cost(m, cost_key)


def test_empty_and_single_stop():
    empty = optimize_route(BASE, BASE, [], osrm_url=None)
    assert empty.order == [] and empty.total_distance_m == 0

    one = optimize_route(BASE, BASE, [(30.1, -95.4)], osrm_url=None)
    assert [l.stop_index for l in one.order] == [0]
    assert one.total_distance_m == one.order[0].distance_m + one.return_distance_m


def test_osrm_failure_falls_back_to_haversine():
    def boom(request):
        raise httpx.ConnectError("down")

    client = httpx.Client(transport=httpx.MockTransport(boom))
    m = build_matrix([BASE, (30.1, -95.4)], "https://osrm.invalid", client)
    assert m.source == "haversine"


def test_osrm_response_is_parsed_and_nulls_are_penalized():
    def handler(request):
        assert "/table/v1/driving/-95.417200,30.079900;" in str(request.url)
        return httpx.Response(200, json={
            "code": "Ok",
            "distances": [[0, 1000.4], [None, 0]],
            "durations": [[0, 90.6], [None, 0]],
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    m = build_matrix([BASE, (30.1, -95.4)], "https://osrm.test", client)
    assert m.source == "osrm"
    assert m.distances_m[0][1] == 1000 and m.durations_s[0][1] == 91
    assert m.distances_m[1][0] == 10**9


def test_exact_solver_finds_the_true_shortest_order_fast():
    import itertools
    import random
    import time

    from app.routing.solver import held_karp
    rng = random.Random(11)
    for n in (2, 4, 6, 7):
        pts = [(30 + rng.random() * 0.1, -95.4 + rng.random() * 0.1) for _ in range(n + 2)]
        c = haversine_matrix(pts).durations_s
        cost = lambda o: c[0][o[0]] + sum(c[a][b] for a, b in zip(o, o[1:])) + c[o[-1]][n + 1]
        assert cost(held_karp(c)) == min(cost(list(p)) for p in itertools.permutations(range(1, n + 1)))
    pts = [(30 + rng.random() * 0.1, -95.4 + rng.random() * 0.1) for _ in range(14)]
    t = time.perf_counter()
    assert sorted(solve_tsp(haversine_matrix(pts), time_limit_s=10)) == list(range(1, 13))
    assert time.perf_counter() - t < 2          # a 12-stop day no longer waits out the 10-second budget


def test_a_round_trip_tie_visits_the_nearer_stop_first():
    from app.routing.solver import held_karp
    #            base  near  far   base
    c = [[0, 1, 5, 0], [1, 0, 4, 1], [5, 4, 0, 5], [0, 1, 5, 0]]
    assert held_karp(c) == [1, 2]
