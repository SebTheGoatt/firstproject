"""Data for search (SEO) and AI-answer (GEO) content: what people search, local season facts, and a check of our pages.

    python3 tools/seo_research.py                                  # everything; checks the live site
    python3 tools/seo_research.py --site http://127.0.0.1:8711     # check a local copy of the site instead
    python3 tools/seo_research.py --skip-site                      # questions and season facts only

Writes data/seo-research.json, which the app reads for the marketing hub ("What people search"), the AI prompt pack,
each area page's FAQ and /llms.txt. Re-run it once a month, and after an area's boxes or day change
(tests/test_seo_research.py fails until you do).

Sources: all public, no keys, no personal data.
  questions  Google's search-box suggestions (suggestqueries.google.com) for lawn-care phrases x our towns, English
             and Spanish. Short public phrases only; this never loads Google's results pages.
  how-to     Stack Exchange's official API (gardening.stackexchange.com): the top-voted lawn questions. Titles and
             links only; the answers are their authors' work and stay on their site.
  season     NOAA NCEI 1991-2020 climate normals through NOAA's Access Data Service, for the station nearest each
             area: average high, rain and rainy days by month, median last and first freeze. US government data,
             public domain.
  site       our own sitemap: titles, descriptions, H1s, structured data, FAQ count, words, broken internal links.

Manners: every host's robots.txt is read first and obeyed (wildcards included); the User-Agent says who we are; one
request a second per host; nothing is retried in a loop. No competitor sites, no search results pages.
"""

import argparse
import hashlib
import html
import json
import math
import pathlib
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import date
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "seo-research.json"
UA = "PostOneLawnResearch/1.0 (+https://property-dispatch.onrender.com/llms.txt)"
LIVE_SITE = "https://property-dispatch.onrender.com"

# NOAA stations with full 1991-2020 normals around our areas (checked Nov 2026). The nearest one serves each area.
STATIONS = {
    "USW00012960": ("Houston Intercontinental Airport", 29.9800, -95.3600),
    "USW00053902": ("Conroe-North Houston Regional Airport", 30.3567, -95.4139),
    "USC00411810": ("Cleveland, TX", 30.3636, -95.0839),
}
MONTHLY = ("MLY-TMAX-NORMAL", "MLY-TMIN-NORMAL", "MLY-PRCP-NORMAL", "MLY-PRCP-AVGNDS-GE010HI")
FREEZE = ("ANN-TMIN-PRBLST-T32FP50", "ANN-TMIN-PRBFST-T32FP50")

# What people type. {town} is each town we mow; generic seeds run once.
SEEDS_EN = ("lawn mowing {town} tx", "lawn care {town} tx", "lawn service {town} tx", "grass cutting {town} tx",
            "yard work {town} tx")
SEEDS_ES = ("corte de cesped {town}", "cortar pasto {town}", "jardinero {town} tx")
GENERIC_EN = ("how much does lawn mowing cost in houston", "how often should i mow my lawn in texas",
              "when to start mowing st augustine grass", "how short to cut st augustine grass",
              "lawn mowing near me", "lawn service prices houston", "bermuda grass mowing height",
              "when to stop mowing lawn texas", "lawn mowing in the rain", "do i need to be home for lawn service")
GENERIC_ES = ("cuanto cobran por cortar el pasto", "cada cuanto cortar el pasto", "servicio de jardineria cerca de mi",
              "corte de cesped cerca de mi")
TOWNS = ("spring", "klein", "new caney", "splendora", "colony ridge", "cleveland", "plum grove")
OTHER_PLACES = re.compile(r"\b(big|sulphur|palm|colorado|cold|dripping|hot|silver|china) springs?\b|\bsprings\b|"
                          r"spring (branch|valley|hill|creek|lake|cypress)|cleveland (oh|ohio|tn|ms|ga)|"
                          r"\b(florida|georgia|carolina|north texas|dallas|austin|san antonio|argentina|m[eé]xico|chile|"
                          r"espa[nñ]a|colombia|per[uú]|uruguay|australia|uk|beach)\b")
JUNK = re.compile(r"\b(gif|meme|reddit|youtube|video|song|lyrics|quotes?|tiktok|wallpaper|clipart|png)\b")
LAWN_WORDS = re.compile(r"lawn|grass|mow|yard|turf|c[eé]sped|pasto|zacate|jard[ií]n|jardiner")
OFF_TOPIC = re.compile(r"\b(repair|for sale|sale|parts|rental|rent|job|jobs|hiring|empleo|trabajo|salary|"
                       r"walmart|home depot|lowes|craigslist|used|battery|blade|blades|equipment|license)\b|mowers?\b")
