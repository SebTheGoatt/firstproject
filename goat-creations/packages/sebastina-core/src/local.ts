/**
 * "Our own everything": run GOAT on your own ComfyUI with open-weight models,
 * instead of a paid API. No key, no per-image cost; you need a computer with a
 * GPU (or a rented one). The apps and server talk to ComfyUI's HTTP API:
 *
 *   POST /upload/image            photo in (multipart field "image")
 *   POST /prompt                  queue a workflow (API format)
 *   GET  /history/{prompt_id}     wait for it
 *   GET  /view?filename=…         results out
 *
 * Every workflow below uses ComfyUI's built-in nodes (input names checked against
 * ComfyUI's /object_info), except background removal, which uses the GOAT pack's
 * own "GOATRemoveBackgroundLocal" node (BiRefNet, MIT). Models are open weights
 * with licenses that allow commercial use:
 *
 *   light (8 GB GPU, or a CPU slowly): Stable Diffusion 1.5 (CreativeML OpenRAIL-M)
 *   full  (24 GB GPU):                 FLUX.1 Schnell, Qwen-Image-Edit 2509, Wan 2.2 TI2V 5B (all Apache-2.0)
 *   pro   (24 GB+ GPU, ~143 GB):       Z-Image Turbo, Qwen-Image 2512, Qwen-Image-Edit 2511,
 *                                      Wan 2.2 14B text/photo-to-video, each with its 4-step
 *                                      Lightning LoRA (all Apache-2.0). Wired like ComfyUI's
 *                                      official templates for these models.
 *   all:                               Real-ESRGAN x4 (BSD-3), BiRefNet lite (MIT)
 */
import type { ModelSpec, ModelTask, PayloadRequest } from './models.js';

export type LocalProfile = 'light' | 'full' | 'pro';

/** File names ComfyUI looks for (download_models.py in the GOAT ComfyUI pack fetches them). */
export const LOCAL_FILES = {
    sd15: 'v1-5-pruned-emaonly-fp16.safetensors',
    flux: 'flux1-schnell-fp8.safetensors',
    upscaler: 'RealESRGAN_x4.pth',
    birefnet: 'birefnet_lite_fp16.onnx',
    qwenEdit: 'qwen_image_edit_2509_fp8_e4m3fn.safetensors',
    qwenText: 'qwen_2.5_vl_7b_fp8_scaled.safetensors',
    qwenVae: 'qwen_image_vae.safetensors',
    wan: 'wan2.2_ti2v_5B_fp16.safetensors',
    wanText: 'umt5_xxl_fp8_e4m3fn_scaled.safetensors',
    wanVae: 'wan2.2_vae.safetensors',
    // pro
    zImage: 'z_image_turbo_bf16.safetensors',
    zText: 'qwen_3_4b.safetensors',
    zVae: 'ae.safetensors',
    qwenImage: 'qwen_image_2512_fp8_e4m3fn.safetensors',
    qwenImageLightning: 'Qwen-Image-2512-Lightning-4steps-V1.0-fp32.safetensors',
    qwenEdit2511: 'qwen_image_edit_2511_fp8mixed.safetensors',
    qwenEditLightning: 'Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors',
    wan14T2vHigh: 'wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors',
    wan14T2vLow: 'wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors',
    wan14I2vHigh: 'wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors',
    wan14I2vLow: 'wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors',
    wan14T2vLoraHigh: 'wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors',
    wan14T2vLoraLow: 'wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors',
    wan14I2vLoraHigh: 'wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors',
    wan14I2vLoraLow: 'wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors',
    wan21Vae: 'wan_2.1_vae.safetensors',
} as const;

/** Models shown in the apps' pickers when connected to your own computer. */
export const LOCAL_IMAGE_MODELS: readonly ModelSpec[] = [
    { id: 'local-sd15', name: 'Stable Diffusion 1.5', note: 'Light: 8 GB GPU, or CPU (slow)', task: 't2i', size: 'pixels' },
    { id: 'local-flux-schnell', name: 'FLUX.1 Schnell', note: 'Full: 24 GB GPU', task: 't2i', size: 'pixels' },
    { id: 'local-z-image-turbo', name: 'Z-Image Turbo', note: 'Pro: photoreal, 8 steps', task: 't2i', size: 'pixels' },
    { id: 'local-qwen-image', name: 'Qwen-Image 2512', note: 'Pro: posters, logos, text in images', task: 't2i', size: 'pixels' },
];
export const LOCAL_VIDEO_MODELS: readonly ModelSpec[] = [
    { id: 'local-wan22', name: 'Wan 2.2 5B', note: 'Full: video on a 24 GB GPU', task: 't2v', size: 'pixels' },
    { id: 'local-wan22-14b', name: 'Wan 2.2 14B', note: 'Pro: best open video, 4-step', task: 't2v', size: 'pixels' },
];

