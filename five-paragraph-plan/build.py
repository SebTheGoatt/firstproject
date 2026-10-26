"""Build The Five-Paragraph Plan from src/.

    python3 build.py [--buy-url https://...]

Writes:
- index.html: the public page (sales + paragraphs 1 and 2 free), published as the Claude artifact.
- dist/Five-Paragraph-Plan-Field-Kit/ and its .zip: the paid kit (full planner + Field Notebook PDF).
  dist/ is git-ignored on purpose: this repo is public, so the paid files never get committed.
"""
import argparse
import json
import re
import shutil
from pathlib import Path

import notebook

HERE = Path(__file__).parent
FREE_FIELDS = ("op_", "sit_", "mis_")
# The checkout link (Gumroad, Lemon Squeezy...). Empty until the product is listed; the Buy buttons then say
# "Checkout opens soon".
BUY_URL = ""


def edition(src, full, examples, buy_url):
    keep, drop = ("FULL", "FREE") if full else ("FREE", "FULL")
    html = re.sub(rf"[ \t]*<!--@{drop}-->.*?<!--@/{drop}-->\n?", "", src, flags=re.S)
    html = re.sub(rf"[ \t]*<!--@/?{keep}-->\n?", "", html)
    if not full:
        examples = {k: {f: v for f, v in ex.items() if f.startswith(FREE_FIELDS)} for k, ex in examples.items()}
    html = html.replace("/*@FULL_FLAG@*/true", "true" if full else "false")
    html = html.replace("/*@EXAMPLES@*/{}", json.dumps(examples, ensure_ascii=False))
    html = html.replace('"/*@BUY_URL@*/"', json.dumps("" if full else buy_url))
    assert "@FULL" not in html and "@FREE" not in html and "/*@" not in html
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--buy-url", default=BUY_URL)
    args = ap.parse_args()

    src = (HERE / "src/app.html").read_text()
    examples = json.loads((HERE / "src/examples.json").read_text())

    (HERE / "index.html").write_text(edition(src, False, examples, args.buy_url))

    kit = HERE / "dist/Five-Paragraph-Plan-Field-Kit"
    shutil.rmtree(kit, ignore_errors=True)
    kit.mkdir(parents=True)
    head = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n')
    full = edition(src, True, examples, "").replace("<title>", head + "<title>", 1)
    full = full.replace("<div class=\"wrap\">", "</head>\n<body>\n<div class=\"wrap\">", 1) + "</body>\n</html>\n"
    (kit / "The Five-Paragraph Plan.html").write_text(full)
    pages = notebook.build(str(kit / "Field Notebook.pdf"), examples)
    (kit / "Start here.txt").write_text(
        "THE FIVE-PARAGRAPH PLAN · FIELD KIT\n\n"
        "1. Open 'The Five-Paragraph Plan.html' in any browser (phone or computer). It works offline and saves your\n"
        "   order on that device only.\n"
        "2. Print 'Field Notebook.pdf' (US Letter, black and white is fine), or fill it in on a tablet.\n"
        "3. Read page 2 of the notebook first.\n\n"
        "Not working for you? Reply to your receipt email within 30 days for a full refund. No questions asked.\n\n"
        "Thank you for buying it. Now go write your order.\n")
    shutil.make_archive(str(kit), "zip", kit.parent, kit.name)
    print(f"index.html written; kit in {kit} ({pages}-page notebook) and {kit}.zip")


if __name__ == "__main__":
    main()
