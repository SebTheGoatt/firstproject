"""Fetch an Instagram reel's caption and video for evaluation.

    python3 fetch_reel.py <reel url> <out dir>

Writes caption.txt, video.mp4 (when the embed page serves one) and meta.json into <out dir>, and warns when the
reel's shortcode is already in references/reel-log.md (the owner sometimes resends a reel with a new share tail).
The caption comes from the link-preview tags (the page Instagram serves to link unfurlers); the video from the
public /embed/ page, loaded in the pre-installed Chromium.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "references" / "reel-log.md"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


def shortcode(url: str) -> str:
    m = re.search(r"instagram\.com/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)", url)
    if not m:
        sys.exit(f"Not an Instagram reel or post link: {url}")
    return m.group(1)


def caption(code: str) -> str:
    page = subprocess.run(["curl", "-sL", "--max-time", "30", "-A", "facebookexternalhit/1.1",
                           f"https://www.instagram.com/reel/{code}/"], capture_output=True, text=True).stdout
    found = re.findall(r'<meta (?:property|name)="(?:og:title|og:description|description)" content="([^"]*)"', page)
    import html
    return html.unescape(max(found, key=len)) if found else ""


def video_url(code: str) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        exe = CHROME if Path(CHROME).exists() else None
        b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        pg = b.new_page(viewport={"width": 400, "height": 800})
        pg.goto(f"https://www.instagram.com/reel/{code}/embed/", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(4000)
        for sel in ("video", "[aria-label*='Play']", ".EmbedVideo"):
            try:
                pg.locator(sel).first.click(timeout=3000)
                break
            except Exception:
                pass
        pg.wait_for_timeout(5000)
        srcs = pg.evaluate("[...document.querySelectorAll('video')].map(v => v.currentSrc || v.src).filter(Boolean)")
        b.close()
        return srcs[0] if srcs else ""


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    url, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    code = shortcode(url)
    if LOG.exists() and code in LOG.read_text(encoding="utf-8"):
        print(f"ALREADY SEEN: {code} is in the reel log. Point the owner to what was done instead of redoing it.")
    text = caption(code)
    (out / "caption.txt").write_text(text, encoding="utf-8")
    print("caption:", text[:300] or "(none found)")
    src = ""
    try:
        src = video_url(code)
    except Exception as exc:                      # still useful: the caption alone
        print("video: embed page failed:", type(exc).__name__)
    if src.startswith("http"):
        subprocess.run(["curl", "-sL", "--max-time", "120", "-o", str(out / "video.mp4"), src], check=False)
        print("video:", out / "video.mp4")
    else:
        print("video: none (photo post, private, or blocked). Ask the owner to upload it if the frames matter.")
    (out / "meta.json").write_text(json.dumps({"shortcode": code, "url": url, "video": bool(src)}, indent=2))


if __name__ == "__main__":
    main()
