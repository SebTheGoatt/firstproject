"""Download the open models GOAT CREATIONS uses on your own computer (no API, no key).

    python custom_nodes/comfyui-goat/download_models.py              # light: ~2.3 GB
    python custom_nodes/comfyui-goat/download_models.py --full       # + FLUX, Qwen edit, Wan video: ~66 GB
    python custom_nodes/comfyui-goat/download_models.py --pro        # flagship open models: ~143 GB, 24 GB+ GPU

Run it from your ComfyUI folder. Everything comes from Hugging Face; licenses allow
commercial use: SD 1.5 (CreativeML OpenRAIL-M: follow its use restrictions),
Real-ESRGAN (BSD-3), BiRefNet (MIT), FLUX.1 Schnell / Qwen-Image-Edit / Wan 2.2 (Apache-2.0),
Pro: Z-Image Turbo, Qwen-Image 2512, Qwen-Image-Edit 2511, Wan 2.2 14B and their Lightning
LoRAs (Apache-2.0). Pro file names and sources follow ComfyUI's official workflow templates.
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

W22 = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"
PRO = [
    ("diffusion_models", "z_image_turbo_bf16.safetensors", "Comfy-Org/z_image_turbo", "split_files/diffusion_models/z_image_turbo_bf16.safetensors"),
    ("text_encoders", "qwen_3_4b.safetensors", "Comfy-Org/z_image_turbo", "split_files/text_encoders/qwen_3_4b.safetensors"),
    ("vae", "ae.safetensors", "Comfy-Org/z_image_turbo", "split_files/vae/ae.safetensors"),
    ("diffusion_models", "qwen_image_2512_fp8_e4m3fn.safetensors", "Comfy-Org/Qwen-Image_ComfyUI", "split_files/diffusion_models/qwen_image_2512_fp8_e4m3fn.safetensors"),
    ("loras", "Qwen-Image-2512-Lightning-4steps-V1.0-fp32.safetensors", "lightx2v/Qwen-Image-2512-Lightning", "Qwen-Image-2512-Lightning-4steps-V1.0-fp32.safetensors"),
    ("diffusion_models", "qwen_image_edit_2511_fp8mixed.safetensors", "Comfy-Org/Qwen-Image-Edit_ComfyUI", "split_files/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors"),
    ("loras", "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors", "lightx2v/Qwen-Image-Edit-2511-Lightning", "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"),
    ("text_encoders", "qwen_2.5_vl_7b_fp8_scaled.safetensors", "Comfy-Org/Qwen-Image_ComfyUI", "split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"),
    ("vae", "qwen_image_vae.safetensors", "Comfy-Org/Qwen-Image_ComfyUI", "split_files/vae/qwen_image_vae.safetensors"),
    ("text_encoders", "umt5_xxl_fp8_e4m3fn_scaled.safetensors", W22, "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
    ("vae", "wan_2.1_vae.safetensors", W22, "split_files/vae/wan_2.1_vae.safetensors"),
] + [
    (folder, name, W22, f"split_files/{folder}/{name}")
    for folder, name in [
        ("diffusion_models", "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors"),
        ("diffusion_models", "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors"),
        ("diffusion_models", "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"),
        ("diffusion_models", "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"),
        ("loras", "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors"),
        ("loras", "wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors"),
        ("loras", "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors"),
        ("loras", "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors"),
    ]
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
    ap.add_argument("--pro", action="store_true", help="flagship open models: Z-Image Turbo, Qwen-Image 2512, Qwen-Image-Edit 2511, Wan 2.2 14B (~143 GB, 24 GB+ GPU)")
    ap.add_argument("--models-dir", default=os.path.join(os.getcwd(), "models"), help="ComfyUI models folder (default: ./models)")
    args = ap.parse_args()
    if not os.path.isdir(args.models_dir):
        sys.exit(f"{args.models_dir} not found: run this from your ComfyUI folder or pass --models-dir")
    for folder, name, repo, path in LIGHT + (FULL if args.full else []) + (PRO if args.pro else []):
        dest_dir = os.path.join(args.models_dir, folder)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, name)
        if os.path.exists(dest):
            print(f"ok    {folder}/{name}")
            continue
        print(f"get   {folder}/{name}  ({repo})")
        fetch(f"{HF}/{repo}/resolve/main/{path}", dest)
    setup = "Pro" if args.pro else "Full" if args.full else "Light"
    print(f"Done. Restart ComfyUI, then in the GOAT CREATIONS app pick \"My computer\" and \"{setup}\".")


if __name__ == "__main__":
    main()
