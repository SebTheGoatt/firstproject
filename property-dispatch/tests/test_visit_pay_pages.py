"""The customer's visit and payment pages (/visit, /pay): Post Green band, status steps, receipt and actions."""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"


def test_visit_page_has_the_band_steps_and_every_control(client):
    t = client.get("/visit/K7MX3QPA").text
    assert 'class="site page-visit-pay"' in t and "{{" not in t
    assert '<p class="eyebrow">Your visit</p>' in t and 'id="v-title"' in t
    # The steps come from the visit's own status (pending / scheduled / completed / cancelled) and on-the-way time.
    assert 'class="vp-steps" id="v-timeline"' in t
    for label in ('"Booked"', '"Crew on the way"', '"Done"', '"Route planned"', "Arriving between"):
        assert label in t, label
    for control in ('id="v-pay-link"', 'id="cancel-btn">Cancel this visit</button>', 'id="push-btn"',
                    'id="other-code">Use a different code</button>', 'id="forget-btn">Delete my information</button>'):
        assert control in t, control
    assert re.search(r'id="v-cancelled"[^>]*hidden>\s*<h2 class="vp-cancelled-title">This visit was cancelled\.</h2>', t)


def test_pay_page_has_the_band_and_the_pay_form(client):
    t = client.get("/pay/whatever-token-value").text
    assert 'class="site page-visit-pay"' in t and "{{" not in t
    assert '<p class="eyebrow">Pay your way</p>' in t and '<h1 id="hello">' in t
    for el in ('id="svc"', 'id="when"', 'id="tax-row" class="tax"', 'id="chips"', 'id="pay-btn"'):
        assert el in t, el


def test_visit_and_pay_pages_have_no_inline_styles():
    for page in ("visit.html", "pay.html"):
        assert ' style="' not in (STATIC / page).read_text(encoding="utf-8"), page
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "/* ===== visit-pay (Post One) ===== */" in css
