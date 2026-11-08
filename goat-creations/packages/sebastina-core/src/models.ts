/**
 * The MuAPI models GOAT CREATIONS uses, and how each one wants its request.
 *
 * Every endpoint here appears in MuAPI's official ComfyUI pack
 * (SamurAIGPT/muapi-comfyui) and in Open-Generative-AI's model schema; inputs and
 * allowed values are copied from that schema. Models differ a lot: FLUX/HiDream
 * take pixel sizes, others an aspect ratio; photo models take the picture as
 * `image_url` or inside `images_list`; enhancers take no prompt at all.
 * `buildPayload` turns one simple request into exactly the fields a model accepts.
 *
 * Pure data + pure functions: also exported as JSON for the ComfyUI node pack.
 */

/** What a model does. */
export type ModelTask = 't2i' | 't2v' | 'i2i' | 'i2v' | 'enhance';

export interface ModelSpec {
    /** MuAPI endpoint, e.g. "flux-dev-image". */
    id: string;
    name: string;
    /** One short line for pickers. */
    note: string;
    task: ModelTask;
    /** "pixels" sends width/height, "aspect" sends aspect_ratio, "none" sends neither. */
    size: 'pixels' | 'aspect' | 'none';
    /** Photo models: the field that carries the uploaded picture. */
    imageField?: 'image_url' | 'images_list';
    /** False for models that take no text prompt (upscale, background removal). */
    prompt?: boolean;
    aspectRatios?: readonly string[];
    /** Sent when the caller doesn't ask for a shape (e.g. "auto" keeps a photo's shape). */
    defaultAspect?: string;
    duration?: { min: number; max: number; default: number };
    resolutions?: readonly string[];
    defaultResolution?: string;
    quality?: { values: readonly string[]; default: string };
}

export const IMAGE_MODELS: readonly ModelSpec[] = [
    { id: 'flux-dev-image', name: 'FLUX.1 Dev', note: 'Detailed, all-round', task: 't2i', size: 'pixels' },
    { id: 'flux-schnell-image', name: 'FLUX.1 Schnell', note: 'Fastest, lowest cost', task: 't2i', size: 'pixels' },
    { id: 'hidream_i1_fast_image', name: 'HiDream I1 Fast', note: 'Quick, strong styles', task: 't2i', size: 'pixels' },
    {
        id: 'nano-banana', name: 'Nano Banana', note: "Google's image model", task: 't2i', size: 'aspect',
        aspectRatios: ['1:1', '3:4', '4:3', '9:16', '16:9', '3:2', '2:3', '5:4', '4:5', '21:9'],
    },
    {
        id: 'nano-banana-pro', name: 'Nano Banana Pro', note: 'Sharper, up to 4K', task: 't2i', size: 'aspect',
        aspectRatios: ['1:1', '3:4', '4:3', '9:16', '16:9', '3:2', '2:3', '5:4', '4:5', '21:9'],
        resolutions: ['1k', '2k', '4k'], defaultResolution: '1k',
    },
    {
        id: 'flux-2-pro', name: 'FLUX.2 Pro', note: 'Clean design work, logos', task: 't2i', size: 'aspect',
        aspectRatios: ['16:9', '9:16', '1:1', '4:3', '3:4', '2:3', '3:2'], resolutions: ['1k', '2k'], defaultResolution: '1k',
    },
    {
        id: 'gpt-image-1.5', name: 'GPT Image 1.5', note: 'Good with text in images', task: 't2i', size: 'aspect',
        aspectRatios: ['1:1', '2:3', '3:2'], quality: { values: ['low', 'medium', 'high'], default: 'medium' },
    },
    {
        id: 'gpt-image-2-text-to-image', name: 'GPT Image 2', note: 'Best with headlines and text', task: 't2i', size: 'aspect',
        aspectRatios: ['1:1', '16:9', '9:16', '4:3', '3:4'], resolutions: ['1K', '2K', '4K'], defaultResolution: '2K',
    },
];

