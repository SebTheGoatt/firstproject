"""What a built route is worth, and where its time goes (for the owner's dispatch board).

    insights(matrix, stops, close)   -> scorecard, per-stop detours, the day as timeline segments

`matrix` covers [base, stop 1..n in route order, end]. Everything is arithmetic on the same travel times the
route was built from, so the numbers agree with the route itself:

- saved: the day's driving in the order bookings came in, minus the optimized order. What planning bought.
- lawn_share: time on lawns / (time on lawns + driving). The crew is paid to mow, not to drive.
- detour: for each stop, the driving it adds = (previous -> stop -> next) - (previous -> next). The costliest
  stop is the one a neighbor's booking would make cheap (the neighbor discount exists for exactly this).
- over: when the day ends after closing, the fewest stops to move so it fits, costliest detours first.
- timeline: drive and lawn segments from leaving base to getting back, for the day strip.
"""

from datetime import datetime, timedelta


def _total(cost, order: list[int]) -> int:
    if not order:
        return 0
    end = len(cost) - 1
    return cost[0][order[0]] + sum(cost[a][b] for a, b in zip(order, order[1:])) + cost[order[-1]][end]


def insights(matrix, stops: list[dict], close: datetime | None = None) -> dict | None:
    """`stops`: route order, each {"stop_id", "booked_at", "eta" (datetime | None), "service_minutes", "done"}."""
    n = len(stops)
    if n == 0 or len(matrix.durations_s) != n + 2:
        return None
    dur, dist = matrix.durations_s, matrix.distances_m
    order = list(range(1, n + 1))
    by_booking = sorted(order, key=lambda i: (stops[i - 1].get("booked_at") or "", i))
    drive_s, drive_m = _total(dur, order), _total(dist, order)
    on_site_s = sum((s.get("service_minutes") or 0) * 60 for s in stops)

    detours = []
    for i in order:
        prev, nxt = i - 1, i + 1                       # node 0 is base, node n+1 the end point
        detours.append({"stop_id": stops[i - 1]["stop_id"], "n": i,
                        "seconds": max(0, dur[prev][i] + dur[i][nxt] - dur[prev][nxt]),
                        "meters": max(0, dist[prev][i] + dist[i][nxt] - dist[prev][nxt])})
    costliest = max(detours, key=lambda d: d["seconds"]) if n > 1 else None

    # The day as segments. Stops with an ETA anchor it; a drive runs from the previous segment's end to the ETA.
    timeline, cursor = [], None
    for i, s in enumerate(stops, start=1):
        eta = s.get("eta")
        if eta is None:
            continue
        drive_start = eta - timedelta(seconds=dur[i - 1][i]) if cursor is None else cursor
        if eta > drive_start:
            timeline.append({"kind": "drive", "start": drive_start.isoformat(), "end": eta.isoformat(), "n": i})
        end = eta + timedelta(minutes=s.get("service_minutes") or 0)
        timeline.append({"kind": "stop", "start": eta.isoformat(), "end": end.isoformat(), "n": i,
                         "stop_id": s["stop_id"], "done": bool(s.get("done"))})
        cursor = end
    back = None
    if cursor is not None:
        back = cursor + timedelta(seconds=dur[n][n + 1])
        if back > cursor:
            timeline.append({"kind": "return", "start": cursor.isoformat(), "end": back.isoformat(), "n": None})

    over = None
    if close is not None and cursor is not None and cursor > close:
        need, moved = (cursor - close).total_seconds(), []
        for d in sorted(detours, key=lambda d: -d["seconds"]):
            if need <= 0:
                break
            s = stops[d["n"] - 1]
            if s.get("done"):
                continue
            need -= d["seconds"] + (s.get("service_minutes") or 0) * 60
            moved.append(d["n"])
        over = {"minutes": round((cursor - close).total_seconds() / 60), "move": sorted(moved), "fits": need <= 0}

    return {
        "source": matrix.source,
        "drive_min": round(drive_s / 60), "drive_m": drive_m,
        "saved_min": max(0, round((_total(dur, by_booking) - drive_s) / 60)),
        "saved_m": max(0, _total(dist, by_booking) - drive_m),
        "lawn_share": round(on_site_s / (on_site_s + drive_s), 3) if on_site_s + drive_s else None,
        "detours": detours, "costliest": costliest,
        "back_at_base": back.isoformat() if back else None,
        "timeline": timeline, "over": over,
    }