INTENTS = (
    ("price", r"price|prices|cost|how much|cheap|affordable|rates?|precio|cu[aá]nto|cobran|barato"),
    ("schedule", r"how often|when|weekly|biweekly|every|schedule|season|month|winter|rain|cada cu[aá]nto|cu[aá]ndo"),
    ("howto", r"how (short|high|to)|height|best|tips|should|need to be home"),
    ("near_me", r"near me|cerca"),
)
# Services people ask about: (pattern, name, we offer it). Mowing visits and their add-ons are ours.
SERVICES = (
    (r"aerat", "aeration", False), (r"fertili", "fertilizing", False), (r"weed", "weed control", False),
    (r"landscap|paisaj", "landscaping", False), (r"\btrees?\b|[aá]rbol", "tree work", False),
    (r"hedge|bush|shrub", "hedges and shrubs", False), (r"\bsod\b", "sod", False), (r"pest|mosquito", "pest control", False),
    (r"\bleaf|leaves|hojas", "leaf removal", False), (r"sprinkler|irrigation|riego", "sprinklers", False),
    (r"pressure wash", "pressure washing", False),
    (r"\bbins?\b|trash can|garbage can", "bin cleaning", True), (r"gutter", "gutter cleaning", True),
    (r"christmas|holiday light", "holiday lighting", True), (r"mow|cutting|corte|cortar", "mowing", True),
)
STOP = set("a an and the of in on for to my me i is it do does how what when should much near tx texas lawn lawns mowing "
           "mow mower care service services grass cutting yard work de el la en por para mi cerca que cuanto cuánto "
           "corte cortar cesped césped pasto jardinero jardineria jardinería servicio cada houston".split())


# ---------- polite fetching ----------
def curl(url: str, timeout: int = 40) -> tuple[int, str]:
    out = subprocess.run(["curl", "-sL", "--compressed", "--max-time", str(timeout), "-A", UA, "-w", "\n%{http_code}", url],
                         capture_output=True, text=True)
    body, _, code = out.stdout.rpartition("\n")
    return (int(code) if code.isdigit() else 0), body