/** Which local models each setup has installed (pickers show only these). */
export const LOCAL_PROFILE_MODELS: Record<LocalProfile, readonly string[]> = {
    light: ['local-sd15'],
    full: ['local-flux-schnell', 'local-sd15', 'local-wan22'],
    pro: ['local-z-image-turbo', 'local-qwen-image', 'local-wan22-14b'],
};

/** Catalog (hosted) models whose strength is lettering: on Pro they map to Qwen-Image. */
const TEXT_HEAVY = new Set(['gpt-image-1.5', 'gpt-image-2-text-to-image', 'flux-2-pro', 'nano-banana-pro']);

/** What a profile can do; Skills needing more say so instead of failing mid-way. */
export function localSupports(profile: LocalProfile, task: ModelTask): boolean {
    return profile !== 'light' || task === 't2i' || task === 'enhance';
}

const NEGATIVE = 'blurry, low quality, distorted, deformed, watermark, text artifacts, nsfw, nudity';

/** Pixel size for a shape: SD 1.5 works around 512 px, the full models around 1024 px. */
function sizeFor(req: PayloadRequest, base: number, step: number): [number, number] {
    let ratio = 1;
    if (req.aspectRatio) {
        const [w, h] = req.aspectRatio.split(':').map(Number);
        if (w > 0 && h > 0) ratio = w / h;
    } else if (req.width && req.height) {
        ratio = req.width / req.height;
    }
    const area = base * base;
    const round = (v: number) => Math.max(step * 4, Math.round(v / step) * step);
    return [round(Math.sqrt(area * ratio)), round(Math.sqrt(area / ratio))];
}

const seed = () => Math.floor(Math.random() * 2 ** 32);
type Workflow = Record<string, { class_type: string; inputs: Record<string, unknown> }>;

/** Text → image (SD 1.5 or FLUX.1 Schnell, one checkpoint file each). */
export function t2iWorkflow(req: PayloadRequest, useFlux: boolean): Workflow {
    const [width, height] = useFlux ? sizeFor(req, 1024, 64) : sizeFor(req, 512, 64);
    return {
        '1': { class_type: 'CheckpointLoaderSimple', inputs: { ckpt_name: useFlux ? LOCAL_FILES.flux : LOCAL_FILES.sd15 } },
        '2': { class_type: 'CLIPTextEncode', inputs: { text: req.prompt, clip: ['1', 1] } },
        '3': { class_type: 'CLIPTextEncode', inputs: { text: useFlux ? '' : NEGATIVE, clip: ['1', 1] } },
        '4': { class_type: 'EmptyLatentImage', inputs: { width, height, batch_size: 1 } },
        '5': {
            class_type: 'KSampler',
            inputs: useFlux
                ? { model: ['1', 0], seed: seed(), steps: 4, cfg: 1, sampler_name: 'euler', scheduler: 'simple', positive: ['2', 0], negative: ['3', 0], latent_image: ['4', 0], denoise: 1 }
                : { model: ['1', 0], seed: seed(), steps: 20, cfg: 7, sampler_name: 'euler_ancestral', scheduler: 'normal', positive: ['2', 0], negative: ['3', 0], latent_image: ['4', 0], denoise: 1 },
        },
        '6': { class_type: 'VAEDecode', inputs: { samples: ['5', 0], vae: ['1', 2] } },
        '7': { class_type: 'SaveImage', inputs: { images: ['6', 0], filename_prefix: 'goat' } },
    };
}

