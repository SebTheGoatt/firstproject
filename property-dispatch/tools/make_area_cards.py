"""Street-map cards for each service area: every street drawn in Post One colors, the area we mow outlined in brass.

    python3 tools/make_area_cards.py            # writes static/img/area-<slug>-<weekday>.jpg and ...-square.jpg

Run it again whenever an area's boxes or mowing day change in app/zones.py. The weekday is in the file name, so a
changed day points the pages at a file that doesn't exist yet and tests/test_area_cards.py fails until this is re-run.

The wide card (1200x630) is the share image of the area page and its neighborhood pages; the square card (1080x1080)
is for social posts and is offered on the owner's marketing page. Streets come from OpenFreeMap vector tiles
(OpenStreetMap data, ODbL), the same tiles as the home page map, so every card credits OpenStreetMap.
Needs Playwright with Chromium (a dev tool; nothing here runs on the server).
"""

import asyncio
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.local_pages import AREAS, area_card_path  # noqa: E402
from app.zones import WEEKDAY_NAMES, short_name, zone_by_key  # noqa: E402

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
SIZES = {"wide": (1200, 630), "square": (1080, 1080)}
K = 3   # the map renders 3x larger, then shrinks to fit: close enough in for the tiles to carry every street
INK = {"ground": "#0f2b22", "water": "#0b2119", "minor": "#4f8a6a", "mid": "#7fb08f", "major": "#9bd15a",
       "brass": "#c9a227", "on_dark": "#f5f6f1", "muted": "#c9d3cd", "fresh": "#9bd15a"}


def style() -> dict:
    road = lambda cls: ["match", ["get", "class"], cls, True, False]  # noqa: E731
    width = lambda px: px * K  # noqa: E731   card pixels, drawn on the 3x map
    return {
        "version": 8,
        "sources": {"omt": {"type": "vector", "url": "https://tiles.openfreemap.org/planet"}},
        "layers": [
            {"id": "ground", "type": "background", "paint": {"background-color": INK["ground"]}},
            {"id": "water", "type": "fill", "source": "omt", "source-layer": "water", "paint": {"fill-color": INK["water"]}},
            {"id": "minor", "type": "line", "source": "omt", "source-layer": "transportation",
             "filter": road(["minor", "service"]), "layout": {"line-cap": "round", "line-join": "round"},
             "paint": {"line-color": INK["minor"], "line-width": width(0.5)}},
            {"id": "mid", "type": "line", "source": "omt", "source-layer": "transportation",
             "filter": road(["tertiary", "secondary"]), "layout": {"line-cap": "round", "line-join": "round"},
             "paint": {"line-color": INK["mid"], "line-width": width(1.1)}},
            {"id": "major", "type": "line", "source": "omt", "source-layer": "transportation",
             "filter": road(["primary", "trunk", "motorway"]), "layout": {"line-cap": "round", "line-join": "round"},
             "paint": {"line-color": INK["major"], "line-width": width(2.2)}},
        ],
    }


def page(area, size: str) -> str:
    zone = zone_by_key(area.zone_key)
    w, h = SIZES[size]
    boxes = [list(b) for b in zone.boxes]
    wide = size == "wide"
    pad = {"top": 48, "right": 48, "bottom": 48, "left": 600} if wide else {"top": 70, "right": 70, "bottom": 520, "left": 70}
    pad = {k: v * K for k, v in pad.items()}
    fonts = (ROOT / "static" / "fonts").as_uri()
    lockup = (ROOT / "static" / "brand" / "post-one-lockup-reversed.svg").as_uri()
    name = short_name(zone)
    day = WEEKDAY_NAMES[zone.service_weekday]
    title_px = (96 if len(name) <= 14 else 70) if wide else (120 if len(name) <= 14 else 92)
    panel = ("left:0;top:0;bottom:0;width:560px;padding:56px 0 48px 56px;"
             f"background:linear-gradient(90deg,{INK['ground']} 0,{INK['ground']} 62%,rgba(15,43,34,0) 100%)") if wide else \
            ("left:0;right:0;bottom:0;height:470px;padding:0 64px 60px;"
             f"background:linear-gradient(0deg,{INK['ground']} 0,{INK['ground']} 66%,rgba(15,43,34,0) 100%)")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