def robots_rules(text: str, agent: str = "postonelawnresearch") -> list[tuple[bool, str]]:
    """(allow, pattern) rules for our agent: the group naming us, else the '*' group."""
    groups, current, saw_rule = {}, [], False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (x.strip() for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if saw_rule:
                current, saw_rule = [], False
            current.append(value.lower())
            for a in current:
                groups.setdefault(a, [])
        elif key in ("allow", "disallow") and current:
            saw_rule = True
            for a in current:
                if value or key == "allow":
                    groups[a].append((key == "allow", value))
    for a, rules in groups.items():
        if a != "*" and a in agent:
            return rules
    return groups.get("*", [])


def robots_allows(rules: list[tuple[bool, str]], path: str) -> bool:
    """Longest matching rule wins; Allow wins a tie. Supports * and $ (as Google and Bing do)."""
    best = (-1, True)
    for allow, pattern in rules:
        rx = "^" + re.escape(pattern).replace(r"\*", ".*")
        rx = rx[:-2] + "$" if rx.endswith(r"\$") else rx
        if re.match(rx, path) and (len(pattern), allow) > best:
            best = (len(pattern), allow)
    return best[1]


class Polite:
    """robots.txt first, then one request a second per host. `fetch` is swappable for tests."""

    def __init__(self, fetch=curl, delay: float = 1.0):
        self.fetch, self.delay, self.rules, self.last = fetch, delay, {}, {}
        self.blocked: list[str] = []

    def get(self, url: str) -> tuple[int, str]:
        u = urllib.parse.urlsplit(url)
        host = f"{u.scheme}://{u.netloc}"
        if host not in self.rules:
            code, text = self._timed(host, host + "/robots.txt")
            # 4xx = no rules (allowed); 5xx or no answer = treat the whole host as off limits for this run.
            self.rules[host] = robots_rules(text) if code == 200 else ([] if 400 <= code < 500 else [(False, "/")])
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        if not robots_allows(self.rules[host], path):
            self.blocked.append(url)
            return 999, ""
        return self._timed(host, url)

    def _timed(self, host: str, url: str) -> tuple[int, str]:
        wait = self.delay - (time.monotonic() - self.last.get(host, -1e9))
        if wait > 0:
            time.sleep(wait)
        self.last[host] = time.monotonic()
        return self.fetch(url)


# ---------- what people search ----------
def suggestions(web: Polite, phrase: str, lang: str) -> list[str]:
    q = urllib.parse.urlencode({"client": "firefox", "hl": lang, "gl": "us", "q": phrase})
    code, body = web.get(f"https://suggestqueries.google.com/complete/search?{q}")
    if code != 200:
        return []
    try:
        return [s for s in json.loads(body)[1] if isinstance(s, str)]
    except (ValueError, IndexError):
        return []


def town_of(text: str) -> str | None:
    return next((t for t in TOWNS if re.search(rf"\b{t}\b", text)), None)


def relevant(text: str, town: str | None) -> bool:
    t = text.lower()
    if not LAWN_WORDS.search(t) or OFF_TOPIC.search(t) or OTHER_PLACES.search(t) or JUNK.search(t):
        return False
    return town is None or re.search(rf"\b{town}\b", t) is not None


def intent(text: str) -> str:
    if re.search(r"cada cu[aá]nto|cu[aá]ndo", text):          # "how often" / "when" in Spanish, not a price
        return "schedule"
    return next((name for name, rx in INTENTS if re.search(rx, text)), "local")


def service_match(text: str) -> tuple[str | None, bool]:
    """('aeration', False) when someone asks about a service we don't offer; those are checked first, so
    "mowing and aeration" counts as a request we can't fully meet."""
    for rx, name, ours in SERVICES:
        if re.search(rx, text):
            return name, ours
    return None, True


def key_terms(text: str) -> list[str]:
    words = re.findall(r"[a-záéíóúñ]+", text.lower())
    towns = " ".join(TOWNS).split()
    return [w.rstrip("s") if len(w) > 3 else w for w in words if w not in STOP and w not in towns and len(w) > 2]


def answered(text: str, site_text: str) -> bool:
    """Does our site already say something about this? Every distinctive word must appear somewhere on it."""
    terms = key_terms(text)
    return all(t in site_text for t in terms)


def questions(web: Polite, site_text: str) -> list[dict]:
    seen, out = set(), []
    jobs = [(s.format(town=town), "en", town) for town in TOWNS for s in SEEDS_EN]
    jobs += [(s.format(town=town), "es", town) for town in TOWNS for s in SEEDS_ES]
    jobs += [(s, "en", None) for s in GENERIC_EN] + [(s, "es", None) for s in GENERIC_ES]
    for seed, lang, town in jobs:
        for s in suggestions(web, seed, lang):
            s = " ".join(s.lower().split())
            if s in seen or not relevant(s, town):
                continue
            seen.add(s)
            service, ours = service_match(s)
            out.append({"q": s, "lang": lang, "town": town_of(s), "intent": intent(s),
                        "service": service, "we_offer": ours, "on_site": ours and answered(s, site_text)})
    return out


def howto(web: Polite) -> list[dict]:
    out, seen = [], set()
    for tag in ("lawn", "mowing", "st-augustine-grass", "bermuda-grass"):
        q = urllib.parse.urlencode({"order": "desc", "sort": "votes", "tagged": tag, "site": "gardening", "pagesize": 15})
        code, body = web.get(f"https://api.stackexchange.com/2.3/questions?{q}")
        if code != 200:
            continue
        for item in json.loads(body).get("items", []):
            title = html.unescape(item.get("title", ""))
            if item.get("question_id") in seen or not title:
                continue
            seen.add(item["question_id"])
            out.append({"q": title, "votes": item.get("score", 0), "link": item.get("link", ""), "tag": tag})
    return sorted(out, key=lambda x: -x["votes"])[:25]


# ---------- season facts (NOAA normals) ----------
def miles(lat1, lng1, lat2, lng2) -> float:
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lng2 - lng1) * p / 2) ** 2)
    return 7917.5 * math.asin(math.sqrt(a))


def area_center(zone) -> tuple[float, float]:
    boxes = zone.boxes
    return (sum((s + n) / 2 for w, s, e, n in boxes) / len(boxes), sum((w + e) / 2 for w, s, e, n in boxes) / len(boxes))


def nearest_station(lat: float, lng: float) -> tuple[str, float]:
    sid = min(STATIONS, key=lambda k: miles(lat, lng, *STATIONS[k][1:]))
    return sid, round(miles(lat, lng, *STATIONS[sid][1:]), 1)


def noaa(web: Polite, dataset: str, station: str, types: tuple[str, ...]) -> list[dict]:
    q = urllib.parse.urlencode({"dataset": dataset, "stations": station, "format": "json", "dataTypes": ",".join(types)})
    code, body = web.get(f"https://www.ncei.noaa.gov/access/services/data/v1?{q}")
    if code != 200:
        raise RuntimeError(f"NOAA answered {code} for {station}")
    return json.loads(body)


