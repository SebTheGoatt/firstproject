import axios from 'axios';
import { buildPayload, findModel, isVideoModel, DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL, type PayloadRequest } from './models.js';
import { findSkill, renderPrompt, skillOutput } from './skills.js';

/**
 * SEBastina talks to MuAPI (api.muapi.ai), the generation API behind the
 * open-source Open-Generative-AI studio (github.com/Anil-matcha/Open-Generative-AI).
 * Its request format, copied from that project's `muapi.js`:
 *
 *   POST {base}/api/v1/{model-endpoint}         header x-api-key, JSON payload
 *     -> { request_id }
 *   GET  {base}/api/v1/predictions/{id}/result  (poll every 2 s)
 *     -> { status: "completed" | "failed" | ..., outputs: ["https://..."] }
 *
 * Image (Flux): endpoint "flux-dev-image", payload { prompt, width, height, num_images }
 *               width/height: multiples of 64 between 128 and 2048.
 * Video:        endpoint "seedance-lite-t2v" (the Video Studio's default model),
 *               payload { prompt, aspect_ratio, duration, resolution }.
 */

export interface GenerationConfig {
    prompt: string;
    /** MotionGOAT (video) instead of ImageGOAT (image). */
    isMotion?: boolean;
    /** MuAPI model endpoint (see models.ts). Default: the engine's image/video model. */
    model?: string;
    /** Who is paying: the customer's external ID in Lago. Required when billing is on. */
    customerId?: string;
    /** Image size in pixels; models that take an aspect ratio get the closest one. */
    width?: number;
    height?: number;
    /** Shape for video, or for images on aspect-ratio models. */
    aspectRatio?: string;
    /** Input photo URL (from `uploadImage`) for photo models. */
    imageUrl?: string;
    /** Set when this request runs a Skill (the credit gate charges per step). */
    skillId?: string;
    duration?: number;
    resolution?: string;
}

export interface GenerationResult {
    success: boolean;
    /** URL of the generated image or video. */
    data?: string;
    error?: string;
    /** Skills: every step's result URL, in order (the last one is `data`). */
    outputs?: string[];
    /** Skills: whether `data` is an image or a video. */
    kind?: 'image' | 'video';
}

/** Run a Skill: its id, the user's text for its fields, and the uploaded photo if it needs one. */
export interface SkillRequest {
    skillId: string;
    inputs?: Record<string, string>;
    photoUrl?: string;
    customerId?: string;
}

/** A picture to upload: a Blob/File (browser, Node), or `{ uri, name, type }` (React Native). */
export type UploadInput = Blob | { uri: string; name?: string; type?: string };

/** Runs before the generation pipeline; call `next()` to continue, or return early to stop. */
export type GenerationMiddleware = (
    config: GenerationConfig,
    next: () => Promise<GenerationResult>,
) => Promise<GenerationResult>;

export interface EngineOptions {
    apiBaseUrl?: string;
    apiKey?: string;
    imageModel?: string;
    videoModel?: string;
    /** If set, only these model endpoints may be requested (the server uses this). */
    allowedModels?: readonly string[];
    /** If set, only these Skills may be run (the server uses this). */
    allowedSkills?: readonly string[];
    /** Milliseconds between result polls (MuAPI's own client uses 2000). */
    pollIntervalMs?: number;
}

const NO_KEY = 'No MuAPI key set. Add it in Settings (or MUAPI_API_KEY on the server).';
const SUCCESS = new Set(['completed', 'succeeded', 'success']);
const FAILURE = new Set(['failed', 'error', 'cancelled', 'canceled']);

export class SEBastinaEngine {
    private readonly apiBaseUrl: string;
    private readonly apiKey: string;
    private readonly imageModel: string;
    private readonly videoModel: string;
    private readonly pollIntervalMs: number;
    private readonly allowedModels?: readonly string[];
    private readonly allowedSkills?: readonly string[];
    private readonly middlewares: GenerationMiddleware[] = [];

    constructor(options: EngineOptions = {}) {
        this.apiBaseUrl = (options.apiBaseUrl || 'https://api.muapi.ai').replace(/\/+$/, '');
        this.apiKey = options.apiKey || '';
        this.imageModel = options.imageModel || DEFAULT_IMAGE_MODEL;
        this.videoModel = options.videoModel || DEFAULT_VIDEO_MODEL;
        this.pollIntervalMs = options.pollIntervalMs ?? 2000;
        this.allowedModels = options.allowedModels;
        this.allowedSkills = options.allowedSkills;
    }

    /** Add a middleware; they run in the order added, before generation. */
    use(middleware: GenerationMiddleware): this {
        this.middlewares.push(middleware);
        return this;
    }

