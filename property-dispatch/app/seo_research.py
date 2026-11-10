"""Research for search and AI-answer content (tools/seo_research.py writes data/seo-research.json; this reads it).

    season_facts(area_slug)   NOAA climate normals for the area: warm months, rainiest month, freeze dates
    season_faq(area)          one more FAQ answer for the area page, from those normals
    llms_climate(areas)       the "Local climate" lines in /llms.txt
    prompt_facts()            what the AI prompt pack may say about the season and what people search
    hub_research()            the marketing hub's "What people search" panel
    competitors()             how competing sites present themselves next to ours (tools/competitor_scan.py), totals only

Everything here degrades to nothing when the file is missing or stale: pages never break over research data.
Numbers are quoted as NOAA states them (1991-2020 normals, nearest station named), never rounded into claims.
"""

import hashlib
import json
import pathlib
from collections import Counter
from functools import lru_cache

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "seo-research.json"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
WARM_F = 80          # "average daily high of 80°F or more": a plain, checkable line for the warm stretch
INTENT_LABELS = {"price": "Price", "schedule": "When and how often", "howto": "How-to", "near_me": "Near me",
                 "local": "Local searches"}


def areas_fingerprint() -> str:
    """Changes when an area is added, renamed or moved, so the research is re-run for it."""
    from .local_pages import AREAS
    from .zones import zone_by_key
    plan = repr(sorted((a.slug, a.zone_key, zone_by_key(a.zone_key).boxes) for a in AREAS)).encode()
    return hashlib.sha256(plan).hexdigest()[:8]


@lru_cache(maxsize=1)
def _load(path: str, mtime: float) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


SKIP_IN_POSITIONING = {"quote_first"}          # their friction, not a feature to match


def competitors() -> dict | None:
    """Where we lead and where we trail, from totals. `lead`: we do it and at most a third of them say so.
    `gap`: at least a third of them do it and our page doesn't. None until the scan has been run."""
    path = DATA.with_name("competitor-scan.json")     # beside the search research, looked up at call time
    try:
        d = _load(str(path), path.stat().st_mtime)
    except (OSError, ValueError):
        return None
    n = d.get("checked") or 0
    if not n:
        return None
    rows = [f for f in d["features"] if f["key"] not in SKIP_IN_POSITIONING]
    quote = next((f for f in d["features"] if f["key"] == "quote_first"), None)
    return {"collected": d.get("collected"), "checked": n, "companies": d.get("companies"),
            "marketplaces": d.get("marketplaces"), "method": d.get("method"), "features": rows,
            "lead": [f for f in rows if f["we"] and f["others"] * 3 <= n],
            "gap": [f for f in rows if not f["we"] and f["others"] * 3 >= n],
            "quote_first": quote["others"] if quote else None}


def research(path: pathlib.Path | None = None) -> dict:
    path = path or DATA          # looked up at call time, so tests (and a re-run) can point it elsewhere
    try:
        return _load(str(path), path.stat().st_mtime)
    except (OSError, ValueError):
        return {}


def _date(md: str | None) -> str | None:
    """'02/13' -> 'Feb 13'."""
    try:
        m, d = (int(x) for x in (md or "").split("/"))
        return f"{MONTHS[m - 1][:3]} {d}"
    except (ValueError, IndexError):
        return None


def season_facts(area_slug: str) -> dict | None:
    s = (research().get("season") or {}).get(area_slug)
    if not s or len(s.get("months") or []) != 12:
        return None
    months = s["months"]
    warm = [m["m"] for m in months if (m.get("high_f") or 0) >= WARM_F]
    wet = max(months, key=lambda m: m.get("rain_in") or 0)
    return {
        "station": s["station"], "miles": s["miles"],
        "warm_from": MONTHS[warm[0] - 1] if warm else None, "warm_to": MONTHS[warm[-1] - 1] if warm else None,
        "hottest_high": max(m.get("high_f") or 0 for m in months),
        "wettest": MONTHS[wet["m"] - 1], "wettest_in": wet.get("rain_in"), "wettest_days": wet.get("rain_days"),
        "year_rain": round(sum(m.get("rain_in") or 0 for m in months), 1),
        "last_freeze": _date(s.get("last_freeze")), "first_freeze": _date(s.get("first_freeze")),
    }


