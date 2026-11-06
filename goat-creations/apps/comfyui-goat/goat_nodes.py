"""GOAT CREATIONS nodes for ComfyUI.

- GOAT Image / GOAT Video: generate from text with any catalog model.
- One node per GOAT Skill and photo tool, built from the shared catalog, with the
  Skill's own fields as inputs (and an IMAGE input when it starts from a photo).
- GOAT Save Video: download a video result into ComfyUI's output folder.
"""
from __future__ import annotations

import io
import os
import re

try:  # loaded by ComfyUI as a package
    from . import goat_core as core
except ImportError:  # imported directly (tests)
    import goat_core as core

CATEGORY = "🐐 GOAT CREATIONS"
ASPECTS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "4:5", "5:4", "21:9"]


# ---------------------------------------------------------------- image <-> tensor

def tensor_to_jpeg(image) -> bytes:
    """First image of a ComfyUI IMAGE batch as JPEG bytes. Re-encoding drops all metadata (GPS etc.)."""
    import numpy as np
    from PIL import Image

    frame = image[0] if getattr(image, "dim", lambda: 3)() == 4 else image
    arr = (frame.cpu().numpy().clip(0, 1) * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def url_to_tensor(url: str):
    import numpy as np
    import torch
    from PIL import Image

    img = Image.open(io.BytesIO(core.download(url))).convert("RGB")
    return torch.from_numpy(np.asarray(img).astype(np.float32) / 255.0)[None, ...]


def _key_input():
    return ("STRING", {"default": "", "multiline": False, "tooltip": "MuAPI key. Leave empty to use the MUAPI_API_KEY environment variable."})


def _run(fn):
    try:
        return fn()
    except core.GoatError as err:
        raise RuntimeError(str(err)) from err


# ---------------------------------------------------------------- generate nodes

class GOATImage:
    @classmethod
    def INPUT_TYPES(cls):
        models = core.models_for("t2i")
        return {
            "required": {
                "model": (models, {"default": "flux-dev-image"}),
                "prompt": ("STRING", {"multiline": True, "default": "A majestic goat on a neon mountain, cinematic"}),
                "aspect_ratio": (ASPECTS, {"default": "1:1"}),
            },
            "optional": {"api_key": _key_input()},
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "image_url")
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, model, prompt, aspect_ratio, api_key=""):
        def go():
            url = core.run_model(core.resolve_key(api_key), model, {"prompt": prompt, "aspectRatio": aspect_ratio})
            return (url_to_tensor(url), url)
        return _run(go)


class GOATVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": (core.models_for("t2v"), {"default": "seedance-lite-t2v"}),
                "prompt": ("STRING", {"multiline": True, "default": "Cinematic drone shot over a misty valley at dawn"}),
                "aspect_ratio": (["16:9", "9:16", "1:1", "4:3", "3:4"], {"default": "16:9"}),
                "duration": ("INT", {"default": 5, "min": 3, "max": 12, "step": 1}),
            },
            "optional": {"api_key": _key_input()},
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_url",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, model, prompt, aspect_ratio, duration, api_key=""):
        req = {"prompt": prompt, "aspectRatio": aspect_ratio, "duration": duration}
        return _run(lambda: (core.run_model(core.resolve_key(api_key), model, req),))


# ---------------------------------------------------------------- one node per Skill

def _skill_node(skill: dict):
    output = core.skill_output(skill)
    required = {
        f["id"]: ("STRING", {"default": "", "multiline": False, "placeholder": f["placeholder"],
                             "tooltip": f["label"] + (" (optional)" if f["fallback"] else "")})
        for f in skill["fields"]
    }
    if skill["needsPhoto"]:
        required = {"image": ("IMAGE",), **required}

    def input_types(cls):
        return {"required": dict(required), "optional": {"api_key": _key_input()}}

    def run(self, api_key="", image=None, **fields):
        def go():
            key = core.resolve_key(api_key)
            photo_url = core.upload_image(key, tensor_to_jpeg(image)) if skill["needsPhoto"] else None
            urls = core.run_skill(key, skill["id"], {k: str(v) for k, v in fields.items()}, photo_url)
            final = urls[-1]
            return (url_to_tensor(final), final) if output == "image" else (final,)
        return _run(go)

    label = "Photo" if skill["category"] == "photo" else "Skill"
    return type(
        f"GOAT{label}_{re.sub(r'[^A-Za-z0-9]', '_', skill['id'])}",
        (),
        {
            "INPUT_TYPES": classmethod(input_types),
            "RETURN_TYPES": ("IMAGE", "STRING") if output == "image" else ("STRING",),
            "RETURN_NAMES": ("image", "image_url") if output == "image" else ("video_url",),
            "FUNCTION": "run",
            "CATEGORY": f"{CATEGORY}/{'Photo tools' if skill['category'] == 'photo' else 'Skills'}",
            "DESCRIPTION": skill["description"],
            "run": run,
        },
    ), f"GOAT {label} · {skill['name']}"


# ---------------------------------------------------------------- save video

class GOATSaveVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "video_url": ("STRING", {"forceInput": True}),
            "filename_prefix": ("STRING", {"default": "goat"}),
        }}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("path",)
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = CATEGORY

    def save(self, video_url, filename_prefix="goat"):
        import folder_paths

        prefix = filename_prefix.strip() or "goat"
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", prefix) or prefix.startswith("."):
            raise RuntimeError("filename_prefix: letters, numbers, dot, dash or underscore only.")
        out_dir = os.path.realpath(folder_paths.get_output_directory())
        data = _run(lambda: core.download(video_url))
        n = 1
        while os.path.exists(os.path.join(out_dir, f"{prefix}_{n:05d}.mp4")):
            n += 1
        path = os.path.join(out_dir, f"{prefix}_{n:05d}.mp4")
        with open(path, "wb") as fh:
            fh.write(data)
        return {"ui": {"text": [os.path.basename(path)]}, "result": (path,)}


# ---------------------------------------------------------------- registration

NODE_CLASS_MAPPINGS = {"GOATImage": GOATImage, "GOATVideo": GOATVideo, "GOATSaveVideo": GOATSaveVideo}
NODE_DISPLAY_NAME_MAPPINGS = {"GOATImage": "GOAT Image", "GOATVideo": "GOAT Video", "GOATSaveVideo": "GOAT Save Video"}
for _skill in core.CATALOG["skills"]:
    _cls, _title = _skill_node(_skill)
    NODE_CLASS_MAPPINGS[_cls.__name__] = _cls
    NODE_DISPLAY_NAME_MAPPINGS[_cls.__name__] = _title
