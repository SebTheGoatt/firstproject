"""Download the open models GOAT CREATIONS uses on your own computer (no API, no key).

    python custom_nodes/comfyui-goat/download_models.py              # light: ~2.3 GB
    python custom_nodes/comfyui-goat/download_models.py --full       # + FLUX, Qwen edit, Wan video: ~66 GB

Run it from your ComfyUI folder. Everything comes from Hugging Face; licenses allow
commercial use: SD 1.5 (CreativeML OpenRAIL-M: follow its use restrictions),
Real-ESRGAN (BSD-3), BiRefNet (MIT), FLUX.1 Schnell / Qwen-Image-Edit / Wan 2.2 (Apache-2.0).
"""
import argparse
import os
import sys
import urllib.request

HF = "https://huggingface.co"
LIGHT = [
    ("checkpoints", "v1-5-pruned-emaonly-fp16.safetensors", "Comfy-Org/stable-diffusion-v1-5-archive", "v1-5-pruned-emaonly-fp16.safetensors"),
    ("upscale_models", "RealESRGAN_x4.pth", "ai-forever/Real-ESRGAN", "RealESRGAN_x4.pth"),
    ("goat", "birefnet_lite_fp16.onnx", "onnx-community/BiRefNet_lite-ONNX", "onnx/model_fp16.onnx"),
]
FULL = [
    ("checkpoints", "flux1-schnell-fp8.safetensors", "Comfy-Org/flux1-schnell", "flux1-schnell-fp8.safetensors"),
    ("diffusion_models", "qwen_image_edit_2509_fp8_e4m3fn.safetensors", "Comfy-Org/Qwen-Image-Edit_ComfyUI", "split_files/diffusion_models/qwen_image_edit_2509_fp8_e4m3fn.safetensors"),
    ("text_encoders", "qwen_2.5_vl_7b_fp8_scaled.safetensors", "Comfy-Org/Qwen-Image_ComfyUI", "split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"),
    ("vae", "qwen_image_vae.safetensors", "Comfy-Org/Qwen-Image_ComfyUI", "split_files/vae/qwen_image_vae.safetensors"),
    ("diffusion_models", "wan2.2_ti2v_5B_fp16.safetensors", "Comfy-Org/Wan_2.2_ComfyUI_Repackaged", "split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors"),
    ("text_encoders", "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "Comfy-Org/Wan_2.2_ComfyUI_Repackaged", "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
    ("vae", "wan2.2_vae.safetensors", "Comfy-Org/Wan_2.2_ComfyUI_Repackaged", "split_files/vae/wan2.2_vae.safetensors"),
]


def fetch(url, dest):
    tmp = dest + ".part"
    with urllib.request.urlopen(url) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(8 << 20):
            out.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / 1e9:5.2f} / {total / 1e9:.2f} GB", end="", flush=True)
    os.replace(tmp, dest)
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true", help="also download FLUX.1 Schnell, Qwen-Image-Edit and Wan 2.2 (~66 GB, 24 GB GPU)")
    ap.add_argument("--models-dir", default=os.path.join(os.getcwd(), "models"), help="ComfyUI models folder (default: ./models)")
    args = ap.parse_args()
    if not os.path.isdir(args.models_dir):
        sys.exit(f"{args.models_dir} not found: run this from your ComfyUI folder or pass --models-dir")
    for folder, name, repo, path in LIGHT + (FULL if args.full else []):
        dest_dir = os.path.join(args.models_dir, folder)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, name)
        if os.path.exists(dest):
            print(f"ok    {folder}/{name}")
            continue
        print(f"get   {folder}/{name}  ({repo})")
        fetch(f"{HF}/{repo}/resolve/main/{path}", dest)
    print("Done. Restart ComfyUI, then pick \"My computer\" in the GOAT CREATIONS app.")


if __name__ == "__main__":
    main()
