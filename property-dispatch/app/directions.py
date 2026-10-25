"""Turn-by-turn driving directions for the crew dashboard's in-app navigation.

Uses the same OSRM road network as route planning (settings.osrm_url) and turns each
maneuver into a short spoken-style instruction ("Turn left onto Kuykendahl Rd").
"""

import httpx

LatLng = tuple[float, float]


class DirectionsUnavailable(Exception):
    pass


def _onto(name: str, ref: str | None) -> str:
    road = name or ref or ""
    return f" onto {road}" if road else ""


def _cardinal(bearing: float | None) -> str:
    if bearing is None:
        return ""
    return ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"][round(bearing / 45) % 8]


def instruction(step: dict) -> str:
    m = step.get("maneuver", {})
    kind, mod = m.get("type", ""), (m.get("modifier") or "").strip()
    name, ref = step.get("name") or "", step.get("ref")
    onto = _onto(name, ref)
    if kind == "depart":
        way = _cardinal(m.get("bearing_after"))
        return f"Head {way}{' on ' + (name or ref) if (name or ref) else ''}".replace("Head  ", "Head ").strip()
    if kind == "arrive":
        side = f" on the {mod}" if mod in ("left", "right") else ""
        return f"Arrive at the stop{side}"
    if kind in ("roundabout", "rotary"):
        n = m.get("exit")
        return f"At the roundabout, take the {_ordinal(n)} exit{onto}" if n else f"Enter the roundabout{onto}"
    if kind == "merge":
        return f"Merge{(' ' + mod) if mod in ('left', 'right') else ''}{onto}"
    side = "left" if "left" in mod else "right" if "right" in mod else ""
    if kind == "on ramp":
        return f"Take the ramp{(' on the ' + side) if side else ''}{onto}"
    if kind == "off ramp":
        return f"Take the exit{(' on the ' + side) if side else ''}{onto}"
    if kind == "fork":
        return f"Keep {'left' if 'left' in mod else 'right' if 'right' in mod else 'straight'} at the fork{onto}"
    if mod == "uturn":
        return f"Make a U-turn{onto}"
    if mod == "straight" or kind in ("new name", "continue") and mod in ("", "straight"):
        return f"Continue straight{onto}" if onto else "Continue straight"
    if mod:
        verb = "Turn" if "slight" not in mod else "Bear"
        return f"{verb} {mod.replace('slight ', '')}{onto}"
    return f"Continue{onto}"


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _http() -> httpx.Client:
    return httpx.Client(timeout=12)


def get_directions(osrm_url: str, origin: LatLng, dest: LatLng, client: httpx.Client | None = None) -> dict:
    """origin/dest are (lat, lng). Returns the road path (GeoJSON [lng, lat] pairs) and the steps."""
    if not osrm_url:
        raise DirectionsUnavailable("Turn-by-turn directions aren't set up (no OSRM_URL).")
    coords = f"{origin[1]:.6f},{origin[0]:.6f};{dest[1]:.6f},{dest[0]:.6f}"
    http = client or _http()
    try:
        resp = http.get(f"{osrm_url}/route/v1/driving/{coords}",
                        params={"overview": "full", "geometries": "geojson", "steps": "true"})
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise DirectionsUnavailable("The directions service didn't answer. Try again, or use Google Maps.") from exc
    if data.get("code") != "Ok" or not data.get("routes"):
        raise DirectionsUnavailable("No driving route was found to this stop.")
    route = data["routes"][0]
    steps = [{
        "instruction": instruction(s),
        "road": s.get("name") or s.get("ref") or "",
        "distance_m": round(s.get("distance", 0)),
        "duration_s": round(s.get("duration", 0)),
        "location": s["maneuver"]["location"],          # [lng, lat] where this maneuver happens
        "type": s["maneuver"].get("type"),
        "modifier": s["maneuver"].get("modifier"),
    } for leg in route["legs"] for s in leg["steps"]]
    return {"distance_m": round(route["distance"]), "duration_s": round(route["duration"]),
            "path": route["geometry"]["coordinates"], "steps": steps}


def route_path(osrm_url: str, points: list[LatLng], client: httpx.Client | None = None) -> dict:
    """The road path through every point in order (lat, lng), for drawing a whole day's route on a map.
    Returns GeoJSON [lng, lat] pairs plus each leg's distance and time. No turn-by-turn steps."""
    if not osrm_url:
        raise DirectionsUnavailable("Road paths aren't set up (no OSRM_URL).")
    if len(points) < 2:
        raise DirectionsUnavailable("A path needs at least two points.")
    coords = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in points)
    http = client or _http()
    try:
        resp = http.get(f"{osrm_url}/route/v1/driving/{coords}", params={"overview": "full", "geometries": "geojson"})
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise DirectionsUnavailable("The road service didn't answer.") from exc
    if data.get("code") != "Ok" or not data.get("routes"):
        raise DirectionsUnavailable("No driving route was found.")
    route = data["routes"][0]
    return {"distance_m": round(route["distance"]), "duration_s": round(route["duration"]),
            "path": route["geometry"]["coordinates"],
            "legs": [{"distance_m": round(leg["distance"]), "duration_s": round(leg["duration"])} for leg in route["legs"]]}
