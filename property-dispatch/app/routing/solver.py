"""Single-vehicle TSP with fixed start and end.

Up to EXACT_MAX_STOPS stops (a normal day) the route is solved exactly with Held-Karp dynamic programming:
provably the shortest order, in milliseconds. Bigger days use Google OR-Tools guided local search, whose time
budget scales with the number of stops (it always runs to its limit, so a flat 10s made every replan wait 10s).

Node layout passed to OR-Tools:
    0            → start (business base)
    1 .. n       → job stops
    n + 1        → end point (may share coordinates with the start)
"""

from dataclasses import dataclass

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from .matrix import LatLng, TravelMatrix, build_matrix


@dataclass
class Leg:
    stop_index: int        # index into the caller's `stops` list
    distance_m: int        # from previous point
    duration_s: int


@dataclass
class OptimizedRoute:
    order: list[Leg]           # visit sequence (excludes start/end)
    return_distance_m: int     # last stop → end point
    return_duration_s: int
    total_distance_m: int
    total_duration_s: int      # drive time only
    matrix_source: str


EXACT_MAX_STOPS = 12


def held_karp(cost) -> list[int]:
    """Exact shortest path 0 → every stop once → n+1 (nodes as in the module docstring). O(2^n · n²)."""
    n = len(cost) - 2
    full = (1 << n) - 1
    # best[mask][j]: cheapest way to start at 0, visit the stops in mask, and stand at stop j (bit j-1)
    best = [[None] * (n + 1) for _ in range(1 << n)]
    prev = [[0] * (n + 1) for _ in range(1 << n)]
    for j in range(1, n + 1):
        best[1 << (j - 1)][j] = cost[0][j]
    for mask in range(1, full + 1):
        row = best[mask]
        for j in range(1, n + 1):
            here = row[j]
            if here is None:
                continue
            for k in range(1, n + 1):
                bit = 1 << (k - 1)
                if mask & bit:
                    continue
                c = here + cost[j][k]
                nxt = best[mask | bit]
                if nxt[k] is None or c < nxt[k]:
                    nxt[k] = c
                    prev[mask | bit][k] = j
    end = n + 1
    last = min(range(1, n + 1), key=lambda j: best[full][j] + cost[j][end])
    order, mask = [], full
    while last:
        order.append(last)
        last, mask = prev[mask][last], mask & ~(1 << (last - 1))
    order.reverse()
    # A round trip is often a tie with its own reverse; then go to the nearer stop first (someone gets mowed sooner).
    total = lambda o: cost[0][o[0]] + sum(cost[a][b] for a, b in zip(o, o[1:])) + cost[o[-1]][end]
    back = order[::-1]
    if total(back) == total(order) and cost[0][back[0]] < cost[0][order[0]]:
        return back
    return order


def solve_tsp(matrix: TravelMatrix, optimize_for: str = "duration", time_limit_s: int = 10) -> list[int]:
    """Return node indices in visit order, start and end excluded."""
    size = len(matrix.distances_m)
    stops = size - 2
    if stops <= 0:
        return []
    if stops == 1:
        return [1]

    cost = matrix.durations_s if optimize_for == "duration" else matrix.distances_m
    if stops <= EXACT_MAX_STOPS:
        return held_karp(cost)
    manager = pywrapcp.RoutingIndexManager(size, 1, [0], [size - 1])
    routing = pywrapcp.RoutingModel(manager)

    def transit(from_index: int, to_index: int) -> int:
        return cost[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    cb = routing.RegisterTransitCallback(transit)
    routing.SetArcCostEvaluatorOfAllVehicles(cb)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = min(time_limit_s, 1 + stops // 8)    # 25 stops: 4s; never more than the setting

    solution = routing.SolveWithParameters(params)
    if solution is None:
        raise RuntimeError("OR-Tools found no route")

    order: list[int] = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        if node != 0:
            order.append(node)
        index = solution.Value(routing.NextVar(index))
    return order


def optimize_route(
    start: LatLng,
    end: LatLng,
    stops: list[LatLng],
    *,
    osrm_url: str | None,
    optimize_for: str = "duration",
    time_limit_s: int = 10,
    matrix: TravelMatrix | None = None,
) -> OptimizedRoute:
    points = [start, *stops, end]
    matrix = matrix or build_matrix(points, osrm_url)
    node_order = solve_tsp(matrix, optimize_for, time_limit_s)

    legs: list[Leg] = []
    prev = 0
    for node in node_order:
        legs.append(Leg(node - 1, matrix.distances_m[prev][node], matrix.durations_s[prev][node]))
        prev = node
    end_node = len(points) - 1
    ret_d = matrix.distances_m[prev][end_node] if stops else 0
    ret_t = matrix.durations_s[prev][end_node] if stops else 0

    return OptimizedRoute(
        order=legs,
        return_distance_m=ret_d,
        return_duration_s=ret_t,
        total_distance_m=sum(l.distance_m for l in legs) + ret_d,
        total_duration_s=sum(l.duration_s for l in legs) + ret_t,
        matrix_source=matrix.source,
    )
