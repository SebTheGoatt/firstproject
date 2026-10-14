"""Driving distance/duration matrices.

Primary source: the OSRM `table` service (free, OpenStreetMap road network).
Fallback: great-circle (haversine) distance × a road-circuity factor, so the
nightly run still produces a sensible route if OSRM is unreachable.
"""

import logging
import math
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

LatLng = tuple[float, float]

ROAD_CIRCUITY = 1.3          # roads are ~30% longer than straight lines
FALLBACK_SPEED_MPS = 13.4    # ~30 mph suburban average
OSRM_MAX_POINTS = 100        # public demo server table limit


@dataclass
class TravelMatrix:
    distances_m: list[list[int]]
    durations_s: list[list[int]]
    source: str


def haversine_m(a: LatLng, b: LatLng) -> float:
    r = 6_371_000
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def haversine_matrix(points: list[LatLng]) -> TravelMatrix:
    dist = [[round(haversine_m(a, b) * ROAD_CIRCUITY) for b in points] for a in points]
    dur = [[round(d / FALLBACK_SPEED_MPS) for d in row] for row in dist]
    return TravelMatrix(dist, dur, "haversine")


def osrm_matrix(points: list[LatLng], base_url: str, client: httpx.Client | None = None) -> TravelMatrix:
    # OSRM wants lng,lat order.
    coords = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in points)
    url = f"{base_url}/table/v1/driving/{coords}"
    http = client or httpx.Client(timeout=20)
    resp = http.get(url, params={"annotations": "distance,duration"})
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM error: {data.get('code')} {data.get('message', '')}")

    def to_int(matrix: list[list[float | None]]) -> list[list[int]]:
        # OSRM returns null for unroutable pairs; make them prohibitively expensive.
        return [[round(v) if v is not None else 10**9 for v in row] for row in matrix]

    return TravelMatrix(to_int(data["distances"]), to_int(data["durations"]), "osrm")


def build_matrix(points: list[LatLng], osrm_url: str | None, client: httpx.Client | None = None) -> TravelMatrix:
    if osrm_url and len(points) <= OSRM_MAX_POINTS:
        try:
            return osrm_matrix(points, osrm_url, client)
        except (httpx.HTTPError, RuntimeError, KeyError, ValueError) as exc:
            log.warning("OSRM matrix failed (%s); falling back to haversine", exc)
    return haversine_matrix(points)
