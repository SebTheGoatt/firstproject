"""The service map poster: every street across all our areas, each area outlined with its mowing day, and a QR code
that books. 18x24 in at 150 dpi, for a print shop, the office wall or an event table.

    python3 tools/make_area_poster.py                       # QR points at PUBLIC_BASE_URL or the live Render site
    python3 tools/make_area_poster.py https://postonelawn.com

Writes static/img/service-map-<fingerprint>.jpg and .pdf (see app.marketing.poster_path). Run it again when an area's
boxes or day change, or when the site moves to its own domain. The QR carries ?ref=poster, so bookings from it show up
on the marketing scoreboard. Streets: OpenFreeMap tiles (OpenStreetMap data, ODbL), credited on the poster.
Needs Playwright with Chromium and Pillow (dev tools; nothing here runs on the server).
"""

import asyncio
import base64
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from make_area_cards import CHROME, INK, style  # noqa: E402

from app.marketing import poster_path, qr_svg  # noqa: E402
from app.zones import SERVICE_ZONES, WEEKDAY_NAMES, short_name  # noqa: E402

W, H, DPI = 2700, 3600, 150      # 18 x 24 in
MAP_H = 2350                     # the map's band at the top; the words sit below it
K = 2                            # the map renders 2x larger, then shrinks: close enough in for every street
LIVE = "https://property-dispatch.onrender.com"


def page(site: str) -> str:
    zones = sorted(SERVICE_ZONES, key=lambda z: z.service_weekday)
    boxes = [list(b) for z in zones for b in z.boxes]
    # One tag per box, on its top-left corner. Cleveland's second box is Plum Grove; it sits right beside Colony
    # Ridge, so its tag goes under the box (right-aligned) to stay clear of Colony Ridge's outline.
    labels = []
    for z in zones:
        for i, b in enumerate(z.boxes):
            name = short_name(z)
            if z.key == "CLEVELAND_HUB":
                name = "Cleveland" if i == 0 else "Plum Grove"
            labels.append({"box": list(b), "text": f"{WEEKDAY_NAMES[z.service_weekday][:3]} · {name}", "below": i > 0})
    week = "".join(f'<li><b>{WEEKDAY_NAMES[z.service_weekday][:3]}</b><span>{short_name(z)}</span></li>' for z in zones)
    week += '<li><b>Sat</b><span>Weather make-ups</span></li>'
    qr = base64.b64encode(qr_svg(f"{site}/?ref=poster")).decode()
    host = site.removeprefix("https://").removeprefix("http://")
    fonts = (ROOT / "static" / "fonts").as_uri()
    lockup = (ROOT / "static" / "brand" / "post-one-lockup-reversed.svg").as_uri()
    pad = {k: v * K for k, v in {"top": 170, "right": 150, "bottom": 150, "left": 150}.items()}
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
@font-face {{ font-family: "BSD"; font-weight: 800; src: url("{fonts}/big-shoulders-display-800.woff2") format("woff2"); }}
@font-face {{ font-family: "PS"; font-weight: 400; src: url("{fonts}/public-sans-400.woff2") format("woff2"); }}
@font-face {{ font-family: "PS"; font-weight: 700; src: url("{fonts}/public-sans-700.woff2") format("woff2"); }}
html, body {{ margin: 0; width: {W}px; height: {H}px; overflow: hidden; background: {INK['ground']}; color: {INK['on_dark']}; }}
#map {{ position: absolute; left: 0; top: 0; width: {W * K}px; height: {MAP_H * K}px; transform: scale({1 / K}); transform-origin: 0 0; }}
.maplibregl-ctrl-attrib, .maplibregl-ctrl-logo {{ display: none !important; }}
.edge {{ position: absolute; left: 0; right: 0; top: 0; height: 14px; background: {INK['brass']}; z-index: 3; }}
.fade {{ position: absolute; left: 0; right: 0; top: {MAP_H - 260}px; height: 260px; z-index: 1;
  background: linear-gradient(180deg, rgba(15,43,34,0), {INK['ground']}); }}
.tag.below {{ transform: translate(-100%, 14px); margin-top: 0; }}
.tag {{ position: absolute; z-index: 2; transform: translateY(-100%); margin-top: -14px; white-space: nowrap;
  font: 700 40px/1 "PS"; letter-spacing: .06em; text-transform: uppercase; color: {INK['ground']};
  background: {INK['brass']}; padding: 14px 20px; border-radius: 10px; }}
.words {{ position: absolute; left: 150px; right: 150px; top: {MAP_H - 40}px; bottom: 120px; z-index: 2;
  display: grid; grid-template-columns: 1fr 520px; grid-template-rows: auto auto 1fr; column-gap: 110px; row-gap: 40px; }}