def num(row: dict, key: str) -> float | None:
    try:
        return float(str(row.get(key, "")).strip())
    except ValueError:
        return None


def season_from(monthly: list[dict], annual: list[dict]) -> dict:
    months = []
    for row in sorted(monthly, key=lambda r: int(r["DATE"])):
        months.append({"m": int(row["DATE"]), "high_f": num(row, "MLY-TMAX-NORMAL"), "low_f": num(row, "MLY-TMIN-NORMAL"),
                       "rain_in": num(row, "MLY-PRCP-NORMAL"), "rain_days": num(row, "MLY-PRCP-AVGNDS-GE010HI")})
    a = annual[0] if annual else {}
    freeze = lambda k: (str(a.get(k, "")).strip() or None)  # noqa: E731  "02/13" (month/day, 50% odds)
    return {"months": months, "last_freeze": freeze(FREEZE[0]), "first_freeze": freeze(FREEZE[1])}


def season(web: Polite) -> dict:
    from app.local_pages import AREAS
    from app.zones import zone_by_key
    cache, out = {}, {}
    for area in AREAS:
        lat, lng = area_center(zone_by_key(area.zone_key))
        sid, dist = nearest_station(lat, lng)
        if sid not in cache:
            cache[sid] = season_from(noaa(web, "normals-monthly-1991-2020", sid, MONTHLY),
                                     noaa(web, "normals-annualseasonal-1991-2020", sid, FREEZE))
        out[area.slug] = {"station_id": sid, "station": STATIONS[sid][0], "miles": dist, **cache[sid]}
    return out


# ---------- our own pages ----------
class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.desc, self.canonical, self.h1, self.links = "", None, None, 0, []
        self.ld, self.text, self._in, self._h1 = [], [], None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in = "title"
        elif tag == "meta" and (a.get("name") or "").lower() == "description":
            self.desc = a.get("content") or ""
        elif tag == "link" and (a.get("rel") or "").lower() == "canonical":
            self.canonical = a.get("href")
        elif tag == "h1":
            self._h1 = ""            # counted at </h1> if it has text (an empty one is filled in by script later)
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "script":
            self._in = "ld" if (a.get("type") or "") == "application/ld+json" else "script"
            if self._in == "ld":
                self.ld.append("")
        elif tag in ("style", "noscript", "template"):
            self._in = "skip"

    def handle_endtag(self, tag):
        if tag == "h1" and self._h1 is not None:
            self.h1 += bool(self._h1.strip())
            self._h1 = None
        if tag in ("title", "script", "style", "noscript", "template"):
            self._in = None

    def handle_data(self, data):
        if self._in == "title":
            self.title += data
        elif self._in == "ld":
            self.ld[-1] += data
        elif self._in is None:
            self.text.append(data)
            if self._h1 is not None:
                self._h1 += data


def ld_types(blocks: list[str]) -> tuple[list[str], int]:
    types, faqs = [], 0

    def walk(node):
        nonlocal faqs
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            t = node.get("@type")
            for x in (t if isinstance(t, list) else [t]):
                if x:
                    types.append(x)
            if t == "FAQPage":
                faqs += len(node.get("mainEntity") or [])
            for v in node.values():
                if isinstance(v, (dict, list)):
                    walk(v)
    for b in blocks:
        try:
            walk(json.loads(b))
        except ValueError:
            types.append("INVALID")
    return sorted(set(types)), faqs


def audit_page(path: str, body: str) -> dict:
    p = PageParser()
    p.feed(body)
    types, faqs = ld_types(p.ld)
    words = len(re.findall(r"\w+", " ".join(p.text)))
    page = {"path": path, "title": " ".join(p.title.split()), "description": p.desc, "h1": p.h1, "words": words,
            "schema": types, "faq": faqs, "canonical": p.canonical}
    issues = []
    if not page["title"]:
        issues.append("no title")
    elif len(page["title"]) > 65:
        issues.append(f"title is {len(page['title'])} characters (Google shows about 60)")
    if not p.desc:
        issues.append("no meta description")
    elif len(p.desc) > 165:
        issues.append(f"description is {len(p.desc)} characters (about 155 show)")
    elif len(p.desc) < 70:
        issues.append(f"description is only {len(p.desc)} characters")
    if p.h1 != 1:
        issues.append(f"{p.h1} H1 headings (one is best)")
    if "INVALID" in types:
        issues.append("structured data that doesn't parse")
    if not types and (path in ("/", "/services", "/local", "/about", "/team", "/community")
                      or path.startswith(("/local/", "/services/"))):
        issues.append("no structured data")
    if path.startswith(("/local/", "/services/")) and words < 250:
        issues.append(f"only {words} words")
    page["issues"] = issues
    page["_text"], page["_links"] = " ".join(" ".join(p.text).split()).lower(), p.links
    return page