def _sentence(f: dict) -> str:
    parts = []
    if f["warm_from"]:
        parts.append(f"average daily highs are {WARM_F}°F or more from {f['warm_from']} through {f['warm_to']}")
    if f["last_freeze"] and f["first_freeze"]:
        parts.append(f"the median last freeze is around {f['last_freeze']} and the first around {f['first_freeze']}")
    if f["wettest_in"]:
        rain = f"{f['wettest']} is the rainiest month, about {f['wettest_in']:.1f} inches"
        if f["wettest_days"]:
            rain += f" over {f['wettest_days']:.0f} days"
        parts.append(rain)
    return "; ".join(parts)


def season_faq(area) -> tuple[str, str] | None:
    f = season_facts(area.slug)
    if not f or not f["warm_from"]:
        return None
    return (f"When does grass grow fastest in {area.city}?",
            f"In the warm months. At the nearest NOAA weather station ({f['station']}, 1991–2020 normals), "
            f"{_sentence(f)}. Heat plus rain is when lawns need mowing most often; we mow through light rain and move "
            f"storm days to the make-up day.")


def llms_climate(areas) -> str:
    lines = []
    for a in areas:
        f = season_facts(a.slug)
        if f:
            lines.append(f"- {a.city} ({f['station']}, {f['miles']:.0f} mi): {_sentence(f)}; about {f['year_rain']} inches "
                         f"of rain a year.")
    if not lines:
        return ""
    return "## Local climate (NOAA U.S. Climate Normals 1991-2020)\n" + "\n".join(lines) + "\n"


def prompt_facts() -> list[str]:
    """Extra lines for the AI prompt pack: real local season facts and the questions people really search."""
    from .local_pages import AREAS
    out = []
    by_station = {}
    for a in AREAS:
        f = season_facts(a.slug)
        if f:
            by_station.setdefault(f["station"], (f, []))[1].append(a.city)
    for station, (f, cities) in by_station.items():
        out.append(f"- Season ({', '.join(cities)}; NOAA 1991-2020 normals, {station}): {_sentence(f)}.")
    c = competitors()
    if c and c["lead"]:
        lead = "; ".join(f"{f['label'].lower()} ({f['others']} of {c['checked']} competing sites do)" for f in c["lead"])
        out.append(f"- What sets us apart online (our check of {c['checked']} competing sites, {c['collected']}): {lead}. "
                   "Lead with these. Never name, criticize or compare against a specific competitor.")
    return out


def top_questions(limit: int = 12, gaps_only: bool = False) -> list[str]:
    qs = [q for q in research().get("questions") or [] if q.get("we_offer")]
    if gaps_only:
        qs = [q for q in qs if not q.get("on_site")]
    return [q["q"] for q in qs[:limit]]


def hub_research() -> dict | None:
    """The marketing hub panel. None when the research hasn't been run yet."""
    r = research()
    if not r:
        return None
    from .local_pages import AREAS
    qs = r.get("questions") or []
    ours = [q for q in qs if q.get("we_offer")]
    groups = {}
    for q in ours:
        groups.setdefault(q.get("intent") or "local", []).append({"q": q["q"], "lang": q.get("lang", "en"),
                                                                  "on_site": bool(q.get("on_site"))})
    not_offered = Counter(q["service"] for q in qs if not q.get("we_offer") and q.get("service"))
    site = r.get("site_check") or {}
    issues = [{"path": p["path"], "issues": p["issues"]} for p in site.get("pages", []) if p.get("issues")]
    return {
        "collected": r.get("collected"), "stale": r.get("fingerprint") != areas_fingerprint(),
        "groups": [{"key": k, "label": INTENT_LABELS.get(k, k), "questions": v[:10]}
                   for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))],
        "gaps": sum(1 for q in ours if not q.get("on_site")), "total": len(ours),
        "not_offered": [{"service": s, "count": n} for s, n in not_offered.most_common(8)],
        "howto": (r.get("howto") or [])[:8],
        "season": [{"area": a.city, **f} for a in AREAS if (f := season_facts(a.slug))],
        "site": {"checked": site.get("site"), "pages": len(site.get("pages") or []), "issues": issues[:15],
                 "broken_links": site.get("broken_links") or [], "llms_txt": site.get("llms_txt")} if site else None,
        "sources": r.get("sources") or {},
        "competitors": competitors(),
    }