export const VIDEO_MODELS: readonly ModelSpec[] = [
    {
        id: 'seedance-lite-t2v', name: 'Seedance 1.0 Lite', note: 'Fast, budget video', task: 't2v', size: 'aspect',
        aspectRatios: ['16:9', '9:16', '1:1', '4:3', '3:4', '9:21'],
        duration: { min: 3, max: 12, default: 5 }, resolutions: ['480p', '720p', '1080p'],
    },
    {
        id: 'seedance-v1.5-pro-t2v-fast', name: 'Seedance 1.5 Pro Fast', note: 'Sharper, 720p and up', task: 't2v', size: 'aspect',
        aspectRatios: ['16:9', '9:16', '1:1', '3:4', '4:3', '21:9'],
        duration: { min: 4, max: 12, default: 5 }, resolutions: ['720p', '1080p'],
    },
    {
        id: 'kling-v2.1-master-t2v', name: 'Kling 2.1 Master', note: 'Cinematic motion', task: 't2v', size: 'aspect',
        aspectRatios: ['16:9', '9:16', '1:1'], duration: { min: 5, max: 10, default: 5 },
    },
    {
        id: 'veo3-fast-text-to-video', name: 'Veo 3 Fast', note: "Google's video, with sound", task: 't2v', size: 'aspect',
        aspectRatios: ['16:9', '9:16'],
    },
    {
        id: 'wan2.2-text-to-video', name: 'Wan 2.2', note: 'Open-weights model', task: 't2v', size: 'aspect',
        aspectRatios: ['16:9', '9:16'], duration: { min: 5, max: 8, default: 5 }, resolutions: ['480p', '720p'],
        quality: { values: ['medium', 'high'], default: 'medium' },
    },
];

/** Models that start from a photo: used by Skills and photo tools. */
export const PHOTO_MODELS: readonly ModelSpec[] = [
    {
        id: 'nano-banana-edit', name: 'Nano Banana Edit', note: 'Edit a photo with words', task: 'i2i', size: 'aspect',
        imageField: 'images_list', aspectRatios: ['1:1', '3:4', '4:3', '9:16', '16:9', '3:2', '2:3', '5:4', '4:5'],
    },
    {
        id: 'flux-2-pro-edit', name: 'FLUX.2 Pro Edit', note: 'Re-stage a product photo', task: 'i2i', size: 'aspect',
        imageField: 'images_list', aspectRatios: ['auto', '16:9', '9:16', '1:1', '4:3', '3:4', '2:3', '3:2'],
        defaultAspect: 'auto', resolutions: ['1k', '2k'], defaultResolution: '1k',
    },
    {
        id: 'seedance-lite-i2v', name: 'Seedance Lite I2V', note: 'Bring a photo to life', task: 'i2v', size: 'none',
        imageField: 'image_url', duration: { min: 3, max: 12, default: 5 }, resolutions: ['480p', '720p', '1080p'],
    },
    {
        id: 'wan2.5-image-to-video', name: 'Wan 2.5 I2V', note: 'Smooth product motion', task: 'i2v', size: 'none',
        imageField: 'image_url', duration: { min: 5, max: 10, default: 5 }, resolutions: ['480p', '720p', '1080p'],
    },
    { id: 'ai-image-upscale', name: 'AI Upscaler', note: 'Bigger, sharper photo', task: 'enhance', size: 'none', imageField: 'image_url', prompt: false },
    { id: 'ai-background-remover', name: 'Background Remover', note: 'Cut out the subject', task: 'enhance', size: 'none', imageField: 'image_url', prompt: false },
];

export const ALL_MODELS: readonly ModelSpec[] = [...IMAGE_MODELS, ...VIDEO_MODELS, ...PHOTO_MODELS];

export const DEFAULT_IMAGE_MODEL = 'flux-dev-image';
export const DEFAULT_VIDEO_MODEL = 'seedance-lite-t2v';

export function findModel(id: string | undefined): ModelSpec | undefined {
    return ALL_MODELS.find((m) => m.id === id);
}

/** True when a model's output is a video. */
export function isVideoModel(spec: ModelSpec): boolean {
    return spec.task === 't2v' || spec.task === 'i2v';
}

/** What callers ask for; `buildPayload` fits it to the model. */
export interface PayloadRequest {
    prompt: string;
    width?: number;
    height?: number;
    aspectRatio?: string;
    duration?: number;
    resolution?: string;
    /** Public URL of the input photo (from `uploadImage`), for photo models. */
    imageUrl?: string;
}

