"""Check pages the way the standard requires before shipping: 1440 / 768 / 390 px, page errors, sideways scroll,
and an axe-core accessibility pass (WCAG 2 A + AA), with a full-page screenshot of each.

    python3 page_check.py --base http://127.0.0.1:8930 --paths /community /owner/community \\
        [--token crew-test-token-123] [--webgl] [--reduced] [--wait 1500] [--out <dir>]

--token   saves the crew/owner token in localStorage first (owner and crew pages)
--webgl   software WebGL, for MapLibre maps and 3D layers
--reduced also loads each page with prefers-reduced-motion: reduce (check animations stay put)
Exit code 1 if any page has an error, scrolls sideways or has an axe violation. Look at the screenshots too.
"""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
AXE_URL = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js"
WIDTHS = ((1440, 900), (768, 1024), (390, 844))


def axe_source(cache: Path) -> str:
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(AXE_URL, timeout=30) as r:
            cache.write_bytes(r.read())
    return cache.read_text(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--paths", nargs="+", required=True)
    ap.add_argument("--token")
    ap.add_argument("--webgl", action="store_true")
    ap.add_argument("--reduced", action="store_true")
    ap.add_argument("--wait", type=int, default=1500, help="ms to wait after load (maps need ~5000)")
    ap.add_argument("--out", default="page-check")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    axe = axe_source(out / "axe.min.js")
    args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] if a.webgl else []
    bad = 0
    with sync_playwright() as p:
        exe = CHROME if Path(CHROME).exists() else None
        b = p.chromium.launch(executable_path=exe, args=args) if exe else p.chromium.launch(args=args)
        motions = ("no-preference", "reduce") if a.reduced else ("no-preference",)
        for motion in motions:
            for path in a.paths:
                for w, h in WIDTHS:
                    ctx = b.new_context(viewport={"width": w, "height": h}, reduced_motion=motion)
                    if a.token:
                        ctx.add_init_script(f"try {{ localStorage.setItem('crewToken', {json.dumps(a.token)}) }} catch {{}}")
                    pg = ctx.new_page()
                    errors: list[str] = []
                    pg.on("pageerror", lambda e: errors.append(str(e)[:160]))
                    pg.goto(a.base.rstrip("/") + path, wait_until="networkidle", timeout=90000)
                    pg.wait_for_timeout(a.wait)
                    scroll = pg.evaluate("document.documentElement.scrollWidth")
                    pg.add_script_tag(content=axe)
                    violations = pg.evaluate("axe.run({runOnly: ['wcag2a', 'wcag2aa']})"
                                             ".then(r => r.violations.map(v => `${v.id} x${v.nodes.length}: ${v.nodes[0].target}`))")
                    slug = re.sub(r"[^A-Za-z0-9]+", "-", path).strip("-") or "home"
                    name = f"{slug}-{w}{'-reduced' if motion == 'reduce' else ''}.png"
                    pg.screenshot(path=str(out / name), full_page=True)
                    ok = not errors and scroll <= w and not violations
                    bad += not ok
                    print(f"{'OK  ' if ok else 'FAIL'} {path} {w}px{' reduced' if motion == 'reduce' else ''}: "
                          f"scroll {scroll}, axe {violations or 'clean'}, errors {errors or 'none'} -> {out / name}")
                    ctx.close()
        b.close()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
