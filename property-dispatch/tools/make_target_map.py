"""Where to knock first: every Census block group in our areas, ranked by how likely its homes are to pay for mowing.

    python3 tools/make_target_map.py        # writes static/data/targets-<fingerprint>.json

Open data only, no keys: American Community Survey 5-year estimates and 2023 TIGER block group shapes, both served
by Census Reporter (api.censusreporter.org; the Census Bureau's own API now needs a key). Only neighborhood totals are
used: no names, no addresses, nothing about a single home.

A block group is a few hundred to a few thousand homes. For each one inside our area boxes it keeps:
  homes          single-family detached homes lived in by their owners (owner households x single-family share)
  income         median household income
  owners_65      share of owner households headed by someone 65 or older (more likely to hire out the mowing)
  kids           share of households with children under 18 (busy parents)
  owner_share    share of households that own their home
and a priority score: homes x an income weight (median income / $100k, held between 0.4 and 1.5). Research on who
pays for lawn care points the same way: owners over renters, higher incomes, older owners and two-income families.
Counts are scaled by the share of the block group's land that falls inside our boxes.

The file name carries a fingerprint of the areas, boxes and days (app/marketing.py target_data_path()), so a schedule
change points the owner page at a file that doesn't exist yet and tests/test_target_map.py fails until this is re-run.
"""

import json
import pathlib
import subprocess
import sys
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.marketing import target_data_path  # noqa: E402
from app.zones import SERVICE_ZONES, WEEKDAY_NAMES, short_name  # noqa: E402

API = "https://api.censusreporter.org/1.0"
COUNTIES = {"48201": "Harris", "48339": "Montgomery", "48291": "Liberty"}   # every area box sits in these three
TABLES = "B25003,B25024,B19013,B25007,B11005"
TIGER = "tiger2023"


def get(path: str, **params) -> dict:
    url = f"{API}/{path}?{urllib.parse.urlencode(params, safe='|,')}"
    out = subprocess.run(["curl", "-sfL", "--retry", "4", "--retry-all-errors", "--max-time", "180", url],
                         capture_output=True, check=True).stdout
    return json.loads(out)


# ---------- geometry: plain Python, no GIS libraries ----------
def ring_area(ring) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]))) / 2


def clip(ring, box):
    """Sutherland-Hodgman: the part of a ring inside an axis-aligned box (w, s, e, n)."""
    w, s, e, n = box
    edges = ((lambda p: p[0] >= w, lambda a, b: (w, a[1] + (b[1] - a[1]) * (w - a[0]) / (b[0] - a[0]))),
             (lambda p: p[0] <= e, lambda a, b: (e, a[1] + (b[1] - a[1]) * (e - a[0]) / (b[0] - a[0]))),
             (lambda p: p[1] >= s, lambda a, b: (a[0] + (b[0] - a[0]) * (s - a[1]) / (b[1] - a[1]), s)),
             (lambda p: p[1] <= n, lambda a, b: (a[0] + (b[0] - a[0]) * (n - a[1]) / (b[1] - a[1]), n)))
    pts = list(ring)
    for inside, cross in edges:
        if not pts:
            break
        src, pts = pts, []
        for i, cur in enumerate(src):
            prev = src[i - 1]
            if inside(cur):
                if not inside(prev):
                    pts.append(cross(prev, cur))
                pts.append(cur)
            elif inside(prev):
                pts.append(cross(prev, cur))
    return pts


def polygons(geom) -> list:
    return [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]


def land_area(geom) -> float:
    return sum(ring_area([tuple(p) for p in poly[0]]) - sum(ring_area([tuple(p) for p in h]) for h in poly[1:])
               for poly in polygons(geom))


def area_in(geom, boxes) -> float:
    return sum(ring_area(clip([tuple(p) for p in poly[0]], b)) for poly in polygons(geom) for b in boxes)


