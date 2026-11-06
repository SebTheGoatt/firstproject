"""GOAT CREATIONS core for ComfyUI: catalog, request building and the MuAPI client.

Pure Python (requests only): no ComfyUI or torch imports, so it can be tested on
its own. The catalog (models + Skills) is generated from packages/sebastina-core,
and tests/golden_cases.json proves this port builds the same requests as the
TypeScript engine the desktop and phone apps use.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

import requests

CATALOG = json.loads((Path(__file__).parent / "goat_catalog.json").read_text(encoding="utf-8"))
MODELS: dict[str, dict] = {m["id"]: m for m in CATALOG["models"]}
SKILLS: dict[str, dict] = {s["id"]: s for s in CATALOG["skills"]}

API_BASE = os.environ.get("GOAT_MUAPI_BASE", "https://api.muapi.ai").rstrip("/")
POLL_INTERVAL = float(os.environ.get("GOAT_POLL_INTERVAL", "2"))
SUCCESS = {"completed", "succeeded", "success"}
FAILURE = {"failed", "error", "cancelled", "canceled"}
MODEL_NAME = re.compile(r"^[A-Za-z0-9._-]+$")

RATIO_PIXELS = {
    "1:1": (1024, 1024), "16:9": (1344, 768), "9:16": (768, 1344), "4:3": (1152, 864), "3:4": (864, 1152),
    "3:2": (1216, 832), "2:3": (832, 1216), "21:9": (1536, 640), "9:21": (640, 1536),
}


class GoatError(RuntimeError):
    """A failure with a message meant for the person running the workflow."""


# ---------------------------------------------------------------- catalog helpers

def is_video_model(spec: dict) -> bool:
    return spec["task"] in ("t2v", "i2v")


def models_for(*tasks: str) -> list[str]:
    return [m["id"] for m in CATALOG["models"] if m["task"] in tasks]


def skill_output(skill: dict) -> str:
    last = MODELS.get(skill["steps"][-1]["model"])
    return "video" if last and is_video_model(last) else "image"


# ---------------------------------------------------------------- request building (mirrors models.ts)

def _ratio(r: str) -> float:
    try:
        w, h = (float(x) for x in r.split(":"))
        return w / h if w > 0 and h > 0 else math.nan
    except ValueError:
        return math.nan


def _closest_ratio(allowed: list[str], wanted: float) -> str:
    shaped = [r for r in allowed if not math.isnan(_ratio(r))]
    best = shaped[0]
    for r in shaped[1:]:
        if abs(math.log(_ratio(r) / wanted)) < abs(math.log(_ratio(best) / wanted)):
            best = r
    return best


def grid_size(px: float) -> int:
    # JS Math.round rounds .5 up; Python's round() rounds half to even.
    return int(min(2048, max(128, math.floor(px / 64 + 0.5) * 64)))


def _js_round(x: float) -> int:
    return int(math.floor(x + 0.5))


def build_payload(model_id: str, kind: str, req: dict) -> dict:
    """Build the MuAPI payload for one model. Raises GoatError if a photo model gets no photo."""
    spec = MODELS.get(model_id)
    if spec is None:
        if kind == "video":
            return {
                "prompt": req.get("prompt", ""),
                "aspect_ratio": req.get("aspectRatio") or "16:9",
                "duration": req.get("duration") or 5,
                "resolution": req.get("resolution") or "480p",
            }
        from_ratio = RATIO_PIXELS.get(req.get("aspectRatio") or "")
        return {
            "prompt": req.get("prompt", ""),
            "width": grid_size(req.get("width") or (from_ratio[0] if from_ratio else 1024)),
            "height": grid_size(req.get("height") or (from_ratio[1] if from_ratio else 1024)),
            "num_images": 1,
        }

    payload: dict[str, Any] = {}
    if spec.get("prompt", True) is not False:
        payload["prompt"] = req.get("prompt", "")

    field = spec.get("imageField")
    if field:
        url = req.get("imageUrl")
        if not url:
            raise GoatError(f"{spec['name']} needs a photo.")
        payload[field] = [url] if field == "images_list" else url

    asked = None
    if req.get("aspectRatio"):
        asked = _ratio(req["aspectRatio"])
    elif req.get("width") and req.get("height"):
        asked = req["width"] / req["height"]

    if spec["size"] == "pixels":
        from_ratio = RATIO_PIXELS.get(req.get("aspectRatio") or "")
        payload["width"] = grid_size(req.get("width") or (from_ratio[0] if from_ratio else 1024))
        payload["height"] = grid_size(req.get("height") or (from_ratio[1] if from_ratio else 1024))
        payload["num_images"] = 1
    elif spec["size"] == "aspect" and spec.get("aspectRatios"):
        if asked and not math.isnan(asked):
            payload["aspect_ratio"] = _closest_ratio(spec["aspectRatios"], asked)
        elif spec.get("defaultAspect"):
            payload["aspect_ratio"] = spec["defaultAspect"]
        elif spec["task"] in ("t2i", "t2v"):
            payload["aspect_ratio"] = _closest_ratio(spec["aspectRatios"], 16 / 9 if spec["task"] == "t2v" else 1)

    dur = spec.get("duration")
    if dur:
        d = _js_round(req.get("duration") if req.get("duration") is not None else dur["default"])
        payload["duration"] = min(dur["max"], max(dur["min"], d))
    res = spec.get("resolutions")
    if res:
        wanted = req.get("resolution")
        payload["resolution"] = wanted if wanted in res else (spec.get("defaultResolution") or res[0])
    if spec.get("quality"):
        payload["quality"] = spec["quality"]["default"]
    return payload


def render_prompt(template: str, skill: dict, inputs: dict) -> dict:
    """Fill {field} slots. Returns {"prompt": ...} or {"missing": field} (same shape as skills.ts)."""
    for f in skill["fields"]:
        value = (inputs.get(f["id"]) or "").strip()
        if not value and not f["fallback"] and "{" + f["id"] + "}" in template:
            return {"missing": f}

    def fill(match: re.Match) -> str:
        fid = match.group(1)
        field = next((f for f in skill["fields"] if f["id"] == fid), None)
        value = (inputs.get(fid) or "").strip()[:600]
        return value or (field["fallback"] if field else "") or ""

    return {"prompt": re.sub(r"\{([a-zA-Z_]+)\}", fill, template)}


# ---------------------------------------------------------------- MuAPI client

def resolve_key(key: str | None) -> str:
    key = (key or "").strip() or os.environ.get("MUAPI_API_KEY", "").strip()
    if not key:
        raise GoatError("No MuAPI key. Paste it into the node's api_key field or set MUAPI_API_KEY.")
    return key


def _friendly(resp: requests.Response) -> GoatError:
    if resp.status_code in (401, 403):
        return GoatError("MuAPI rejected the API key.")
    if resp.status_code == 402:
        return GoatError("Your MuAPI account is out of credit. Top up at muapi.ai.")
    if resp.status_code == 429:
        return GoatError("MuAPI is busy right now (rate limited). Try again in a minute.")
    return GoatError(f"MuAPI error {resp.status_code}: {resp.text[:200]}")


def _failure_reason(data: Any) -> str:
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        err = err.get("message")
    return str(err or (data or {}).get("detail") or (data or {}).get("message") or "unknown error")[:200]


def first_output(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    out = data.get("outputs", data.get("output"))
    if isinstance(out, list) and out:
        return str(out[0])
    if isinstance(out, str) and out:
        return out
    if isinstance(out, dict) and isinstance(out.get("url"), str):
        return out["url"]
    for k in ("video_url", "image_url", "url"):
        if isinstance(data.get(k), str) and data[k]:
            return data[k]
    images = data.get("images")
    return str(images[0]) if isinstance(images, list) and images else None


def upload_image(key: str, jpeg_bytes: bytes, name: str = "photo.jpg") -> str:
    resp = requests.post(f"{API_BASE}/api/v1/upload_file", headers={"x-api-key": key},
                         files={"file": (name, jpeg_bytes, "image/jpeg")}, timeout=120)
    if not resp.ok:
        raise _friendly(resp)
    data = resp.json()
    url = data.get("url") or data.get("file_url") or data.get("output")
    if not isinstance(url, str) or not url:
        raise GoatError("Upload finished without a file URL.")
    return url


def run_model(key: str, model_id: str, request: dict, *, log: Callable[[str], None] = print) -> str:
    """Submit one model call, wait for it, return the result URL."""
    if not MODEL_NAME.match(model_id):
        raise GoatError("Invalid model name.")
    spec = MODELS.get(model_id)
    video = is_video_model(spec) if spec else bool(request.get("isMotion"))
    payload = build_payload(model_id, "video" if video else "image", request)
    headers = {"x-api-key": key, "Content-Type": "application/json"}
    resp = requests.post(f"{API_BASE}/api/v1/{model_id}", headers=headers, json=payload, timeout=60)
    if not resp.ok:
        raise _friendly(resp)
    data = resp.json()
    request_id = data.get("request_id") or data.get("id")
    if not request_id:
        url = first_output(data)
        if url:
            return url
        raise GoatError("MuAPI returned no request ID or output.")

    log(f"[GOAT] {model_id} queued ({request_id})")
    attempts = 900 if video else 60
    for attempt in range(1, attempts + 1):
        time.sleep(POLL_INTERVAL)
        try:
            poll = requests.get(f"{API_BASE}/api/v1/predictions/{request_id}/result", headers=headers, timeout=30)
        except requests.RequestException:
            if attempt < attempts:
                continue
            raise
        if poll.status_code == 400:
            raise GoatError(f"Generation failed: {_failure_reason(poll.json())}")
        if poll.status_code >= 500 and attempt < attempts:
            continue
        if not poll.ok:
            raise _friendly(poll)
        result = poll.json()
        status = str(result.get("status", "")).lower()
        if status in SUCCESS:
            url = first_output(result)
            if not url:
                raise GoatError("Generation finished without an output URL.")
            log(f"[GOAT] {model_id} done")
            return url
        if status in FAILURE:
            raise GoatError(f"Generation failed: {_failure_reason(result)}")
    raise GoatError(f"Generation timed out. Request ID: {request_id}")


def run_skill(key: str, skill_id: str, inputs: dict, photo_url: str | None = None,
              *, log: Callable[[str], None] = print) -> list[str]:
    """Run every step of a Skill; returns each step's result URL (the last is the final piece)."""
    skill = SKILLS.get(skill_id)
    if skill is None:
        raise GoatError("Unknown Skill.")
    if skill["needsPhoto"] and not photo_url:
        raise GoatError(f"{skill['name']} needs a photo.")
    prompts = []
    for step in skill["steps"]:
        rendered = render_prompt(step["prompt"], skill, inputs)
        if "missing" in rendered:
            raise GoatError(f'Fill in "{rendered["missing"]["label"]}".')
        prompts.append(rendered["prompt"])

    outputs: list[str] = []
    for i, step in enumerate(skill["steps"]):
        source = step.get("from")
        image = photo_url if source == "photo" else outputs[i - 1] if source == "previous" else None
        req = {k: v for k, v in {
            "prompt": prompts[i], "aspectRatio": step.get("aspectRatio"), "duration": step.get("duration"),
            "resolution": step.get("resolution"), "imageUrl": image,
        }.items() if v is not None}
        try:
            outputs.append(run_model(key, step["model"], req, log=log))
        except GoatError as err:
            where = f" (step {i + 1} of {len(skill['steps'])})" if len(skill["steps"]) > 1 else ""
            raise GoatError(f"{err}{where}") from err
    return outputs


# ---------------------------------------------------------------- safe downloads

ALLOWED_DOWNLOAD_HOST = re.compile(r"^https://([a-z0-9-]+\.)*muapi\.ai/", re.IGNORECASE)


def download(url: str, max_bytes: int = 512 * 1024 * 1024) -> bytes:
    """Fetch a result from MuAPI's own hosts only (no redirects), with a size cap."""
    if not (ALLOWED_DOWNLOAD_HOST.match(url) or url.startswith(API_BASE + "/")):
        raise GoatError("Only MuAPI result URLs (https://…muapi.ai/…) can be downloaded.")
    with requests.get(url, timeout=120, stream=True, allow_redirects=False) as resp:
        if resp.status_code != 200:
            raise GoatError(f"Download failed ({resp.status_code}).")
        chunks, size = [], 0
        for chunk in resp.iter_content(1 << 20):
            size += len(chunk)
            if size > max_bytes:
                raise GoatError("Download is too large.")
            chunks.append(chunk)
    return b"".join(chunks)
