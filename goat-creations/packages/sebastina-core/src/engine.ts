import axios from 'axios';

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
    /** Who is paying: the customer's external ID in Lago. Required when billing is on. */
    customerId?: string;
    /** Image size in pixels (Flux). Rounded to a multiple of 64, 128–2048. */
    width?: number;
    height?: number;
    /** Video options. */
    aspectRatio?: string;
    duration?: number;
    resolution?: string;
}

export interface GenerationResult {
    success: boolean;
    /** URL of the generated image or video. */
    data?: string;
    error?: string;
}

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
    /** Milliseconds between result polls (MuAPI's own client uses 2000). */
    pollIntervalMs?: number;
}

const SUCCESS = new Set(['completed', 'succeeded', 'success']);
const FAILURE = new Set(['failed', 'error', 'cancelled', 'canceled']);

export class SEBastinaEngine {
    private readonly apiBaseUrl: string;
    private readonly apiKey: string;
    private readonly imageModel: string;
    private readonly videoModel: string;
    private readonly pollIntervalMs: number;
    private readonly middlewares: GenerationMiddleware[] = [];

    constructor(options: EngineOptions = {}) {
        this.apiBaseUrl = (options.apiBaseUrl || 'https://api.muapi.ai').replace(/\/+$/, '');
        this.apiKey = options.apiKey || '';
        this.imageModel = options.imageModel || 'flux-dev-image';
        this.videoModel = options.videoModel || 'seedance-lite-t2v';
        this.pollIntervalMs = options.pollIntervalMs ?? 2000;
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
        const run = (index: number): Promise<GenerationResult> =>
            index < this.middlewares.length
                ? this.middlewares[index](config, () => run(index + 1))
                : this.runPipeline(config);
        try {
            return await run(0);
        } catch (error: any) {
            return { success: false, error: describeError(error) };
        }
    }

    /** Submit the job to MuAPI and wait for the finished asset. */
    private async runPipeline(config: GenerationConfig): Promise<GenerationResult> {
        if (!this.apiKey) {
            return { success: false, error: 'MUAPI_API_KEY is missing. Add it to your .env file.' };
        }

        // Route dynamically if user flips the switch to MotionGOAT (AI Video)
        const endpoint = config.isMotion ? this.videoModel : this.imageModel;
        const payload = config.isMotion
            ? {
                  prompt: config.prompt,
                  aspect_ratio: config.aspectRatio || '16:9',
                  duration: config.duration || 5,
                  resolution: config.resolution || '480p',
              }
            : {
                  prompt: config.prompt,
                  width: fluxSize(config.width ?? 1024),
                  height: fluxSize(config.height ?? 1024),
                  num_images: 1,
              };

        console.log(`[SEBastina] Initiating asset creation pipeline... Mode: ${config.isMotion ? 'MotionGOAT' : 'ImageGOAT'} (${endpoint})`);
        const headers = { 'Content-Type': 'application/json', 'x-api-key': this.apiKey };
        const submit = await axios.post(`${this.apiBaseUrl}/api/v1/${endpoint}`, payload, { headers, timeout: 60000 });

        const requestId: string | undefined = submit.data?.request_id || submit.data?.id;
        if (!requestId) {
            // Some models answer synchronously.
            const url = firstOutput(submit.data);
            return url ? { success: true, data: url } : { success: false, error: 'Engine returned no request ID or output.' };
        }

        // Images finish in seconds; videos can take many minutes (same limits as MuAPI's client).
        const maxAttempts = config.isMotion ? 900 : 60;
        for (let attempt = 1; attempt <= maxAttempts; attempt++) {
            await sleep(this.pollIntervalMs);
            let result: any;
            try {
                const poll = await axios.get(`${this.apiBaseUrl}/api/v1/predictions/${requestId}/result`, { headers, timeout: 30000 });
                result = poll.data;
            } catch (error: any) {
                // Network blips and server errors: keep polling. Auth/other client errors: stop.
                const status = error?.response?.status;
                if ((status === undefined || status >= 500) && attempt < maxAttempts) continue;
                throw error;
            }
            const status = String(result?.status || '').toLowerCase();
            if (SUCCESS.has(status)) {
                const url = firstOutput(result);
                return url ? { success: true, data: url } : { success: false, error: 'Generation finished without an output URL.' };
            }
            if (FAILURE.has(status)) {
                return { success: false, error: `Generation failed: ${result?.error?.message || result?.error || 'unknown error'}` };
            }
        }
        return { success: false, error: `Generation timed out. Request ID: ${requestId}` };
    }
}

/** Round to Flux's grid: a multiple of 64 between 128 and 2048. */
function fluxSize(px: number): number {
    return Math.min(2048, Math.max(128, Math.round(px / 64) * 64));
}

function firstOutput(data: any): string | undefined {
    return data?.outputs?.[0] || data?.url || data?.output?.url || data?.images?.[0];
}

export function describeError(error: any): string {
    const status = error?.response?.status;
    const body = error?.response?.data;
    const detail = typeof body === 'string' ? body : body?.detail || body?.error || body?.message;
    if (status) return `HTTP ${status}${detail ? `: ${String(detail).slice(0, 160)}` : ''}`;
    return error?.message || String(error);
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