    /**
     * Core processing method for SEBastina pipeline assets.
     * Every request passes through the middlewares (e.g. the Lago credit gate) first.
     */
    async generateAsset(config: GenerationConfig): Promise<GenerationResult> {
        return this.throughMiddleware(config, () => this.runPipeline(config));
    }

    /**
     * Run a Skill: fill its prompts, pass the middlewares once (billing for all
     * steps), then run each step, feeding a step's result into the next.
     */
    async runSkill(request: SkillRequest): Promise<GenerationResult> {
        const skill = findSkill(request.skillId);
        if (!skill) return { success: false, error: 'Unknown Skill.' };
        if (this.allowedSkills && !this.allowedSkills.includes(skill.id)) {
            return { success: false, error: `The Skill "${skill.name}" isn't offered here.` };
        }
        if (skill.needsPhoto && !request.photoUrl) return { success: false, error: `${skill.name} needs a photo.` };

        const prompts: string[] = [];
        for (const step of skill.steps) {
            const rendered = renderPrompt(step.prompt, skill, request.inputs ?? {});
            if (rendered.missing) return { success: false, error: `Fill in "${rendered.missing.label}".` };
            prompts.push(rendered.prompt);
        }
        const kind = skillOutput(skill);
        const config: GenerationConfig = {
            prompt: prompts[0] || skill.name,
            isMotion: kind === 'video',
            customerId: request.customerId,
            skillId: skill.id,
            imageUrl: request.photoUrl,
        };

        return this.throughMiddleware(config, async () => {
            if (!this.apiKey) return { success: false, error: NO_KEY };
            const outputs: string[] = [];
            for (const [i, step] of skill.steps.entries()) {
                const spec = findModel(step.model);
                const imageUrl = step.from === 'photo' ? request.photoUrl : step.from === 'previous' ? outputs[i - 1] : undefined;
                const result = await this.runModel(step.model, spec ? isVideoModel(spec) : false, {
                    prompt: prompts[i],
                    aspectRatio: step.aspectRatio,
                    duration: step.duration,
                    resolution: step.resolution,
                    imageUrl,
                });
                if (!result.success || !result.data) {
                    const where = skill.steps.length > 1 ? ` (step ${i + 1} of ${skill.steps.length})` : '';
                    return { ...result, success: false, error: `${result.error ?? 'Step failed'}${where}`, outputs };
                }
                outputs.push(result.data);
            }
            return { success: true, data: outputs[outputs.length - 1], outputs, kind };
        });
    }

    /**
     * Upload a picture to MuAPI and get back a public URL for photo models.
     * Uses fetch + FormData so it works in browsers, React Native and Node.
     */
    async uploadImage(file: UploadInput, fileName = 'photo.jpg'): Promise<string> {
        if (!this.apiKey) throw new Error(NO_KEY);
        const form = new FormData();
        if (typeof Blob !== 'undefined' && file instanceof Blob) {
            form.append('file', file, fileName);
        } else {
            const rn = file as { uri: string; name?: string; type?: string };
            // React Native's FormData accepts { uri, name, type } for local files.
            form.append('file', { uri: rn.uri, name: rn.name ?? fileName, type: rn.type ?? 'image/jpeg' } as any);
        }
        const response = await fetch(`${this.apiBaseUrl}/api/v1/upload_file`, {
            method: 'POST',
            headers: { 'x-api-key': this.apiKey },
            body: form,
        });
        const data: any = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(muapiErrorMessage({ response: { status: response.status, data } }));
        const url = data?.url || data?.file_url || data?.output;
        if (typeof url !== 'string' || !url) throw new Error('Upload finished without a file URL.');
        return url;
    }

    private async throughMiddleware(config: GenerationConfig, handler: () => Promise<GenerationResult>): Promise<GenerationResult> {
        const run = (index: number): Promise<GenerationResult> =>
            index < this.middlewares.length ? this.middlewares[index](config, () => run(index + 1)) : handler();
        try {
            return await run(0);
        } catch (error: any) {
            return { success: false, error: describeError(error) };
        }
    }

    /** One model call: build its payload, submit, wait. Never throws. */
    private async runModel(endpoint: string, isVideo: boolean, request: PayloadRequest): Promise<GenerationResult> {
        if (!/^[A-Za-z0-9._-]+$/.test(endpoint)) return { success: false, error: 'Invalid model name.' };
        let payload: Record<string, unknown>;
        try {
            payload = buildPayload(endpoint, isVideo ? 'video' : 'image', request);
        } catch (error: any) {
            return { success: false, error: error?.message ?? String(error) };
        }
        try {
            return await this.submitAndPoll(endpoint, payload, isVideo);
        } catch (error) {
            return { success: false, error: muapiErrorMessage(error) };
        }
    }

