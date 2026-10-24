"""Each area has its street-map cards (tools/make_area_cards.py), and its pages share the wide one."""

import pathlib

from app.local_pages import AREAS, HOODS, area_card_path
from app.marketing import poster_path

from .test_api_flow import CREW

STATIC = pathlib.Path(__file__).resolve().parents[1] / "static"


def test_every_area_has_both_cards_for_its_current_day():
    for area in AREAS:
        for square in (False, True):
            path = STATIC / area_card_path(area, square=square).removeprefix("/static/")
            assert path.is_file(), f"{path.name} is missing: run python3 tools/make_area_cards.py"
            assert path.read_bytes()[:3] == b"\xff\xd8\xff"


def test_area_and_neighborhood_pages_share_their_area_card(client):
    for area in AREAS:
        assert f'property="og:image" content="http://testserver{area_card_path(area)}"' in client.get(f"/local/{area.slug}").text
    hood = HOODS[0]
    area = next(a for a in AREAS if a.slug == hood.area)
    assert area_card_path(area) in client.get(f"/local/{hood.area}/{hood.slug}").text


def test_marketing_hub_offers_the_cards(client):
    r = client.get("/api/owner/marketing", headers=CREW)
    cards = r.json()["map_cards"]
    assert [c["square"] for c in cards] == [area_card_path(a, square=True) for a in AREAS]


def test_the_poster_matches_the_current_areas_and_days():
    jpg, pdf = (STATIC / poster_path(ext).removeprefix("/static/") for ext in ("jpg", "pdf"))
    assert jpg.is_file() and pdf.is_file(), "the service map poster is out of date: run python3 tools/make_area_poster.py"
    assert jpg.read_bytes()[:3] == b"\xff\xd8\xff" and pdf.read_bytes()[:5] == b"%PDF-"


def test_marketing_hub_offers_the_poster(client):
    assert client.get("/api/owner/marketing", headers=CREW).json()["poster"] == {"jpg": poster_path("jpg"), "pdf": poster_path("pdf")}