/** Photo → edited photo with words, keeping the subject (Qwen-Image-Edit; SEBastina scenes too). */
export function editWorkflow(req: PayloadRequest, image: string): Workflow {
    const [width, height] = sizeFor(req, 1024, 64);
    return {
        '1': { class_type: 'UNETLoader', inputs: { unet_name: LOCAL_FILES.qwenEdit, weight_dtype: 'default' } },
        '2': { class_type: 'CLIPLoader', inputs: { clip_name: LOCAL_FILES.qwenText, type: 'qwen_image' } },
        '3': { class_type: 'VAELoader', inputs: { vae_name: LOCAL_FILES.qwenVae } },
        '4': { class_type: 'LoadImage', inputs: { image } },
        '5': { class_type: 'TextEncodeQwenImageEdit', inputs: { clip: ['2', 0], prompt: req.prompt, vae: ['3', 0], image: ['4', 0] } },
        '6': { class_type: 'TextEncodeQwenImageEdit', inputs: { clip: ['2', 0], prompt: '', vae: ['3', 0], image: ['4', 0] } },
        '7': { class_type: 'ModelSamplingAuraFlow', inputs: { model: ['1', 0], shift: 3 } },
        '8': { class_type: 'EmptySD3LatentImage', inputs: { width, height, batch_size: 1 } },
        '9': { class_type: 'KSampler', inputs: { model: ['7', 0], seed: seed(), steps: 20, cfg: 2.5, sampler_name: 'euler', scheduler: 'simple', positive: ['5', 0], negative: ['6', 0], latent_image: ['8', 0], denoise: 1 } },
        '10': { class_type: 'VAEDecode', inputs: { samples: ['9', 0], vae: ['3', 0] } },
        '11': { class_type: 'SaveImage', inputs: { images: ['10', 0], filename_prefix: 'goat_edit' } },
    };
}

/** Text (or photo) → video with Wan 2.2 TI2V 5B, 24 fps, saved as WebM. */
export function videoWorkflow(req: PayloadRequest, startImage?: string): Workflow {
    const [width, height] = sizeFor({ aspectRatio: req.aspectRatio ?? '16:9', prompt: '' }, 960, 32);
    const seconds = Math.min(5, Math.max(2, Math.round(req.duration ?? 5)));
    const wf: Workflow = {
        '1': { class_type: 'UNETLoader', inputs: { unet_name: LOCAL_FILES.wan, weight_dtype: 'default' } },
        '2': { class_type: 'CLIPLoader', inputs: { clip_name: LOCAL_FILES.wanText, type: 'wan' } },
        '3': { class_type: 'VAELoader', inputs: { vae_name: LOCAL_FILES.wanVae } },
        '4': { class_type: 'CLIPTextEncode', inputs: { text: req.prompt, clip: ['2', 0] } },
        '5': { class_type: 'CLIPTextEncode', inputs: { text: NEGATIVE, clip: ['2', 0] } },
        '6': { class_type: 'ModelSamplingSD3', inputs: { model: ['1', 0], shift: 8 } },
        '7': { class_type: 'Wan22ImageToVideoLatent', inputs: { vae: ['3', 0], width, height, length: seconds * 24 + 1, batch_size: 1 } },
        '8': { class_type: 'KSampler', inputs: { model: ['6', 0], seed: seed(), steps: 20, cfg: 5, sampler_name: 'uni_pc', scheduler: 'simple', positive: ['4', 0], negative: ['5', 0], latent_image: ['7', 0], denoise: 1 } },
        '9': { class_type: 'VAEDecode', inputs: { samples: ['8', 0], vae: ['3', 0] } },
        '10': { class_type: 'SaveWEBM', inputs: { images: ['9', 0], filename_prefix: 'goat_video', codec: 'vp9', fps: 24, crf: 32 } },
    };
    if (startImage) {
        wf['11'] = { class_type: 'LoadImage', inputs: { image: startImage } };
        wf['7'].inputs.start_image = ['11', 0];
    }
    return wf;
}

/** Photo → 4x bigger photo (Real-ESRGAN). */
export function upscaleWorkflow(image: string): Workflow {
    return {
        '1': { class_type: 'LoadImage', inputs: { image } },
        '2': { class_type: 'UpscaleModelLoader', inputs: { model_name: LOCAL_FILES.upscaler } },
        '3': { class_type: 'ImageUpscaleWithModel', inputs: { upscale_model: ['2', 0], image: ['1', 0] } },
        '4': { class_type: 'SaveImage', inputs: { images: ['3', 0], filename_prefix: 'goat_upscale' } },
    };
}