    /** Submit the job to MuAPI and wait for the finished asset. */
    private async runPipeline(config: GenerationConfig): Promise<GenerationResult> {
        if (!this.apiKey) {
            return { success: false, error: NO_KEY };
        }

        // Route dynamically if user flips the switch to MotionGOAT (AI Video)
        const endpoint = config.model || (config.isMotion ? this.videoModel : this.imageModel);
        if (this.allowedModels && !this.allowedModels.includes(endpoint)) {
            return { success: false, error: `The model "${endpoint}" isn't offered here.` };
        }
        const spec = findModel(endpoint);
        return this.runModel(endpoint, spec ? isVideoModel(spec) : !!config.isMotion, config);
    }

    private async submitAndPoll(endpoint: string, payload: Record<string, unknown>, isMotion: boolean): Promise<GenerationResult> {

        console.log(`[SEBastina] Initiating asset creation pipeline... Mode: ${isMotion ? 'MotionGOAT' : 'ImageGOAT'} (${endpoint})`);
        const headers = { 'Content-Type': 'application/json', 'x-api-key': this.apiKey };
        const submit = await axios.post(`${this.apiBaseUrl}/api/v1/${endpoint}`, payload, { headers, timeout: 60000 });

        const requestId: string | undefined = submit.data?.request_id || submit.data?.id;
        if (!requestId) {
            // Some models answer synchronously.
            const url = firstOutput(submit.data);
            return url ? { success: true, data: url } : { success: false, error: 'Engine returned no request ID or output.' };
        }

        // Images finish in seconds; videos can take many minutes (same limits as MuAPI's client).
        const maxAttempts = isMotion ? 900 : 60;
        for (let attempt = 1; attempt <= maxAttempts; attempt++) {
            await sleep(this.pollIntervalMs);
            let result: any;
            try {
                const poll = await axios.get(`${this.apiBaseUrl}/api/v1/predictions/${requestId}/result`, { headers, timeout: 30000 });
                result = poll.data;
            } catch (error: any) {
                const status = error?.response?.status;
                // MuAPI reports a failed generation as HTTP 400 with the reason in the body.
                if (status === 400 && error.response.data) {
                    return { success: false, error: `Generation failed: ${failureReason(error.response.data)}` };
                }
                // Network blips and server errors: keep polling. Auth/other client errors: stop.
                if ((status === undefined || status >= 500) && attempt < maxAttempts) continue;
                throw error;
            }
            const status = String(result?.status || '').toLowerCase();
            if (SUCCESS.has(status)) {
                const url = firstOutput(result);
                return url ? { success: true, data: url } : { success: false, error: 'Generation finished without an output URL.' };
            }
            if (FAILURE.has(status)) {
                return { success: false, error: `Generation failed: ${failureReason(result)}` };
            }
        }
        return { success: false, error: `Generation timed out. Request ID: ${requestId}` };
    }
}

/** The result URL, wherever MuAPI put it (shapes seen in MuAPI's own clients). */
function firstOutput(data: any): string | undefined {
    const out = data?.outputs ?? data?.output;
    if (Array.isArray(out) && out.length) return String(out[0]);
    if (typeof out === 'string' && out) return out;
    if (typeof out?.url === 'string') return out.url;
    for (const key of ['video_url', 'image_url', 'url']) {
        if (typeof data?.[key] === 'string' && data[key]) return data[key];
    }
    return Array.isArray(data?.images) && data.images.length ? String(data.images[0]) : undefined;
}

function failureReason(data: any): string {
    const e = data?.error;
    return String((typeof e === 'object' ? e?.message : e) || data?.detail || data?.message || 'unknown error').slice(0, 200);
}

/** Plain-language messages for the MuAPI errors people actually hit. */
function muapiErrorMessage(error: any): string {
    switch (error?.response?.status) {
        case 401:
        case 403:
            return 'MuAPI rejected the API key. Check it in Settings.';
        case 402:
            return 'Your MuAPI account is out of credit. Top up at muapi.ai.';
        case 429:
            return 'MuAPI is busy right now (rate limited). Try again in a minute.';
        default:
            return describeError(error);
    }
}

export function describeError(error: any): string {
    const status = error?.response?.status;
    const body = error?.response?.data;
    const detail = typeof body === 'string' ? body : body?.detail || body?.error || body?.message;
    if (status) return `HTTP ${status}${detail ? `: ${String(detail).slice(0, 160)}` : ''}`;
    return error?.message || String(error);
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
