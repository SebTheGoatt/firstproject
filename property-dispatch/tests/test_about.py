"""About page: founders' bios as written, and only true statements about how the business works."""

from app.about_page import FOUNDERS


def test_about_page_has_both_founders_and_true_pillars(client, settings):
    r = client.get("/about")
    assert r.status_code == 200
    t = r.text
    for name, role, tag, _ in FOUNDERS:
        assert name in t and role in t and tag in t
    assert "Ciro" not in t and "RXO" not in t and len(FOUNDERS) == 1
    assert "Built on Pedigree. Driven by <span>Discernment.</span>" in t
    assert "5:00 PM sharp" in t and "cutting down the fuel" in t
    assert "Holiday toy drive for local kids" in t and "Local veterans and their families" in t   # real causes
    for false_claim in ("completely erasing", "verified, local combat veteran", "encrypted payment rails", "service dogs"):
        assert false_claim not in t


def test_about_is_linked_and_in_the_sitemap(client):
    assert 'href="/about"' in client.get("/").text and 'href="/about"' in client.get("/local/spring").text
    assert "/about</loc>" in client.get("/sitemap.xml").text