def simplify(ring, tol=0.00025):
    """Ramer-Douglas-Peucker, then 5 decimals (about a metre): small enough to ship, close enough to read."""
    if len(ring) < 4:
        return ring
    (x1, y1), (x2, y2) = ring[0], ring[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = (dx * dx + dy * dy) ** 0.5 or 1e-12
    far, idx = 0.0, 0
    for i, (x, y) in enumerate(ring[1:-1], 1):
        d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / norm
        if d > far:
            far, idx = d, i
    if far <= tol:
        return [ring[0], ring[-1]]
    return simplify(ring[: idx + 1], tol)[:-1] + simplify(ring[idx:], tol)


def simplify_ring(ring):
    """A closed ring starts and ends on the same point, so split it at the point farthest from the start first."""
    far = max(range(len(ring)), key=lambda i: (ring[i][0] - ring[0][0]) ** 2 + (ring[i][1] - ring[0][1]) ** 2)
    return simplify(ring[: far + 1])[:-1] + simplify(ring[far:])


def small(geom) -> dict:
    out = []
    for poly in polygons(geom):
        ring = [[round(x, 5), round(y, 5)] for x, y in simplify_ring([tuple(p) for p in poly[0]])]
        if len(ring) >= 4:
            out.append([ring])
    return {"type": "MultiPolygon", "coordinates": out}


# ---------- numbers ----------
def est(row: dict, table: str, col: str) -> float:
    v = (row.get(table) or {}).get("estimate", {}).get(f"{table}{col}")
    return float(v) if v is not None else 0.0


def main() -> None:
    zone_boxes = {z.key: z.boxes for z in SERVICE_ZONES}
    features, release = [], None
    for fips, county in COUNTIES.items():
        geo = get(f"geo/show/{TIGER}", geo_ids=f"150|05000US{fips}")
        data = get("data/show/latest", table_ids=TABLES, geo_ids=f"150|05000US{fips}")
        release = data["release"]
        for f in geo["features"]:
            gid = f["properties"]["geoid"]
            total = land_area(f["geometry"])
            share = {k: area_in(f["geometry"], boxes) / total for k, boxes in zone_boxes.items()} if total else {}
            key, part = max(share.items(), key=lambda kv: kv[1]) if share else (None, 0)
            if part < 0.15:                    # mostly outside our areas
                continue
            row = data["data"].get(gid, {})
            households, owners = est(row, "B25003", "001"), est(row, "B25003", "002")
            units, detached = est(row, "B25024", "001"), est(row, "B25024", "002")
            if households < 20 or not units:
                continue
            income = est(row, "B19013", "001") or None
            older = sum(est(row, "B25007", c) for c in ("009", "010", "011"))
            kids = est(row, "B11005", "002")
            homes = owners * min(1.0, detached / units) * part
            weight = min(1.5, max(0.4, (income or 40000) / 100000))
            features.append({"type": "Feature", "geometry": small(f["geometry"]), "properties": {
                "id": gid, "county": county, "zone": key, "inside": round(part, 2),
                "homes": round(homes), "households": round(households * part),
                "owner_share": round(owners / households, 2), "income": round(income) if income else None,
                "owners_65": round(older / owners, 2) if owners else 0, "kids": round(kids / households, 2),
                "score": round(homes * weight)}})
        print(f"{county}: {sum(1 for x in features if x['properties']['county'] == county)} block groups in our areas")
    features.sort(key=lambda f: -f["properties"]["score"])
    areas = [{"key": z.key, "name": short_name(z), "day": WEEKDAY_NAMES[z.service_weekday], "boxes": z.boxes}
             for z in sorted(SERVICE_ZONES, key=lambda z: z.service_weekday)]
    out = ROOT / target_data_path().lstrip("/")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"release": release["name"], "years": release["years"], "tiger": TIGER,
                               "source": "U.S. Census Bureau ACS 5-year estimates, via Census Reporter",
                               "areas": areas, "type": "FeatureCollection", "features": features},
                              separators=(",", ":")), encoding="utf-8")
    print(f"{len(features)} block groups, {out.stat().st_size // 1024} KB -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
