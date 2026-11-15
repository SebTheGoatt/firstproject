"""Market trends that decide Post One's outlook, from official data: growth, new homes, jobs, labor and prices.

    python3 tools/trend_scan.py          # writes data/trends.json

Every series is U.S. government data (Census Bureau, Bureau of Labor Statistics) as republished by FRED, the
Federal Reserve Bank of St. Louis's data service, whose robots.txt welcomes automated visitors (BLS's own and
Census Reporter's robots.txt now turn them away, so they're not used). Read through tools/seo_research.py Polite:
robots.txt first, one request a second, an honest User-Agent. Re-run every quarter.

What each number answers:
  new homes      Houston-metro housing permits: every new house is a new lawn, mostly in exurbs like ours
  population     Houston metro and our three counties: more households to serve
  jobs           Houston-metro jobs: households with income to hire out the mowing
  industry       U.S. jobs in services to buildings and dwellings (includes landscaping): how fast the trade is
                 growing, which is both more competitors and more competition for crew
  prices         Houston consumer prices: the inflation our price has to keep up with
"""

import csv
import io
import json
import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from seo_research import Polite  # noqa: E402

OUT = ROOT / "data" / "trends.json"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="

# key: (FRED id, label, unit, how to read it). Monthly flows (permits) are compared as trailing 12-month totals.
SERIES = {
    "permits_total": ("HOUS448BPPRIVSA", "New homes permitted, Houston metro", "homes / 12 months", "flow"),
    "permits_single": ("HOUS448BP1FHSA", "New single-family homes permitted, Houston metro", "homes / 12 months", "flow"),
    "pop_metro": ("HTNPOP", "Population, Houston metro", "thousand people", "level"),
    "pop_harris": ("TXHARR1POP", "Population, Harris County (Spring, Klein)", "thousand people", "level"),
    "pop_montgomery": ("TXMONT0POP", "Population, Montgomery County (Spring, New Caney, Splendora)", "thousand people", "level"),
    "pop_liberty": ("TXLIBE1POP", "Population, Liberty County (Cleveland, Plum Grove, Colony Ridge)", "thousand people", "level"),
    "jobs_metro": ("HOUS448NA", "Jobs, Houston metro", "thousand jobs", "level"),
    "jobs_industry": ("CES6056170001", "U.S. jobs in services to buildings and dwellings (incl. landscaping)", "thousand jobs", "level"),
    "cpi_houston": ("CUURA318SA0", "Consumer prices, Houston metro (all items)", "index", "level"),
}


def parse(text: str) -> list[tuple[str, float]]:
    rows = []
    for r in csv.reader(io.StringIO(text)):
        if len(r) == 2 and r[0][:4].isdigit():
            try:
                rows.append((r[0], float(r[1])))
            except ValueError:                     # "." or blank = no value that period
                continue
    return rows


def pct(new: float, old: float) -> float | None:
    return round((new / old - 1) * 100, 1) if old else None


def summarize(rows: list[tuple[str, float]], kind: str) -> dict | None:
    """Latest value and its change over 1 and 5 years. Flows compare trailing 12-month totals."""
    if not rows:
        return None
    monthly = len(rows) > 2 and rows[-1][0][5:7] != rows[-2][0][5:7]
    step = 12 if monthly else 1
    if kind == "flow" and monthly:
        if len(rows) < 72:
            return None
        sums = lambda end: sum(v for _, v in rows[end - 12:end])  # noqa: E731
        n = len(rows)
        latest, year_ago, five_ago = sums(n), sums(n - 12), sums(n - 60)
        return {"as_of": rows[-1][0], "value": round(latest), "change_1y": pct(latest, year_ago),
                "change_5y": pct(latest, five_ago)}
    latest = rows[-1][1]
    one = rows[-1 - step][1] if len(rows) > step else None
    five = rows[-1 - 5 * step][1] if len(rows) > 5 * step else None
    return {"as_of": rows[-1][0], "value": round(latest, 2), "change_1y": pct(latest, one) if one else None,
            "change_5y": pct(latest, five) if five else None}


def signals(s: dict) -> list[str]:
    """Plain sentences for the owner and the business plan, only from numbers that came back."""
    out = []
    p = s.get("permits_single")
    if p:
        out.append(f"About {p['value']:,} new single-family homes were permitted in the Houston metro in the 12 months "
                   f"to {p['as_of'][:7]} ({p['change_5y']:+.0f}% vs. five years earlier): new lawns every day.")
    for key, name in (("pop_montgomery", "Montgomery County"), ("pop_liberty", "Liberty County"), ("pop_harris", "Harris County")):
        v = s.get(key)
        if v and v.get("change_5y") is not None:
            out.append(f"{name} grew {v['change_5y']:+.1f}% in five years to {v['value']:,.0f} thousand people ({v['as_of'][:4]}).")
    j = s.get("jobs_industry")
    if j and j.get("change_5y") is not None:
        out.append(f"The building-and-grounds services trade (which includes landscaping) employs {j['value']:,.0f} "
                   f"thousand people nationally, {j['change_5y']:+.1f}% in five years: steady growth, and steady "
                   f"competition for good crew.")
    m = s.get("jobs_metro")
    if m and m.get("change_5y") is not None:
        out.append(f"The Houston metro has {m['value']:,.0f} thousand jobs, {m['change_5y']:+.1f}% in five years: more "
                   f"working households with less time for yard work.")
    c = s.get("cpi_houston")
    if c and c.get("change_1y") is not None:
        out.append(f"Houston consumer prices rose {c['change_1y']:+.1f}% in the year to {c['as_of'][:7]}; "
                   f"a price that stays flat is a real cut each year.")
    return out


def main(argv=None) -> int:
    web = Polite()
    series, missing = {}, []
    for key, (fid, label, unit, kind) in SERIES.items():
        code, body = web.get(FRED + fid)
        if code == 0:                              # timed out once: one more try, then move on
            code, body = web.get(FRED + fid)
        summary = summarize(parse(body), kind) if code == 200 else None
        if summary is None:
            missing.append(f"{fid} ({'robots.txt' if code == 999 else code})")
            continue
        series[key] = {"id": fid, "label": label, "unit": unit, "source": f"https://fred.stlouisfed.org/series/{fid}",
                       **summary}
        print(f"  {label:<72} {summary['value']:>12,} {unit:<18} 1y {summary['change_1y']}%  5y {summary['change_5y']}%")
    data = {"collected": date.today().isoformat(), "series": series, "signals": signals(series),
            "missing": missing, "method": "U.S. government data via FRED (Federal Reserve Bank of St. Louis); robots.txt obeyed."}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(series)} series" + (f"; missing: {', '.join(missing)}" if missing else "") + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
