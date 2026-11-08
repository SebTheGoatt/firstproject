#!/usr/bin/env bash
# GOAT render node: our own image/video engine on hardware we control.
# Installs ComfyUI + the GOAT pack + open models, then starts it for the GOAT apps.
# Safe to re-run: anything already installed is kept.
#
#   ./setup.sh                 Light models (~2.3 GB), start on port 8188
#   ./setup.sh --full          + FLUX.1 Schnell, Qwen-Image-Edit, Wan 2.2 (~66 GB, 24 GB GPU)
#   ./setup.sh --pro           flagship open models: Z-Image, Qwen-Image, Qwen-Edit 2511, Wan 2.2 14B (~143 GB, 24 GB+ GPU)
#   ./setup.sh --dir ~/goat --port 8188 --no-start
#   ./setup.sh --private       only this machine can reach it (used by the cloud setup)
set -euo pipefail

COMFY_REPO="https://github.com/comfyanonymous/ComfyUI"
COMFY_COMMIT="2f89433"   # the version the GOAT workflows were checked against
DIR="$HOME/goat-render-node"; PORT=8188; FULL=""; START=1; LISTEN=0.0.0.0
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --full) FULL="--full"; shift ;;
    --pro) FULL="--pro"; shift ;;
    --no-start) START=0; shift ;;
    --private) LISTEN=127.0.0.1; shift ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done
PACK="$(cd "$(dirname "$0")/../comfyui-goat" && pwd)"
say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }

command -v git >/dev/null || { echo "Please install git first."; exit 1; }
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "Please install Python 3.10+ first."; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "Python 3.10+ is required."; exit 1; }
GPU=0; command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1 && GPU=1
mkdir -p "$DIR"; cd "$DIR"

say "ComfyUI"
if [ ! -d ComfyUI/.git ] && [ ! -e ComfyUI ]; then
  git clone --filter=blob:none "$COMFY_REPO" ComfyUI
  git -C ComfyUI checkout -q "$COMFY_COMMIT"
else
  echo "already here: $DIR/ComfyUI"
fi

say "Python environment"
[ -e venv ] || "$PY" -m venv venv
VPY="$DIR/venv/bin/python"
"$VPY" -m pip install -q --upgrade pip
if ! "$VPY" -c 'import torch' 2>/dev/null; then
  if [ "$GPU" = 1 ]; then "$VPY" -m pip install -q torch torchvision torchaudio
  else "$VPY" -m pip install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu; fi
fi
"$VPY" -m pip install -q -r ComfyUI/requirements.txt

say "GOAT pack"
rm -rf ComfyUI/custom_nodes/comfyui-goat
mkdir -p ComfyUI/custom_nodes/comfyui-goat
cp -r "$PACK"/*.py "$PACK"/*.json "$PACK"/requirements.txt "$PACK"/README.md ComfyUI/custom_nodes/comfyui-goat/
"$VPY" -m pip install -q requests Pillow numpy
if [ "$GPU" = 1 ]; then "$VPY" -m pip install -q onnxruntime-gpu; else "$VPY" -m pip install -q onnxruntime; fi

say "Open models ${FULL:+(full)}"
(cd ComfyUI && "$VPY" custom_nodes/comfyui-goat/download_models.py $FULL)

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"; [ -n "$IP" ] || IP="<this computer's IP>"
say "Ready"
SETUP=Light; [ "$FULL" = "--full" ] && SETUP=Full; [ "$FULL" = "--pro" ] && SETUP=Pro
if [ "$LISTEN" = 127.0.0.1 ]; then
  echo "Private render node on http://127.0.0.1:$PORT ($SETUP models). Only the SEBastina server on this machine can reach it."
else
  echo "In the GOAT CREATIONS app: Settings > My computer > http://$IP:$PORT > $SETUP > Save and test"
  echo "Keep this on your home network (no login). On mobile data, use GOAT Cloud or Tailscale (see the README)."
fi
[ "$START" = 1 ] || { echo "Start later with: cd $DIR/ComfyUI && $VPY main.py --listen $LISTEN --port $PORT"; exit 0; }
EXTRA=(); [ "$GPU" = 1 ] || EXTRA=(--cpu)
cd ComfyUI && exec "$VPY" main.py --listen "$LISTEN" --port "$PORT" --enable-cors-header "*" "${EXTRA[@]}"