def site_check(web: Polite, site: str) -> tuple[dict, str]:
    code, sm = web.get(site + "/sitemap.xml")
    if code != 200:
        why = "robots.txt didn't load (site down or suspended?)" if code == 999 else f"sitemap.xml answered {code}"
        return {"site": site, "error": why}, ""
    paths = [urllib.parse.urlsplit(html.unescape(u)).path or "/" for u in re.findall(r"<loc>(.*?)</loc>", sm)]
    pages, texts, links = [], [], set()
    for path in paths:
        code, body = web.get(site + path)
        if code != 200:
            pages.append({"path": path, "issues": [f"answers {code}"]})
            continue
        page = audit_page(path, body)
        texts.append(page.pop("_text"))
        for href in page.pop("_links"):
            u = urllib.parse.urlsplit(urllib.parse.urljoin(site + path, href))
            if f"{u.scheme}://{u.netloc}" == site and u.path not in paths:
                links.add(u.path)
        pages.append(page)
    for label, field in (("title", "title"), ("description", "description")):
        seen = {}
        for p in pages:
            if p.get(field):
                seen.setdefault(p[field], []).append(p["path"])
        for value, where in seen.items():
            for p in pages:
                if len(where) > 1 and p["path"] in where:
                    p["issues"].append(f"same {label} as {', '.join(x for x in where if x != p['path'])}")
    broken = []
    for path in sorted(links)[:60]:
        code, _ = web.get(site + path)
        if code >= 400 and code != 999:
            broken.append({"path": path, "status": code})
    code, llms = web.get(site + "/llms.txt")
    if code == 200:
        texts.append(llms.lower())
    return ({"site": site, "pages": pages, "broken_links": broken, "llms_txt": code == 200,
             "issues": sum(len(p["issues"]) for p in pages) + len(broken)}, " ".join(texts))


def tidy_local(data: dict) -> dict:
    """A check of a local copy (the live site was down) keeps no local addresses in the saved file."""
    site = (data.get("site_check") or {}).get("site") or ""
    if urllib.parse.urlsplit(site).hostname not in ("127.0.0.1", "localhost"):
        return data
    data["site_check"]["site"] = "local copy of the current code"
    for page in data["site_check"].get("pages", []):
        page.pop("canonical", None)
    data["robots_blocked"] = [urllib.parse.urlsplit(u).path if site in u else u for u in data.get("robots_blocked", [])]
    return data


def spanish_text() -> str:
    """Spanish wording lives in static/i18n.js (the pages translate in the browser)."""
    js = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
    return " ".join(re.findall(r':\s*"([^"]+)"', js)).lower()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--site", default=LIVE_SITE, help="site to check (default: the live site)")
    ap.add_argument("--skip-site", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    from app.seo_research import areas_fingerprint
    web = Polite()
    site_report, site_text = ({}, "") if args.skip_site else site_check(web, args.site.rstrip("/"))
    if site_report.get("error"):
        print(f"site: not checked ({site_report['error']})")
    else:
        print(f"site: {site_report.get('issues', 'skipped')} issue(s) on {len(site_report.get('pages', []))} page(s)")
    site_text += " " + spanish_text()
    qs = questions(web, site_text)
    print(f"questions: {len(qs)} ({sum(not q['on_site'] and q['we_offer'] for q in qs)} not on our site yet)")
    how = howto(web)
    print(f"how-to: {len(how)}")
    seasons = season(web)
    print("season: " + ", ".join(f"{k} <- {v['station']} ({v['miles']} mi)" for k, v in seasons.items()))
    data = {
        "collected": date.today().isoformat(), "fingerprint": areas_fingerprint(),
        "sources": {
            "questions": "Google search-box suggestions (suggestqueries.google.com), English and Spanish",
            "howto": "Stack Exchange API, gardening.stackexchange.com (titles and links only)",
            "season": "NOAA NCEI U.S. Climate Normals 1991-2020 (public domain)",
        },
        "season": seasons, "questions": qs, "howto": how, "site_check": site_report,
        "robots_blocked": web.blocked,
    }
    data = tidy_local(data)
    pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.out).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}" + (f" ({len(web.blocked)} URL(s) skipped by robots.txt)" if web.blocked else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
