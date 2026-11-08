"""Research for SEO and GEO content: the collector's manners and filters, and where the data shows up."""
import json
import pathlib
import sys

import pytest

from app import seo_research
from app.local_pages import AREAS, HOODS, AREA_BY_SLUG, area_faq

from .test_api_flow import CREW

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import seo_research as tool  # noqa: E402  (tools/seo_research.py)


# ---------- the committed data ----------
def test_the_data_covers_todays_areas_with_public_facts_only():
    d = json.loads(seo_research.DATA.read_text(encoding="utf-8"))
    assert d["fingerprint"] == seo_research.areas_fingerprint(), \
        "Areas changed: run python3 tools/seo_research.py (data/seo-research.json is stale)"
    assert set(d["season"]) == {a.slug for a in AREAS}
    for s in d["season"].values():
        assert len(s["months"]) == 12 and s["station_id"] in tool.STATIONS and 0 < s["miles"] < 30
    assert "NOAA" in d["sources"]["season"] and d["questions"] and d["howto"]
    for q in d["questions"]:                     # short public phrases and our labels; nothing about a person
        assert set(q) == {"q", "lang", "town", "intent", "service", "we_offer", "on_site"} and len(q["q"]) < 120


# ---------- manners: robots.txt and pacing ----------
DDG = "User-agent: *\nDisallow: /lite\nDisallow: /*?\nAllow: /?*\n\nUser-agent: ia_archiver\nDisallow: /\n"
NOAA = "User-agent: *\nDisallow: /data*\nDisallow: /access/crn/*?\nAllow: /data/oceans/coris/library*\n"


def test_robots_rules_follow_google_matching():
    rules = tool.robots_rules(DDG)
    assert not tool.robots_allows(rules, "/ac/?q=lawn")            # query strings off the root: not allowed
    assert tool.robots_allows(rules, "/?q=lawn") and tool.robots_allows(rules, "/about")
    noaa = tool.robots_rules(NOAA)
    assert not tool.robots_allows(noaa, "/data/normals-monthly/1991-2020/access/USW00012960.csv")
    assert tool.robots_allows(noaa, "/access/services/data/v1?dataset=normals-monthly-1991-2020")
    assert tool.robots_allows(noaa, "/data/oceans/coris/library/x")    # the longer Allow wins
    ours = tool.robots_rules("User-agent: postonelawnresearch\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    assert not tool.robots_allows(ours, "/anything")                  # a group naming us beats '*'
    assert tool.robots_allows(tool.robots_rules("User-agent: *\nDisallow:\n"), "/x")
    assert not tool.robots_allows(tool.robots_rules("User-agent: *\nDisallow: /*.json$\n"), "/a.json")


def test_blocked_urls_are_never_fetched_and_a_down_host_is_left_alone():
    calls = []

    def fetch(url):
        calls.append(url)
        if url == "https://example.org/robots.txt":
            return 200, "User-agent: *\nDisallow: /private\n"
        if url == "https://down.example/robots.txt":
            return 503, ""
        return 200, "ok"
    web = tool.Polite(fetch, delay=0)
    assert web.get("https://example.org/private/x") == (999, "") and web.get("https://example.org/public") == (200, "ok")
    assert web.get("https://down.example/page") == (999, "")
    assert calls == ["https://example.org/robots.txt", "https://example.org/public", "https://down.example/robots.txt"]
    assert web.blocked == ["https://example.org/private/x", "https://down.example/page"]


# ---------- what people search ----------
def test_only_relevant_local_searches_are_kept():
    keep = ["lawn service spring tx prices", "lawn mowing service new caney tx", "corte de cesped cerca de mi"]
    drop = ["lawn mower repair spring tx", "lawn care big spring tx", "lawn care china spring tx",
            "mowing grass in the rain meme", "cuanto cobran por cortar el pasto en mexico", "lawn mowing jobs klein tx",
            "spring branch lawn service"]
    assert all(tool.relevant(q, tool.town_of(q)) for q in keep)
    assert not any(tool.relevant(q, "spring" if "spring" in q else tool.town_of(q)) for q in drop)


def test_intent_and_services():
    assert tool.intent("lawn service spring tx prices") == "price"
    assert tool.intent("cada cuanto cortar el pasto") == "schedule"      # "how often", not a price
    assert tool.intent("how short to cut st augustine grass") == "howto"
    assert tool.service_match("lawn mowing and aeration klein") == ("aeration", False)
    assert tool.service_match("trash bin cleaning spring tx") == ("bin cleaning", True)
    assert tool.service_match("lawn care klein tx") == (None, True)


def test_questions_are_deduped_and_checked_against_our_site():
    canned = {"lawn mowing klein tx": ["lawn mowing klein tx", "lawn mowing klein tx prices", "Lawn Mowing Klein TX",
                                      "lawn aeration klein tx", "st augustine mowing height klein tx"]}

    def fetch(url):
        if url.endswith("/robots.txt"):
            return 404, ""
        from urllib.parse import parse_qs, urlsplit
        q = parse_qs(urlsplit(url).query)["q"][0]
        return 200, json.dumps([q, canned.get(q, [])])
    site = "lawn mowing in klein, tx. prices from $75 a visit."
    out = tool.questions(tool.Polite(fetch, delay=0), site)
    by = {q["q"]: q for q in out}
    assert list(by) == ["lawn mowing klein tx", "lawn mowing klein tx prices", "lawn aeration klein tx",
                        "st augustine mowing height klein tx"]
    assert by["lawn mowing klein tx prices"]["on_site"] and by["lawn mowing klein tx prices"]["intent"] == "price"
    assert not by["st augustine mowing height klein tx"]["on_site"]        # a gap worth writing about
    assert by["lawn aeration klein tx"]["we_offer"] is False and by["lawn aeration klein tx"]["on_site"] is False


# ---------- season facts ----------
def rows():
    highs = [63.8, 67.8, 74.0, 80.1, 86.9, 92.3, 94.5, 95.0, 90.3, 83.2, 72.9, 65.3]
    rain = [3.76, 2.97, 3.47, 3.95, 5.01, 6.0, 3.77, 4.36, 4.14, 4.98, 3.95, 3.66]
    monthly = [{"DATE": f"{m:02d}", "MLY-TMAX-NORMAL": f"  {h}", "MLY-TMIN-NORMAL": "50.0", "MLY-PRCP-NORMAL": f" {r}",
                "MLY-PRCP-AVGNDS-GE010HI": "  6.6" if m == 6 else "  5.0"} for m, h, r in zip(range(1, 13), highs, rain)]
    return monthly, [{"ANN-TMIN-PRBLST-T32FP50": "   02/13", "ANN-TMIN-PRBFST-T32FP50": "   12/09"}]


def test_nearest_station_and_season_summary(monkeypatch, tmp_path):
    from app.zones import zone_by_key
    klein = AREA_BY_SLUG["klein"]
    sid, miles = tool.nearest_station(*tool.area_center(zone_by_key(klein.zone_key)))
    assert sid == "USW00012960" and miles < 15                         # Houston Intercontinental serves Klein
    season = {"station_id": sid, "station": tool.STATIONS[sid][0], "miles": miles, **tool.season_from(*rows())}
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"season": {"klein": season}}))
    monkeypatch.setattr(seo_research, "DATA", path)
    f = seo_research.season_facts("klein")
    assert (f["warm_from"], f["warm_to"], f["wettest"], f["last_freeze"], f["first_freeze"]) == \
        ("April", "October", "June", "Feb 13", "Dec 9")
    q, a = seo_research.season_faq(klein)
    assert q == "When does grass grow fastest in Klein?"
    assert "NOAA weather station (Houston Intercontinental Airport, 1991–2020 normals)" in a
    assert "80°F or more from April through October" in a and "June is the rainiest month, about 6.0 inches over 7 days" in a