/** Photo → cut-out on transparent background (GOAT pack node, BiRefNet). */
export function removeBackgroundWorkflow(image: string): Workflow {
    return {
        '1': { class_type: 'LoadImage', inputs: { image } },
        '2': { class_type: 'GOATRemoveBackgroundLocal', inputs: { image: ['1', 0] } },
        '3': { class_type: 'SaveImage', inputs: { images: ['2', 0], filename_prefix: 'goat_cutout' } },
    };
}


// ------------------------------------------------------------------ pro (official-template wiring)

/** Text -> image with Z-Image Turbo: 8 steps, cfg 1, res_multistep (ComfyUI template). */
export function zImageWorkflow(req: PayloadRequest): Workflow {
    const [width, height] = sizeFor(req, 1024, 64);
    return {
        '1': { class_type: 'UNETLoader', inputs: { unet_name: LOCAL_FILES.zImage, weight_dtype: 'default' } },
        '2': { class_type: 'CLIPLoader', inputs: { clip_name: LOCAL_FILES.zText, type: 'lumina2' } },
        '3': { class_type: 'VAELoader', inputs: { vae_name: LOCAL_FILES.zVae } },
        '4': { class_type: 'ModelSamplingAuraFlow', inputs: { model: ['1', 0], shift: 3 } },
        '5': { class_type: 'CLIPTextEncode', inputs: { text: req.prompt, clip: ['2', 0] } },
        '6': { class_type: 'ConditioningZeroOut', inputs: { conditioning: ['5', 0] } },
        '7': { class_type: 'EmptySD3LatentImage', inputs: { width, height, batch_size: 1 } },
        '8': { class_type: 'KSampler', inputs: { model: ['4', 0], seed: seed(), steps: 8, cfg: 1, sampler_name: 'res_multistep', scheduler: 'simple', positive: ['5', 0], negative: ['6', 0], latent_image: ['7', 0], denoise: 1 } },
        '9': { class_type: 'VAEDecode', inputs: { samples: ['8', 0], vae: ['3', 0] } },
        '10': { class_type: 'SaveImage', inputs: { images: ['9', 0], filename_prefix: 'goat_zimage' } },
    };
}

/** Text -> image with Qwen-Image 2512 + its 4-step Lightning LoRA: best lettering. */
export function qwenImageWorkflow(req: PayloadRequest): Workflow {
    const [width, height] = sizeFor(req, 1328, 16);
    return {
        '1': { class_type: 'UNETLoader', inputs: { unet_name: LOCAL_FILES.qwenImage, weight_dtype: 'default' } },
        '2': { class_type: 'LoraLoaderModelOnly', inputs: { model: ['1', 0], lora_name: LOCAL_FILES.qwenImageLightning, strength_model: 1 } },
        '3': { class_type: 'ModelSamplingAuraFlow', inputs: { model: ['2', 0], shift: 3.1 } },
        '4': { class_type: 'CLIPLoader', inputs: { clip_name: LOCAL_FILES.qwenText, type: 'qwen_image' } },
        '5': { class_type: 'VAELoader', inputs: { vae_name: LOCAL_FILES.qwenVae } },
        '6': { class_type: 'CLIPTextEncode', inputs: { text: req.prompt, clip: ['4', 0] } },
        '7': { class_type: 'CLIPTextEncode', inputs: { text: NEGATIVE, clip: ['4', 0] } },
        '8': { class_type: 'EmptySD3LatentImage', inputs: { width, height, batch_size: 1 } },
        '9': { class_type: 'KSampler', inputs: { model: ['3', 0], seed: seed(), steps: 4, cfg: 1, sampler_name: 'euler', scheduler: 'simple', positive: ['6', 0], negative: ['7', 0], latent_image: ['8', 0], denoise: 1 } },
        '10': { class_type: 'VAEDecode', inputs: { samples: ['9', 0], vae: ['5', 0] } },
        '11': { class_type: 'SaveImage', inputs: { images: ['10', 0], filename_prefix: 'goat_qwenimage' } },
    };
}