h1 {{ grid-column: 1 / -1; margin: 0; font: 800 250px/.9 "BSD"; text-transform: uppercase; letter-spacing: .01em; }}
.lede {{ margin: 0; font: 400 58px/1.3 "PS"; color: {INK['muted']}; }}
.lede b {{ color: {INK['fresh']}; font-weight: 700; }}
ul {{ grid-column: 1; list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(2, 1fr); gap: 22px 60px; align-content: start; }}
li {{ display: flex; gap: 26px; align-items: baseline; border-top: 3px solid {INK['brass']}; padding-top: 18px; }}
li b {{ font: 800 76px/1 "BSD"; text-transform: uppercase; color: {INK['fresh']}; min-width: 140px; }}
li span {{ font: 700 50px/1.15 "PS"; }}
.qr {{ grid-column: 2; grid-row: 2 / 4; align-self: start; display: grid; gap: 22px; justify-items: center; text-align: center; }}
.qr img {{ width: 520px; height: 520px; background: #fff; border-radius: 24px; padding: 18px; box-sizing: border-box; }}
.qr p {{ margin: 0; font: 700 44px/1.25 "PS"; }}
.qr small {{ font: 400 34px/1.2 "PS"; color: {INK['muted']}; }}
.foot {{ position: absolute; left: 150px; right: 150px; bottom: 90px; z-index: 2; display: flex; justify-content: space-between; align-items: flex-end; }}
.foot img {{ height: 150px; width: auto; }}
.credit {{ font: 400 28px/1 "PS"; color: {INK['muted']}; opacity: .85; }}
</style></head><body>
<div id="map"></div><div class="edge"></div><div class="fade"></div>
<div id="tags"></div>
<div class="words">
  <h1>One area a day</h1>
  <p class="lede">Your street gets the same mowing day <b>every week</b>. See your price before you book.</p>
  <ul>{week}</ul>
  <div class="qr"><img src="data:image/svg+xml;base64,{qr}" alt=""><p>Scan to see your price and book</p><small>{host}</small></div>
</div>
<div class="foot"><img src="{lockup}" alt=""><span class="credit">Streets © OpenStreetMap contributors · OpenFreeMap</span></div>
<script>
const boxes = {json.dumps(boxes)}, labels = {json.dumps(labels)};
const ring = ([w, s, e, n]) => [[w, s], [e, s], [e, n], [w, n], [w, s]];
const map = new maplibregl.Map({{ container: "map", style: {json.dumps(style(K))}, interactive: false,
  attributionControl: false, fadeDuration: 0, canvasContextAttributes: {{ preserveDrawingBuffer: true }} }});
map.on("load", () => {{
  const world = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]];
  map.addSource("mask", {{ type: "geojson", data: {{ type: "Feature", geometry: {{ type: "Polygon",
    coordinates: [world, ...boxes.map((b) => ring(b).reverse())] }} }} }});
  map.addLayer({{ id: "mask", type: "fill", source: "mask", paint: {{ "fill-color": "{INK['ground']}", "fill-opacity": 0.55 }} }});
  map.addSource("zone", {{ type: "geojson", data: {{ type: "FeatureCollection", features: boxes.map((b) => ({{
    type: "Feature", geometry: {{ type: "Polygon", coordinates: [ring(b)] }} }})) }} }});
  map.addLayer({{ id: "zone", type: "line", source: "zone", paint: {{ "line-color": "{INK['brass']}", "line-width": {4 * K},
    "line-dasharray": [3, 2] }} }});
  map.fitBounds([[Math.min(...boxes.map((b) => b[0])), Math.min(...boxes.map((b) => b[1]))],
                 [Math.max(...boxes.map((b) => b[2])), Math.max(...boxes.map((b) => b[3]))]],
                {{ padding: {json.dumps(pad)}, duration: 0 }});
  map.once("idle", () => {{
    // Each area's label sits on its top-left corner (map pixels are K times the poster's).
    for (const l of labels) {{
      const p = l.below ? map.project([l.box[2], l.box[1]]) : map.project([l.box[0], l.box[3]]);
      const t = document.createElement("div"); t.className = l.below ? "tag below" : "tag"; t.textContent = l.text;
      t.style.left = (p.x / {K}) + "px"; t.style.top = (p.y / {K}) + "px";
      document.getElementById("tags").append(t);
    }}
    document.fonts.ready.then(() => (window.posterReady = true));
  }});
}});
</script></body></html>"""


async def main(site: str) -> None:
    from PIL import Image
    from playwright.async_api import async_playwright

    jpg = ROOT / "static" / poster_path("jpg").removeprefix("/static/")
    pdf = ROOT / "static" / poster_path("pdf").removeprefix("/static/")
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=CHROME, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        with tempfile.TemporaryDirectory() as tmp:
            html = pathlib.Path(tmp) / "poster.html"
            html.write_text(page(site))
            pg = await browser.new_page(viewport={"width": W, "height": H})
            await pg.goto(html.as_uri())
            await pg.wait_for_function("window.posterReady === true", timeout=240_000)
            await pg.wait_for_timeout(500)
            await pg.screenshot(path=str(jpg), type="jpeg", quality=86)
        await browser.close()
    Image.open(jpg).convert("RGB").save(pdf, "PDF", resolution=DPI)        # prints at 18 x 24 in
    for f in (jpg, pdf):
        print(f"{f.relative_to(ROOT)}  {f.stat().st_size // 1024} KB")


if __name__ == "__main__":
    asyncio.run(main((sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PUBLIC_BASE_URL") or LIVE).rstrip("/")))
