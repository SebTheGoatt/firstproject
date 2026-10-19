import json
import re

from app.config import Settings


def test_pages_render_with_business_name_and_version(client, settings):
    for path in ("/", "/book", "/crew"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
        assert "{{" not in r.text, f"unrendered placeholder on {path}"
        assert settings.business_name in r.text
        assert "/static/site.js?v=" in r.text
        assert 'rel="manifest"' in r.text and "apple-touch-icon" in r.text


def test_business_name_is_html_escaped(settings, repo):
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings.business_name = "<b>Bob's</b> Lawns"
    r = TestClient(create_app(settings, repo=repo, sms=None)).get("/")
    assert "<b>Bob" not in r.text and "&lt;b&gt;Bob&#x27;s&lt;/b&gt; Lawns" in r.text


def test_default_brand_is_post_one_lawn_co(client, settings):
    """The public name is Post One Lawn Co.; the legal name (who customers contract with) stays Semper Green LLC."""
    assert Settings.model_fields["business_name"].default == "Post One Lawn Co."
    assert settings.business_name == "Post One Lawn Co." and settings.legal_name == "Semper Green LLC"
    t = client.get("/").text
    assert re.search(r"<title>[^<]*Post One Lawn Co\.[^<]*</title>", t)
    assert '<meta name="apple-mobile-web-app-title" content="Post One">' in t
    d = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', t, re.S).group(1))
    assert d["name"] == "Post One Lawn Co." and d["legalName"] == "Semper Green LLC"
    for path in ("/", "/book", "/team", "/visit", "/about", "/local", "/local/spring", "/privacy", "/terms", "/refunds"):
        assert "Semper Green Lawn Care" not in client.get(path).text, path     # the old public name is gone
    m = client.get("/manifest.webmanifest").json()
    assert (m["name"], m["short_name"], m["theme_color"], m["background_color"]) == (
        "Post One Lawn Co.", "Post One", "#0F2B22", "#F5F6F1")
    assert client.get("/crew.webmanifest").json()["name"] == "Post One Lawn Co. Crew"


def test_header_logo_is_the_post_one_wordmark_built_from_the_name(client, settings, repo):
    """Logo A's mark and a two-line wordmark on every page with a header; screen readers hear the full name once."""
    from fastapi.testclient import TestClient

    from app.local_pages import brand_lines
    from app.main import create_app

    assert brand_lines("Post One Lawn Co.") == ("Post One", "Lawn Co.")
    assert brand_lines("Semper Green LLC") == ("Semper Green LLC", "")       # no "Lawn" in the name: one line
    wordmark = ('<span class="wordmark" aria-hidden="true" data-no-i18n><span class="wm-top">Post One</span>'
                '<span class="wm-sub">Lawn Co.</span></span><span class="visually-hidden">Post One Lawn Co.</span>')
    for path in ("/", "/book", "/team", "/visit", "/pay/abc", "/about", "/local", "/local/spring", "/privacy", "/no-such-page"):
        t = client.get(path, headers={"Accept": "text/html"}).text
        assert '<a class="brand" href="/"><svg class="brand-mark"' in t and 'aria-hidden="true" focusable="false"' in t, path
        assert wordmark in t and "logo-64.png" not in t, path
    assert '<p class="crew-brandbar-name">Post One · <span>Crew</span></p>' in client.get("/crew").text
    settings.business_name = "Acme Lawn Care"            # a new name still reads right in the wordmark
    t = TestClient(create_app(settings, repo=repo, sms=None)).get("/book").text
    assert '<span class="wm-top">Acme</span><span class="wm-sub">Lawn Care</span>' in t and '<span class="wm-top">Post One' not in t


def test_fonts_are_self_hosted(client):
    """Big Shoulders Display and Public Sans come from /static/fonts: no third-party font requests."""
    css = client.get("/static/styles.css").text
    for family, weight in (("Big Shoulders Display", 700), ("Big Shoulders Display", 800), ("Public Sans", 400),
                           ("Public Sans", 500), ("Public Sans", 600), ("Public Sans", 700)):
        file = f"/static/fonts/{family.lower().replace(' ', '-')}-{weight}.woff2"
        assert re.search(rf'font-family: "{family}"; font-style: normal; font-weight: {weight}; font-display: swap;\s*'
                         rf'src: url\("{re.escape(file)}"\) format\("woff2"\)', css), (family, weight)
        r = client.get(file)
        assert r.status_code == 200 and r.content[:4] == b"wOF2"
    for path in ("/", "/book", "/about", "/crew"):
        assert "fonts.googleapis.com" not in client.get(path).text and "fonts.gstatic.com" not in client.get(path).text
    assert "fonts.googleapis.com" not in css and "@import" not in css


def test_service_worker_names_the_business_from_settings(client, settings, repo):
    from fastapi.testclient import TestClient

    from app.main import create_app

    sw = client.get("/sw.js").text
    assert '"Tap to open Post One Lawn Co."' in sw and '|| "Post One Lawn Co.", options' in sw and "__BUSINESS_NAME__" not in sw
    settings.business_name = 'Bob\'s "Best" Lawns'
    sw = TestClient(create_app(settings, repo=repo, sms=None)).get("/sw.js").text
    assert '"Tap to open Bob\'s \\"Best\\" Lawns"' in sw      # a quote in the name can't end the JS string


def test_manifests_are_valid_and_installable(client):
    for path, start, scope in (("/manifest.webmanifest", "/?source=app", "/"),
                               ("/crew.webmanifest", "/crew?source=app", "/crew")):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
        m = json.loads(r.text)
        assert m["display"] == "standalone" and m["start_url"] == start and m["scope"] == scope
        sizes = {i["sizes"] for i in m["icons"]}
        assert {"192x192", "512x512"} <= sizes
        assert any(i.get("purpose") == "maskable" for i in m["icons"])
        for icon in m["icons"]:
            assert client.get(icon["src"]).status_code == 200


def test_service_worker_is_served_from_root_with_version(client):
    r = client.get("/sw.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert "__VERSION__" not in r.text
    assert r.headers["cache-control"] == "no-cache"


def test_robots_hides_crew_and_api(client):
    r = client.get("/robots.txt").text
    assert "Disallow: /crew" in r and "Disallow: /api/" in r


def test_favicon(client):
    assert client.get("/favicon.ico").status_code == 200


def test_link_preview_uses_the_post_one_share_image(client):
    """Texts, Facebook and Google show the og:image when the link is shared. It must be a full address and a new
    file name, so apps that saved the old Semper Green picture under the old name fetch the new one."""
    t = client.get("/").text
    m = re.search(r'<meta property="og:image" content="([^"]+)">', t)
    assert m and m.group(1).startswith("http") and m.group(1).endswith("/static/icons/post-one-share.jpg")
    assert '<meta name="twitter:card" content="summary_large_image">' in t and "social.jpg" not in t
    assert client.get("/static/icons/post-one-share.jpg").status_code == 200
    assert client.get("/static/icons/social.jpg").status_code == 404
    assert "post-one-share.jpg" in client.get("/local/spring").text