/** Photo -> edited photo with Qwen-Image-Edit 2511 + 4-step Lightning (SEBastina scenes too). */
export function qwenEdit2511Workflow(req: PayloadRequest, image: string): Workflow {
    return {
        '1': { class_type: 'UNETLoader', inputs: { unet_name: LOCAL_FILES.qwenEdit2511, weight_dtype: 'default' } },
        '2': { class_type: 'ModelSamplingAuraFlow', inputs: { model: ['1', 0], shift: 3.1 } },
        '3': { class_type: 'CFGNorm', inputs: { model: ['2', 0], strength: 1 } },
        '4': { class_type: 'LoraLoaderModelOnly', inputs: { model: ['3', 0], lora_name: LOCAL_FILES.qwenEditLightning, strength_model: 1 } },
        '5': { class_type: 'CLIPLoader', inputs: { clip_name: LOCAL_FILES.qwenText, type: 'qwen_image' } },
        '6': { class_type: 'VAELoader', inputs: { vae_name: LOCAL_FILES.qwenVae } },
        '7': { class_type: 'LoadImage', inputs: { image } },
        '8': { class_type: 'FluxKontextImageScale', inputs: { image: ['7', 0] } },
        '9': { class_type: 'TextEncodeQwenImageEditPlus', inputs: { clip: ['5', 0], prompt: req.prompt, vae: ['6', 0], image1: ['8', 0] } },
        '10': { class_type: 'TextEncodeQwenImageEditPlus', inputs: { clip: ['5', 0], prompt: '', vae: ['6', 0], image1: ['8', 0] } },
        '11': { class_type: 'FluxKontextMultiReferenceLatentMethod', inputs: { conditioning: ['9', 0], reference_latents_method: 'index_timestep_zero' } },
        '12': { class_type: 'FluxKontextMultiReferenceLatentMethod', inputs: { conditioning: ['10', 0], reference_latents_method: 'index_timestep_zero' } },
        '13': { class_type: 'VAEEncode', inputs: { pixels: ['8', 0], vae: ['6', 0] } },
        '14': { class_type: 'KSampler', inputs: { model: ['4', 0], seed: seed(), steps: 4, cfg: 1, sampler_name: 'euler', scheduler: 'simple', positive: ['11', 0], negative: ['12', 0], latent_image: ['13', 0], denoise: 1 } },
        '15': { class_type: 'VAEDecode', inputs: { samples: ['14', 0], vae: ['6', 0] } },
        '16': { class_type: 'SaveImage', inputs: { images: ['15', 0], filename_prefix: 'goat_edit' } },
    };
}

/**
 * Text or photo -> video with Wan 2.2 14B: high-noise expert for steps 0-2, low-noise
 * expert for 2-4, each with its 4-step Lightning LoRA; 16 fps (ComfyUI template).
 */
export function wan14bWorkflow(req: PayloadRequest, startImage?: string): Workflow {
    const [width, height] = sizeFor({ aspectRatio: req.aspectRatio ?? '16:9', prompt: '' }, 640, 16);
    const seconds = Math.min(5, Math.max(2, Math.round(req.duration ?? 5)));
    const i2v = !!startImage;
    const wf: Workflow = {
        '1': { class_type: 'UNETLoader', inputs: { unet_name: i2v ? LOCAL_FILES.wan14I2vHigh : LOCAL_FILES.wan14T2vHigh, weight_dtype: 'default' } },
        '2': { class_type: 'UNETLoader', inputs: { unet_name: i2v ? LOCAL_FILES.wan14I2vLow : LOCAL_FILES.wan14T2vLow, weight_dtype: 'default' } },
        '3': { class_type: 'LoraLoaderModelOnly', inputs: { model: ['1', 0], lora_name: i2v ? LOCAL_FILES.wan14I2vLoraHigh : LOCAL_FILES.wan14T2vLoraHigh, strength_model: 1 } },
        '4': { class_type: 'LoraLoaderModelOnly', inputs: { model: ['2', 0], lora_name: i2v ? LOCAL_FILES.wan14I2vLoraLow : LOCAL_FILES.wan14T2vLoraLow, strength_model: 1 } },
        '5': { class_type: 'ModelSamplingSD3', inputs: { model: ['3', 0], shift: 5 } },
        '6': { class_type: 'ModelSamplingSD3', inputs: { model: ['4', 0], shift: 5 } },
        '7': { class_type: 'CLIPLoader', inputs: { clip_name: LOCAL_FILES.wanText, type: 'wan' } },
        '8': { class_type: 'VAELoader', inputs: { vae_name: LOCAL_FILES.wan21Vae } },
        '9': { class_type: 'CLIPTextEncode', inputs: { text: req.prompt, clip: ['7', 0] } },
        '10': { class_type: 'CLIPTextEncode', inputs: { text: NEGATIVE, clip: ['7', 0] } },
    };
    const length = seconds * 16 + 1;
    let positive: [string, number] = ['9', 0];
    let negative: [string, number] = ['10', 0];
    let latent: [string, number];
    if (startImage) {
        wf['11'] = { class_type: 'LoadImage', inputs: { image: startImage } };
        wf['12'] = { class_type: 'WanImageToVideo', inputs: { positive, negative, vae: ['8', 0], width, height, length, batch_size: 1, start_image: ['11', 0] } };
        positive = ['12', 0]; negative = ['12', 1]; latent = ['12', 2];
    } else {
        wf['12'] = { class_type: 'EmptyHunyuanLatentVideo', inputs: { width, height, length, batch_size: 1 } };
        latent = ['12', 0];
    }
    wf['13'] = { class_type: 'KSamplerAdvanced', inputs: { model: ['5', 0], add_noise: 'enable', noise_seed: seed(), steps: 4, cfg: 1, sampler_name: 'euler', scheduler: 'simple', positive, negative, latent_image: latent, start_at_step: 0, end_at_step: 2, return_with_leftover_noise: 'enable' } };
    wf['14'] = { class_type: 'KSamplerAdvanced', inputs: { model: ['6', 0], add_noise: 'disable', noise_seed: 0, steps: 4, cfg: 1, sampler_name: 'euler', scheduler: 'simple', positive, negative, latent_image: ['13', 0], start_at_step: 2, end_at_step: 4, return_with_leftover_noise: 'disable' } };
    wf['15'] = { class_type: 'VAEDecode', inputs: { samples: ['14', 0], vae: ['8', 0] } };
    wf['16'] = { class_type: 'SaveWEBM', inputs: { images: ['15', 0], filename_prefix: 'goat_video', codec: 'vp9', fps: 16, crf: 32 } };
    return wf;
}

