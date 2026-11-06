/**
 * The models GOAT CREATIONS offers, and how each one wants its request.
 *
 * Endpoints appear in both MuAPI's official ComfyUI pack (SamurAIGPT/muapi-comfyui)
 * and Open-Generative-AI's model schema; inputs and allowed values are copied
 * from that schema. Models differ: FLUX/HiDream take pixel sizes, Nano Banana and
 * GPT Image take an aspect ratio, video models each have their own durations and
 * resolutions. `buildPayload` turns one simple request into the right fields.
 */

export interface ModelSpec {
    /** MuAPI endpoint, e.g. "flux-dev-image". */
    id: string;
    name: string;
    /** One short line for pickers. */
    note: string;
    kind: 'image' | 'video';
    /** Images: "pixels" sends width/height; "aspect" sends aspect_ratio. */
    size: 'pixels' | 'aspect';
    aspectRatios?: readonly string[];
    duration?: { min: number; max: number; default: number };
    resolutions?: readonly string[];
    quality?: { values: readonly string[]; default: string };
}

export const IMAGE_MODELS: readonly ModelSpec[] = [
    { id: 'flux-dev-image', name: 'FLUX.1 Dev', note: 'Detailed, all-round', kind: 'image', size: 'pixels' },
    { id: 'flux-schnell-image', name: 'FLUX.1 Schnell', note: 'Fastest, lowest cost', kind: 'image', size: 'pixels' },
    { id: 'hidream_i1_fast_image', name: 'HiDream I1 Fast', note: 'Quick, strong styles', kind: 'image', size: 'pixels' },
    {
        id: 'nano-banana', name: 'Nano Banana', note: "Google's image model", kind: 'image', size: 'aspect',
        aspectRatios: ['1:1', '3:4', '4:3', '9:16', '16:9', '3:2', '2:3', '5:4', '4:5', '21:9'],
    },
    {
        id: 'gpt-image-1.5', name: 'GPT Image 1.5', note: 'Best with text in images', kind: 'image', size: 'aspect',
        aspectRatios: ['1:1', '2:3', '3:2'], quality: { values: ['low', 'medium', 'high'], default: 'medium' },
    },
];

export const VIDEO_MODELS: readonly ModelSpec[] = [
    {
        id: 'seedance-lite-t2v', name: 'Seedance 1.0 Lite', note: 'Fast, budget video', kind: 'video', size: 'aspect',
        aspectRatios: ['16:9', '9:16', '1:1', '4:3', '3:4', '9:21'],
        duration: { min: 3, max: 12, default: 5 }, resolutions: ['480p', '720p', '1080p'],
    },
    {
        id: 'seedance-v1.5-pro-t2v-fast', name: 'Seedance 1.5 Pro Fast', note: 'Sharper, 720p and up', kind: 'video', size: 'aspect',
        aspectRatios: ['16:9', '9:16', '1:1', '3:4', '4:3', '21:9'],
        duration: { min: 4, max: 12, default: 5 }, resolutions: ['720p', '1080p'],
    },
    {
        id: 'kling-v2.1-master-t2v', name: 'Kling 2.1 Master', note: 'Cinematic motion', kind: 'video', size: 'aspect',
        aspectRatios: ['16:9', '9:16', '1:1'], duration: { min: 5, max: 10, default: 5 },
    },
    {
        id: 'veo3-fast-text-to-video', name: 'Veo 3 Fast', note: "Google's video, with sound", kind: 'video', size: 'aspect',
        aspectRatios: ['16:9', '9:16'],
    },
    {
        id: 'wan2.2-text-to-video', name: 'Wan 2.2', note: 'Open-weights model', kind: 'video', size: 'aspect',
        aspectRatios: ['16:9', '9:16'], duration: { min: 5, max: 8, default: 5 }, resolutions: ['480p', '720p'],
        quality: { values: ['medium', 'high'], default: 'medium' },
    },
];

export const DEFAULT_IMAGE_MODEL = 'flux-dev-image';
export const DEFAULT_VIDEO_MODEL = 'seedance-lite-t2v';

export function findModel(id: string | undefined): ModelSpec | undefined {
    return [...IMAGE_MODELS, ...VIDEO_MODELS].find((m) => m.id === id);
}

/** What the apps ask for; `buildPayload` fits it to the model. */
export interface PayloadRequest {
    prompt: string;
    width?: number;
    height?: number;
    aspectRatio?: string;
    duration?: number;
    resolution?: string;
}

/** Pixel sizes for aspect ratios on width/height models (same table as MuAPI's ComfyUI pack). */
const RATIO_PIXELS: Record<string, [number, number]> = {
    '1:1': [1024, 1024], '16:9': [1344, 768], '9:16': [768, 1344], '4:3': [1152, 864], '3:4': [864, 1152],
    '3:2': [1216, 832], '2:3': [832, 1216], '21:9': [1536, 640], '9:21': [640, 1536],
};

function ratioValue(ratio: string): number {
    const [w, h] = ratio.split(':').map(Number);
    return w > 0 && h > 0 ? w / h : 1;
}

/** The allowed ratio closest in shape to what was asked for. */
function closestRatio(allowed: readonly string[], wanted: number): string {
    return allowed.reduce((best, r) =>
        Math.abs(Math.log(ratioValue(r) / wanted)) < Math.abs(Math.log(ratioValue(best) / wanted)) ? r : best,
    );
}

/** Round to a multiple of 64 between 128 and 2048 (FLUX/HiDream grid). */
export function gridSize(px: number): number {
    return Math.min(2048, Math.max(128, Math.round(px / 64) * 64));
}

/**
 * Build the MuAPI payload for `model` (falls back to sensible fields for a model
 * that isn't in the catalog, e.g. one set with SEBASTINA_IMAGE_MODEL).
 */
export function buildPayload(modelId: string, kind: 'image' | 'video', req: PayloadRequest): Record<string, unknown> {
    const spec = findModel(modelId);
    const wantedRatio = req.aspectRatio
        ? ratioValue(req.aspectRatio)
        : req.width && req.height
          ? req.width / req.height
          : kind === 'video' ? 16 / 9 : 1;

    if (kind === 'image') {
        if (!spec || spec.size === 'pixels') {
            const fromRatio = req.aspectRatio ? RATIO_PIXELS[req.aspectRatio] : undefined;
            const width = req.width ?? fromRatio?.[0] ?? 1024;
            const height = req.height ?? fromRatio?.[1] ?? 1024;
            return { prompt: req.prompt, width: gridSize(width), height: gridSize(height), num_images: 1 };
        }
        const payload: Record<string, unknown> = {
            prompt: req.prompt,
            aspect_ratio: closestRatio(spec.aspectRatios ?? ['1:1'], wantedRatio),
        };
        if (spec.quality) payload.quality = spec.quality.default;
        return payload;
    }

    if (!spec) {
        return {
            prompt: req.prompt,
            aspect_ratio: req.aspectRatio || '16:9',
            duration: req.duration || 5,
            resolution: req.resolution || '480p',
        };
    }
    const payload: Record<string, unknown> = {
        prompt: req.prompt,
        aspect_ratio: closestRatio(spec.aspectRatios ?? ['16:9'], wantedRatio),
    };
    if (spec.duration) {
        const d = Math.round(req.duration ?? spec.duration.default);
        payload.duration = Math.min(spec.duration.max, Math.max(spec.duration.min, d));
    }
    if (spec.resolutions) {
        payload.resolution = req.resolution && spec.resolutions.includes(req.resolution) ? req.resolution : spec.resolutions[0];
    }
    if (spec.quality) payload.quality = spec.quality.default;
    return payload;
}
