"""MuAPI client against a local stand-in server: chains, upload, errors, safe downloads."""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CALLS = []
STATE = {"fail": None, "submit_status": 200}


class StandIn(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/api/v1/upload_file":
            CALLS.append({"upload": len(raw), "type": self.headers["Content-Type"].split(";")[0], "key": self.headers["x-api-key"]})
            return self._json({"url": f"{BASE}/files/photo.jpg"})
        if STATE["submit_status"] != 200:
            return self._json({"detail": "nope"}, STATE["submit_status"])
        model = self.path.rsplit("/", 1)[-1]
        CALLS.append({"model": model, "body": json.loads(raw)})
        self._json({"request_id": f"job-{model}"})

    def do_GET(self):
        if self.path.startswith("/files/"):
            body = b"result-bytes"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        job = self.path.split("/")[-2]
        if job == f"job-{STATE['fail']}":
            return self._json({"status": "failed", "error": {"message": "model overloaded"}}, 400)
        ext = "mp4" if "video" in job or "i2v" in job else "png"
        self._json({"status": "completed", "outputs": [f"{BASE}/files/{job}.{ext}"]})


SERVER = ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
BASE = f"http://127.0.0.1:{SERVER.server_address[1]}"
threading.Thread(target=SERVER.serve_forever, daemon=True).start()
import goat_core as core  # noqa: E402

# The module may already be imported by another test file: point it at the stand-in.
core.API_BASE = BASE
core.POLL_INTERVAL = 0.01


class Client(unittest.TestCase):
    def setUp(self):
        CALLS.clear()
        STATE.update(fail=None, submit_status=200)

    def test_upload(self):
        url = core.upload_image("k", b"\xff\xd8fake-jpeg")
        self.assertEqual(url, f"{BASE}/files/photo.jpg")
        self.assertEqual(CALLS[0]["type"], "multipart/form-data")
        self.assertEqual(CALLS[0]["key"], "k")

    def test_two_step_chain_feeds_step_one_into_step_two(self):
        photo = f"{BASE}/files/photo.jpg"
        urls = core.run_skill("k", "product-ad-video", {}, photo, log=lambda *_: None)
        self.assertEqual([c["model"] for c in CALLS], ["flux-2-pro-edit", "wan2.5-image-to-video"])
        self.assertEqual(CALLS[0]["body"]["images_list"], [photo])
        self.assertEqual(CALLS[0]["body"]["aspect_ratio"], "auto")
        self.assertEqual(CALLS[1]["body"]["image_url"], urls[0])
        self.assertTrue(urls[1].endswith(".mp4"))

    def test_text_skill_uses_your_words(self):
        core.run_skill("k", "youtube-thumbnail", {"subject": "a goat", "headline": "GOAT MODE"}, log=lambda *_: None)
        body = CALLS[0]["body"]
        self.assertIn('"GOAT MODE"', body["prompt"])
        self.assertEqual((body["aspect_ratio"], body["resolution"]), ("16:9", "2K"))

    def test_failures_are_explained(self):
        STATE["fail"] = "wan2.5-image-to-video"
        with self.assertRaisesRegex(core.GoatError, r"model overloaded \(step 2 of 2\)"):
            core.run_skill("k", "product-ad-video", {}, f"{BASE}/files/p.jpg", log=lambda *_: None)
        STATE.update(fail=None, submit_status=402)
        with self.assertRaisesRegex(core.GoatError, "out of credit"):
            core.run_model("k", "flux-dev-image", {"prompt": "x"}, log=lambda *_: None)
        with self.assertRaisesRegex(core.GoatError, 'Fill in "Brand name"'):
            core.run_skill("k", "logo", {})
        with self.assertRaisesRegex(core.GoatError, "Invalid model"):
            core.run_model("k", "../admin", {"prompt": "x"})

    def test_downloads_only_from_muapi(self):
        self.assertEqual(core.download(f"{BASE}/files/x.png"), b"result-bytes")
        for bad in ("http://evil.example/x.mp4", "https://muapi.ai.evil.example/x", "file:///etc/passwd"):
            with self.assertRaises(core.GoatError):
                core.download(bad)

    def test_key_resolution(self):
        os.environ.pop("MUAPI_API_KEY", None)
        with self.assertRaisesRegex(core.GoatError, "No MuAPI key"):
            core.resolve_key("")
        self.assertEqual(core.resolve_key("  abc "), "abc")


if __name__ == "__main__":
    unittest.main()