def test_no_research_file_means_no_extra_claims(monkeypatch, tmp_path, settings):
    monkeypatch.setattr(seo_research, "DATA", tmp_path / "missing.json")
    assert seo_research.research() == {} and seo_research.hub_research() is None
    assert len(area_faq(settings, AREA_BY_SLUG["klein"])) == 3 and seo_research.llms_climate(AREAS) == ""
    assert seo_research.prompt_facts() == [] and seo_research.top_questions() == []


# ---------- our own pages ----------
def test_page_audit_flags_what_search_engines_care_about():
    page = ('<html><head><title>' + "x" * 70 + '</title><script type="application/ld+json">{"@type": "FAQPage", '
            '"mainEntity": [{"@type": "Question"}, {"@type": "Question"}]}</script></head><body><h1>Hi</h1>'
            '<h1 id="filled-later"></h1><a href="/book">Book</a><script>var x = 1;</script></body></html>')
    a = tool.audit_page("/local/klein", page)
    assert a["h1"] == 1 and a["faq"] == 2 and "FAQPage" in a["schema"]       # an empty H1 isn't counted
    assert "no meta description" in a["issues"] and any("70 characters" in i for i in a["issues"])
    assert any(i.startswith("only ") for i in a["issues"]) and a["_links"] == ["/book"]
    assert "var x" not in a["_text"]


# ---------- where it shows up ----------
@pytest.mark.parametrize("path", ["/services", "/local", "/about", "/team", "/community"])
def test_listing_and_about_pages_describe_themselves(client, path):
    page = client.get(path).text
    assert page.count("application/ld+json") >= 1 and '"BreadcrumbList"' in page and "/#business" in page


def test_neighborhood_titles_fit_in_search_results(client):
    import re
    for h in HOODS:
        title = re.search(r"<title>(.*?)</title>", client.get(f"/local/{h.area}/{h.slug}").text).group(1)
        assert len(title.replace("&amp;", "&")) <= 60, title


def test_area_page_llms_txt_prompts_and_hub_use_the_research(client):
    klein = client.get("/local/klein").text
    assert "When does grass grow fastest in Klein?" in klein and klein.count("When does grass grow fastest in Klein?") >= 2
    llms = client.get("/llms.txt").text
    assert "## Local climate (NOAA U.S. Climate Normals 1991-2020)" in llms and "- Klein (Houston Intercontinental" in llms
    hub = client.get("/api/owner/marketing", headers=CREW).json()
    r = hub["research"]
    assert r["total"] > 0 and r["groups"] and len(r["season"]) == len(AREAS) and r["stale"] is False
    search = hub["prompts"][0]
    assert search["key"] == "search" and "[CHECK]" in search["prompt"] and "Season (" in search["prompt"]
    assert all(f"- {q}" in search["prompt"] for q in seo_research.top_questions(gaps_only=True))


def test_a_local_check_keeps_no_local_addresses():
    d = {"site_check": {"site": "http://127.0.0.1:8714", "pages": [{"path": "/", "canonical": "http://127.0.0.1:8714/"}]},
         "robots_blocked": ["http://127.0.0.1:8714/crew", "https://example.org/x"]}
    out = tool.tidy_local(d)
    assert out["site_check"]["site"] == "local copy of the current code" and "canonical" not in out["site_check"]["pages"][0]
    assert out["robots_blocked"] == ["/crew", "https://example.org/x"]
    assert "127.0.0.1" not in json.dumps(out)


def test_the_deploy_ships_the_research_file():
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY data ./data" in docker          # app/seo_research.py reads data/seo-research.json at run time
