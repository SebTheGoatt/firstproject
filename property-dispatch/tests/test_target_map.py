"""Where to knock first: the ranked neighborhood data (tools/make_target_map.py) and the owner page that shows it."""

import json
import pathlib
import sys

from app.marketing import target_data_path
from app.zones import SERVICE_ZONES

from .test_api_flow import CREW

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIELDS = {"id", "county", "zone", "inside", "homes", "households", "owner_share", "income", "owners_65", "kids", "score"}


def data() -> dict:
    path = ROOT / target_data_path().lstrip("/")
    assert path.exists(), f"Run tools/make_target_map.py: {path.name} is missing for the current areas and days"
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_data_matches_todays_areas_and_holds_only_neighborhood_totals():
    d = data()
    zones = {z.key for z in SERVICE_ZONES}
    assert {a["key"] for a in d["areas"]} == zones and d["features"]
    for f in d["features"]:
        p = f["properties"]
        assert set(p) == FIELDS                       # totals and shares only: nothing about a single home
        assert p["zone"] in zones and p["id"].startswith("15000US")
        assert f["geometry"]["coordinates"] and all(len(poly[0]) >= 4 for poly in f["geometry"]["coordinates"])
        assert 0 <= p["owner_share"] <= 1 and 0 <= p["owners_65"] <= 1 and 0 <= p["kids"] <= 1 and p["homes"] >= 0
    scores = [f["properties"]["score"] for f in d["features"]]
    assert scores == sorted(scores, reverse=True)     # ranked best first
    assert "Census" in d["source"] and d["release"].startswith("ACS")


def test_clipping_math():
    sys.path.insert(0, str(ROOT / "tools"))
    from make_target_map import area_in, clip, ring_area
    square = [(0, 0), (2, 0), (2, 2), (0, 2)]
    assert ring_area(square) == 4
    assert ring_area(clip(square, (1, 1, 3, 3))) == 1                    # a quarter inside the box
    assert ring_area(clip(square, (5, 5, 6, 6))) == 0                    # none inside
    geom = {"type": "Polygon", "coordinates": [[list(p) for p in square]]}
    assert area_in(geom, [(0, 0, 1, 2)]) == 2


def test_owner_page_and_data_link(client):
    assert client.get("/api/owner/targets").status_code in (401, 403)
    url = client.get("/api/owner/targets", headers=CREW).json()["data_url"]
    assert url == target_data_path() and client.get(url).status_code == 200
    page = client.get("/owner/targets")
    assert page.status_code == 200 and "noindex" in page.headers.get("x-robots-tag", "")
    assert 'href="/owner/targets"' in client.get("/owner/marketing").text