/** Pixel sizes for aspect ratios on width/height models (same table as MuAPI's ComfyUI pack). */
const RATIO_PIXELS: Record<string, [number, number]> = {
    '1:1': [1024, 1024], '16:9': [1344, 768], '9:16': [768, 1344], '4:3': [1152, 864], '3:4': [864, 1152],
    '3:2': [1216, 832], '2:3': [832, 1216], '21:9': [1536, 640], '9:21': [640, 1536],
};

function ratioValue(ratio: string): number {
    const [w, h] = ratio.split(':').map(Number);
    return w > 0 && h > 0 ? w / h : NaN;
}

/** The allowed ratio closest in shape to what was asked for. */
function closestRatio(allowed: readonly string[], wanted: number): string {
    const shaped = allowed.filter((r) => Number.isFinite(ratioValue(r)));
    return shaped.reduce((best, r) =>
        Math.abs(Math.log(ratioValue(r) / wanted)) < Math.abs(Math.log(ratioValue(best) / wanted)) ? r : best,
    );
}

/** Round to a multiple of 64 between 128 and 2048 (FLUX/HiDream grid). */
export function gridSize(px: number): number {
    return Math.min(2048, Math.max(128, Math.round(px / 64) * 64));
}

/**
 * Build the MuAPI payload for `modelId`. `kind` is only used for models outside
 * the catalog (e.g. one set with SEBASTINA_IMAGE_MODEL). Throws if a photo model
 * gets no photo.
 */
export function buildPayload(modelId: string, kind: 'image' | 'video', req: PayloadRequest): Record<string, unknown> {
    const spec = findModel(modelId);

    if (!spec) {
        if (kind === 'video') {
            return {
                prompt: req.prompt,
                aspect_ratio: req.aspectRatio || '16:9',
                duration: req.duration || 5,
                resolution: req.resolution || '480p',
            };
        }
        const fromRatio = req.aspectRatio ? RATIO_PIXELS[req.aspectRatio] : undefined;
        return {
            prompt: req.prompt,
            width: gridSize(req.width ?? fromRatio?.[0] ?? 1024),
            height: gridSize(req.height ?? fromRatio?.[1] ?? 1024),
            num_images: 1,
        };
    }

    const payload: Record<string, unknown> = {};
    if (spec.prompt !== false) payload.prompt = req.prompt;

    if (spec.imageField) {
        if (!req.imageUrl) throw new Error(`${spec.name} needs a photo.`);
        payload[spec.imageField] = spec.imageField === 'images_list' ? [req.imageUrl] : req.imageUrl;
    }

    const asked = req.aspectRatio
        ? ratioValue(req.aspectRatio)
        : req.width && req.height ? req.width / req.height : undefined;

    if (spec.size === 'pixels') {
        const fromRatio = req.aspectRatio ? RATIO_PIXELS[req.aspectRatio] : undefined;
        payload.width = gridSize(req.width ?? fromRatio?.[0] ?? 1024);
        payload.height = gridSize(req.height ?? fromRatio?.[1] ?? 1024);
        payload.num_images = 1;
    } else if (spec.size === 'aspect' && spec.aspectRatios) {
        if (asked && Number.isFinite(asked)) {
            payload.aspect_ratio = closestRatio(spec.aspectRatios, asked);
        } else if (spec.defaultAspect) {
            payload.aspect_ratio = spec.defaultAspect;
        } else if (spec.task === 't2i' || spec.task === 't2v') {
            // From-scratch models need a shape: square images, landscape videos.
            payload.aspect_ratio = closestRatio(spec.aspectRatios, spec.task === 't2v' ? 16 / 9 : 1);
        }
        // Photo edits with no shape asked: leave it out, so the model keeps the photo's shape.
    }

    if (spec.duration) {
        const d = Math.round(req.duration ?? spec.duration.default);
        payload.duration = Math.min(spec.duration.max, Math.max(spec.duration.min, d));
    }
    if (spec.resolutions) {
        payload.resolution = req.resolution && spec.resolutions.includes(req.resolution)
            ? req.resolution
            : spec.defaultResolution ?? spec.resolutions[0];
    }
    if (spec.quality) payload.quality = spec.quality.default;
    return payload;
}
