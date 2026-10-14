"""Native-navigation deep links for Google Maps and Apple Maps.

Google Maps (universal URL, opens the app on iOS/Android):
    https://www.google.com/maps/dir/?api=1&origin=..&destination=..&waypoints=a|b
    The Google Maps app accepts up to 9 waypoints (mobile *browsers* only 3),
    so a full-day route is split into chained legs of at most 9 waypoints.

Apple Maps:
    https://maps.apple.com/?saddr=..&daddr=..&dirflg=d
    The URL scheme officially supports a single destination, so Apple Maps
    gets per-stop navigation links.
"""

from urllib.parse import urlencode

LatLng = tuple[float, float]

GOOGLE_MAX_WAYPOINTS = 9


def _fmt(p: LatLng) -> str:
    return f"{p[0]:.6f},{p[1]:.6f}"


def google_directions(destination: LatLng, origin: LatLng | None = None, waypoints: list[LatLng] | None = None) -> str:
    params = {"api": "1", "destination": _fmt(destination), "travelmode": "driving"}
    if origin:
        params["origin"] = _fmt(origin)  # omitted → device's current location
    if waypoints:
        params["waypoints"] = "|".join(_fmt(w) for w in waypoints)
    return "https://www.google.com/maps/dir/?" + urlencode(params, safe=",|")


def apple_directions(destination: LatLng, origin: LatLng | None = None) -> str:
    params = {"daddr": _fmt(destination), "dirflg": "d"}
    if origin:
        params["saddr"] = _fmt(origin)
    return "https://maps.apple.com/?" + urlencode(params, safe=",")


def google_full_route(origin: LatLng | None, stops: list[LatLng], end: LatLng) -> list[str]:
    """Split the day into Google Maps links of ≤9 waypoints each.

    `origin=None` starts the first segment from the device's live location.
    Each segment ends where the next begins, so the crew taps them in order.
    """
    path = [*stops, end]
    urls: list[str] = []
    seg_origin, i = origin, 0
    while i < len(path):
        j = min(i + GOOGLE_MAX_WAYPOINTS, len(path) - 1)   # index of this segment's destination
        urls.append(google_directions(path[j], origin=seg_origin, waypoints=path[i:j]))
        seg_origin, i = path[j], j + 1
    return urls
