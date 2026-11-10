"""How lawn services that compete in our areas present themselves online, next to how we do.

    python3 tools/competitor_scan.py             # writes data/competitor-scan.json (totals only)
    python3 tools/competitor_scan.py --details   # also prints the site-by-site table (for the owner; not saved)

It reads ONE public page per business (the page a customer lands on for our area) and notes what that page tells a
customer: is a price shown, can you book online, is there Spanish, are texts, photos, a set day, a guarantee or
giving mentioned. The same checks run on our own home page, so the comparison is like for like.

Rules it keeps:
- Business websites only, found by ordinary web search (the SITES list). No people, no reviews, no review sites,
  no social profiles, no logins, nothing behind a form.
- robots.txt is read and obeyed, one request a second, an honest User-Agent (tools/seo_research.py Polite).
- The saved file holds totals ("4 of 11 show a price"), never a claim about a named business: a page check can
  misread a site, and the repo is public. Site-by-site rows are printed for the owner with --details.
- Research only. It never posts, reviews, reports or contacts anyone. We win by being clearer, not by attacking.
"""

import argparse
import json
import pathlib
import re
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from seo_research import PageParser, Polite  # noqa: E402

OUT = ROOT / "data" / "competitor-scan.json"

# (kind, page). Found by web search for lawn mowing in Spring, Klein, New Caney and Cleveland TX, Nov 2026.
SITES = (
    ("marketplace", "https://www.lawnstarter.com/spring-tx-lawn-care"),
    ("marketplace", "https://lawnlove.com/texas/houston-lawn-care/spring-lawn-care"),
    ("marketplace", "https://www.tidy.com/locations/spring-tx/lawn-mowing"),
    ("marketplace", "https://www.angi.com/companylist/us/tx/klein/lawn-care.htm"),
    ("marketplace", "https://www.yourgreenpal.com/tx/lawn-care-spring"),
    ("company", "https://www.abchomeandcommercial.com/houston/spring-tx-lawn-services"),
    ("company", "https://www.heroeslawncare.com/woodlands-tx/areas-we-serve/harris-county/klein/"),
    ("company", "https://www.augustalawncareservices.com/tomball"),
    ("company", "https://landscapingspringtexas.com/"),
    ("company", "https://exterior-services.vercel.app/lawn-mowing/spring-tx"),
    ("company", "https://maylandscaping.pages.dev/"),
)

# What a customer can learn from the page: (key, label, pattern on the page's visible text).
FEATURES = (
    ("price", "Shows a price", r"\$\s?\d{2,3}\b"),
    ("book_online", "Lets you book online", r"book (online|now|in|a |your)|schedule (online|now|service)|instant (quote|price)|order (online|now)"),
    ("spanish", "Offers Spanish", r"espa[nñ]ol|se habla|hablamos"),
    ("texts", "Mentions text updates", r"\btext (message|update|alert|notification|you|when)|\bsms\b|notif(y|ication)"),
    ("photos", "Mentions photos of the work", r"before (and|&) after|photos? of|photo proof|pictures? of (the|your)"),
    ("set_day", "Names a set service day", r"same day (each|every) week|set (route )?day|your (scheduled|service|mowing) day|route day"),
    ("no_contract", "Says no contract", r"no (long[- ]term )?contracts?|cancel any ?time|no commitment"),
    ("guarantee", "States a guarantee", r"guarantee|make it right|not (happy|satisfied)"),
    ("veteran", "Says veteran-owned", r"veteran[- ](owned|operated)"),
    ("gives_back", "Mentions giving to a cause", r"donat|charit|gives? back|local cause|nonprofit"),
    ("quote_first", "Asks you to request a quote", r"(free|request an?|get an?|get your) (estimate|quote)|call (us )?(for|today)"),
)


def page_text(body: str) -> str:
    p = PageParser()
    p.feed(body)
    return " ".join(" ".join(p.text).split()).lower() + (" español" if re.search(r'hreflang="es', body) else "")


def features_of(text: str) -> dict:
    return {key: bool(re.search(rx, text)) for key, _, rx in FEATURES}


def ours(body: str | None = None) -> dict:
    """The same checks on our own home page as it is served (what a crawler that runs no scripts reads)."""
    if body is None:
        from fastapi.testclient import TestClient
        from app.config import Settings
        from app.db import MemoryRepository
        from app.main import create_app
        app = create_app(Settings(_env_file=None, data_backend="memory", osrm_url="", crew_access_token="x"),
                         repo=MemoryRepository())
        body = TestClient(app).get("/").text
    return features_of(page_text(body))


def summarize(rows: list[dict], mine: dict) -> list[dict]:
    out = []
    for key, label, _ in FEATURES:
        have = sum(r[key] for r in rows)
        out.append({"key": key, "label": label, "others": have, "of": len(rows),
                    "companies": sum(r[key] for r in rows if r["kind"] == "company"),
                    "marketplaces": sum(r[key] for r in rows if r["kind"] == "marketplace"), "we": mine[key]})
    return out


def scan(web: Polite) -> tuple[list[dict], list[str]]:
    rows, skipped = [], []
    for kind, url in SITES:
        code, body = web.get(url)
        if code != 200 or len(body) < 500:
            skipped.append(f"{url} ({'robots.txt' if code == 999 else code})")
            continue
        text = page_text(body)
        if len(text) < 300:                       # a page drawn entirely by scripts tells us nothing
            skipped.append(f"{url} (no readable text)")
            continue
        rows.append({"site": re.sub(r"^https?://(www\.)?", "", url).split("/")[0], "kind": kind, **features_of(text)})
    return rows, skipped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--details", action="store_true", help="print the site-by-site table (not saved)")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    rows, skipped = scan(Polite())
    mine = ours()
    summary = summarize(rows, mine)
    data = {"collected": date.today().isoformat(), "checked": len(rows),
            "companies": sum(r["kind"] == "company" for r in rows),
            "marketplaces": sum(r["kind"] == "marketplace" for r in rows), "skipped": len(skipped),
            "method": "One public landing page per business, read like a customer would; robots.txt obeyed. "
                      "A page check can miss things, so treat counts as a guide.",
            "features": summary}
    pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.out).write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    print(f"checked {len(rows)} page(s), skipped {len(skipped)}: {'; '.join(skipped) or 'none'}")
    for f in summary:
        print(f"  {f['label']:<32} others {f['others']}/{f['of']}   we: {'yes' if f['we'] else 'no'}")
    if args.details:
        print()
        for r in rows:
            print(f"  {r['site']:<34} {r['kind']:<12} " + ", ".join(k for k, _, _ in FEATURES if r[k]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
