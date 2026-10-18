"""About page: founders' bios as written, and only true statements about how the business works."""

from app.about_page import FOUNDERS


def test_about_page_has_both_founders_and_true_pillars(client, settings):
    r = client.get("/about")
    assert r.status_code == 200
    t = r.text
    for name, role, tag, _ in FOUNDERS:
        assert name in t and role in t and tag in t
    assert "Lawn Care, Run Like an <span>Operation.</span>" in t
    assert "5% less (10% with 5 or more)" in t                                  # the real density discount
    assert "Holiday toy drive for local kids" in t and "Local veterans and their families" in t   # real causes
    for false_claim in ("to zero", "service dogs", "recurring users", "fleet tracking points"):
        assert false_claim not in t


def test_about_is_linked_and_in_the_sitemap(client):
    assert 'href="/about"' in client.get("/").text and 'href="/about"' in client.get("/local/spring").text
    assert "/about</loc>" in client.get("/sitemap.xml").text
