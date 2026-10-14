import json


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