/** A ComfyUI file reference as a /view URL, and back to LoadImage's "name [type]" form. */
export function viewUrl(base: string, file: { filename: string; subfolder?: string; type?: string }): string {
    const q = new URLSearchParams({ filename: file.filename, subfolder: file.subfolder ?? '', type: file.type ?? 'output' });
    return `${base}/view?${q.toString()}`;
}

export function loadImageRef(url: string, base: string): string | null {
    if (!url.startsWith(`${base}/view?`)) return null;
    const q = new URL(url).searchParams;
    const filename = q.get('filename') ?? '';
    const subfolder = q.get('subfolder') ?? '';
    const type = q.get('type') ?? 'input';
    if (!filename || /[\\/]|\.\./.test(filename) || /\.\./.test(subfolder) || !['input', 'output', 'temp'].includes(type)) return null;
    return `${subfolder ? `${subfolder}/` : ''}${filename} [${type}]`;
}

/** Pick the workflow for one catalog step on a given profile. Throws a readable error. */
export function workflowFor(
    task: ModelTask,
    modelId: string,
    req: PayloadRequest,
    profile: LocalProfile,
    image: string | undefined,
): Workflow {
    if (!localSupports(profile, task)) {
        const what = task === 'i2i' ? 'Photo edits and SEBastina scenes need' : 'Video needs';
        throw new Error(`${what} the Full or Pro local setup (Qwen-Image-Edit / Wan 2.2 on a 24 GB GPU).`);
    }
    const needImage = () => {
        if (!image) throw new Error('This step needs a photo.');
        return image;
    };
    if (profile === 'pro') {
        switch (task) {
            case 't2i':
                if (modelId === 'local-sd15' || modelId === 'local-flux-schnell') break;
                return modelId === 'local-qwen-image' || TEXT_HEAVY.has(modelId) ? qwenImageWorkflow(req) : zImageWorkflow(req);
            case 'i2i':
                return qwenEdit2511Workflow(req, needImage());
            case 't2v':
                return wan14bWorkflow(req);
            case 'i2v':
                return wan14bWorkflow(req, needImage());
            default:
                break;
        }
    }
    switch (task) {
        case 't2i':
            return t2iWorkflow(req, modelId === 'local-flux-schnell' || (modelId !== 'local-sd15' && profile !== 'light'));
        case 'i2i':
            return editWorkflow(req, needImage());
        case 't2v':
            return videoWorkflow(req);
        case 'i2v':
            return videoWorkflow(req, needImage());
        case 'enhance':
            return modelId === 'ai-background-remover' ? removeBackgroundWorkflow(needImage()) : upscaleWorkflow(needImage());
    }
}