@font-face {{ font-family: "BSD"; font-weight: 800; src: url("{fonts}/big-shoulders-display-800.woff2") format("woff2"); }}
@font-face {{ font-family: "PS"; font-weight: 400; src: url("{fonts}/public-sans-400.woff2") format("woff2"); }}
@font-face {{ font-family: "PS"; font-weight: 700; src: url("{fonts}/public-sans-700.woff2") format("woff2"); }}
html, body {{ margin: 0; width: {w}px; height: {h}px; overflow: hidden; background: {INK['ground']}; }}
#map {{ position: absolute; left: 0; top: 0; width: {w * K}px; height: {h * K}px; transform: scale({1 / K}); transform-origin: 0 0; }}
.maplibregl-ctrl-attrib, .maplibregl-ctrl-logo {{ display: none !important; }}
.panel {{ position: absolute; box-sizing: border-box; {panel}; display: flex; flex-direction: column;
  justify-content: flex-end; gap: 14px; color: {INK['on_dark']}; font-family: "PS", sans-serif; }}
.kicker {{ font: 700 17px/1.3 "PS"; letter-spacing: .12em; text-transform: uppercase; color: {INK['muted']}; }}
h1 {{ margin: 0; font: 800 {title_px}px/.92 "BSD"; text-transform: uppercase; letter-spacing: .01em; max-width: 470px; }}
.day {{ font: 700 26px/1.25 "PS"; color: {INK['fresh']}; }}
.sub {{ font: 400 19px/1.4 "PS"; color: {INK['muted']}; }}
.lockup {{ height: 58px; width: auto; align-self: flex-start; margin-top: 18px; }}
.edge {{ position: absolute; left: 0; right: 0; top: 0; height: 6px; background: {INK['brass']}; z-index: 2; }}
.credit {{ position: absolute; right: 14px; bottom: 10px; font: 400 12px/1 "PS"; color: {INK['muted']}; opacity: .8; }}
</style></head><body>
<div id="map"></div>
<div class="edge"></div>
<div class="panel">
  <div class="kicker">Lawn mowing · {area.county}, TX</div>
  <h1>{name}</h1>
  <div class="day">Mowed every {day}</div>
  <div class="sub">See your price before you book.</div>
  <img class="lockup" src="{lockup}" alt="">
</div>
<div class="credit">© OpenStreetMap contributors · OpenFreeMap</div>
<script>
const boxes = {json.dumps(boxes)};
const ring = ([w, s, e, n]) => [[w, s], [e, s], [e, n], [w, n], [w, s]];
const map = new maplibregl.Map({{ container: "map", style: {json.dumps(style())}, interactive: false,
  attributionControl: false, fadeDuration: 0, canvasContextAttributes: {{ preserveDrawingBuffer: true }} }});
map.on("load", () => {{
  // Dim everything outside the areas we mow, then outline them in brass.
  const world = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]];
  map.addSource("mask", {{ type: "geojson", data: {{ type: "Feature", geometry: {{ type: "Polygon",
    coordinates: [world, ...boxes.map((b) => ring(b).reverse())] }} }} }});
  map.addLayer({{ id: "mask", type: "fill", source: "mask", paint: {{ "fill-color": "{INK['ground']}", "fill-opacity": 0.6 }} }});
  map.addSource("zone", {{ type: "geojson", data: {{ type: "FeatureCollection", features: boxes.map((b) => ({{
    type: "Feature", geometry: {{ type: "Polygon", coordinates: [ring(b)] }} }})) }} }});
  map.addLayer({{ id: "zone", type: "line", source: "zone", paint: {{ "line-color": "{INK['brass']}", "line-width": {2.5 * K},
    "line-dasharray": [3, 2] }} }});
  const all = boxes.flat();
  map.fitBounds([[Math.min(...boxes.map((b) => b[0])), Math.min(...boxes.map((b) => b[1]))],
                 [Math.max(...boxes.map((b) => b[2])), Math.max(...boxes.map((b) => b[3]))]],
                {{ padding: {json.dumps(pad)}, duration: 0 }});
  map.once("idle", () => document.fonts.ready.then(() => (window.cardReady = true)));
}});
</script></body></html>"""


async def main() -> None:
    from playwright.async_api import async_playwright

    out = ROOT / "static"
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=CHROME, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        with tempfile.TemporaryDirectory() as tmp:
            for area in AREAS:
                for size, (w, h) in SIZES.items():
                    html = pathlib.Path(tmp) / f"{area.slug}-{size}.html"
                    html.write_text(page(area, size))
                    pg = await browser.new_page(viewport={"width": w, "height": h})
                    await pg.goto(html.as_uri())
                    await pg.wait_for_function("window.cardReady === true", timeout=90_000)
                    await pg.wait_for_timeout(300)
                    target = out / area_card_path(area, square=size == "square").removeprefix("/static/")
                    await pg.screenshot(path=str(target), type="jpeg", quality=82)
                    await pg.close()
                    print(f"{target.relative_to(ROOT)}  {target.stat().st_size // 1024} KB")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
