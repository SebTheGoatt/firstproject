# GOAT CREATIONS for ComfyUI

GOAT CREATIONS' Skills, photo tools and model catalog as ComfyUI nodes, running on
[MuAPI](https://muapi.ai) (one key, no GPU needed).

## Nodes (category 🐐 GOAT CREATIONS)

| Node | What it does |
| --- | --- |
| **GOAT Image** | Text to image with 8 models (FLUX.1 Dev/Schnell, HiDream, Nano Banana / Pro, FLUX.2 Pro, GPT Image 1.5 / 2) |
| **GOAT Video** | Text to video with 5 models (Seedance Lite / 1.5 Pro, Kling 2.1 Master, Veo 3 Fast, Wan 2.2) |
| **GOAT Skill · YouTube Thumbnail** | `subject` + `headline` → bold 16:9 thumbnail |
| **GOAT Skill · Instagram Post** | `subject` + `mood` → square post |
| **GOAT Skill · Ad Creative** | `product` + `headline` → 4:5 ad |
| **GOAT Skill · Logo** | `name` + `idea` → flat logo on white |
| **GOAT Skill · Blog Header** | `topic` → wide editorial image |
| **GOAT Skill · Drone Shot Video** | `place` → 5 s aerial video |
| **GOAT Skill · Action Figure** | photo + `title` → boxed collectible figure |
| **GOAT Skill · Product Ad Video** | product photo → re-staged shot → 5 s commercial (2 steps) |
| **GOAT Photo · Animate Photo** | photo + `motion` → 5 s video |
| **GOAT Photo · Edit with Words** | photo + `change` → edited photo |
| **GOAT Photo · Upscale** | photo → bigger, sharper photo |
| **GOAT Photo · Remove Background** | photo → cut-out subject |
| **GOAT Save Video** | downloads a `video_url` into ComfyUI's output folder |

Image nodes output an `IMAGE` (wire it to Save Image / Preview Image) and the URL;
video nodes output `video_url` (wire it to GOAT Save Video).

## Install

```bash
cd ComfyUI/custom_nodes
cp -r /path/to/goat-creations/apps/comfyui-goat comfyui-goat   # or git clone the repo and copy this folder
pip install -r comfyui-goat/requirements.txt
```

Restart ComfyUI. Set your key once with `export MUAPI_API_KEY=...` before starting
ComfyUI, or paste it into a node's `api_key` field (it is saved inside the workflow
file, so don't share workflows with the key filled in).

## Privacy and safety

- Photos are re-encoded as JPEG before upload, which drops hidden metadata such as GPS location.
- Results are only downloaded from MuAPI's own hosts, without following redirects.
- GOAT Save Video writes only inside ComfyUI's output folder, with a plain file-name prefix.

## Development

The catalog (`goat_catalog.json`) is generated from `packages/sebastina-core`, the same
code the GOAT CREATIONS desktop and phone apps use. Don't edit it by hand:

```bash
cd packages/sebastina-core && npm run catalog     # regenerate after changing models or Skills
cd apps/comfyui-goat && python3 -m unittest discover tests
```

`tests/golden_cases.json` holds every request and prompt the TypeScript engine builds;
`tests/test_parity.py` proves this Python port builds exactly the same ones.

Inspired by MuAPI's own ComfyUI pack ([SamurAIGPT/muapi-comfyui](https://github.com/SamurAIGPT/muapi-comfyui), MIT).
License: MIT OR Apache-2.0.
