/**
 * GOAT AI Engine Hub: Hugging Face Inference Providers backend.
 *
 * Runs open-weight models hosted on Hugging Face (FLUX.1 Schnell for images,
 * Wan 2.1 for video) with a Hugging Face access token. Billing is per request on
 * the token owner's Hugging Face account (free accounts get a small monthly credit).
 *
 * Works in Node (server, CLI), the Tauri desktop webview and React Native:
 * - no dotenv or Buffer here; Node code loads .env via `sebastina-core/server`;
 * - the token is passed in by the app (typed into Settings, stored on the device),
 *   or read from HF_ACCESS_TOKEN where a real environment exists (server). It is
 *   never baked into an app bundle, where anyone could unpack and spend it.
 *
 * Uses `InferenceClient` (the current name; `HfInference` is a deprecated alias).
 */
import { InferenceClient, type InferenceProviderOrPolicy } from '@huggingface/inference';

export const FLUX_SCHNELL_MODEL = 'black-forest-labs/FLUX.1-schnell';
export const WAN_T2V_MODEL = 'Wan-AI/Wan2.1-T2V-14B';

/** An image or video from Hugging Face, ready for any app. */
export interface HubAsset {
    /** The raw file. */
    blob: Blob;
    /** Same file as a data: URL: shows directly in <img>, <canvas> and React Native <Image>. */
    dataUrl: string;
    mimeType: string;
    model: string;
}

export interface HubOptions {
    /** Hugging Face access token (hf_…). Default: HF_ACCESS_TOKEN from the environment. */
    token?: string;
    /** Provider routing; "auto" lets Hugging Face pick a provider that serves the model. */
    provider?: InferenceProviderOrPolicy;
    /** For tests or proxies. */
    fetch?: typeof fetch;
}

const MAX_PROMPT = 2000;

function envToken(): string {
    const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;
    return env?.HF_ACCESS_TOKEN?.trim() ?? '';
}

function client(options: HubOptions): InferenceClient {
    const token = (options.token ?? envToken()).trim();
    if (!token) {
        throw new Error('No Hugging Face token. Add one in Settings (huggingface.co > Settings > Access Tokens), or set HF_ACCESS_TOKEN on the server.');
    }
    return new InferenceClient(token, options.fetch ? { fetch: options.fetch } : undefined);
}

/** Blob -> data: URL, in browsers / React Native (FileReader) and Node (Buffer). */
export async function blobToDataUrl(blob: Blob): Promise<string> {
    const type = blob.type || 'application/octet-stream';
    if (typeof FileReader !== 'undefined') {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result));
            reader.onerror = () => reject(reader.error ?? new Error('Could not read the file.'));
            reader.readAsDataURL(blob);
        });
    }
    const nodeBuffer = (globalThis as any).Buffer;
    return `data:${type};base64,${nodeBuffer.from(await blob.arrayBuffer()).toString('base64')}`;
}

/** Readable messages for the errors people actually hit. */
function friendly(error: any): Error {
    const status = error?.httpResponse?.status ?? error?.response?.status ?? error?.status;
    const text = String(error?.message ?? error);
    if (status === 401 || status === 403 || /401|unauthori[sz]ed|invalid.*token/i.test(text)) {
        return new Error('Hugging Face rejected the token. Check it in Settings (it needs "Make calls to Inference Providers").');
    }
    if (status === 402 || /402|payment|credits?/i.test(text)) {
        return new Error('Your Hugging Face credit is used up. Add credit or a PRO plan at huggingface.co/settings/billing.');
    }
    if (status === 429 || /429|rate limit/i.test(text)) return new Error('Hugging Face is busy (rate limited). Try again in a minute.');
    return new Error(`Hugging Face: ${text.slice(0, 200)}`);
}

function checkPrompt(prompt: string): string {
    const p = (prompt ?? '').trim();
    if (!p) throw new Error('Prompt cannot be empty.');
    return p.slice(0, MAX_PROMPT);
}

/**
 * The HF client waits between queue polls with an unref'd timer, so a Node script
 * whose only work is this request could exit mid-wait. Hold a timer for the call.
 */
async function keepAlive<T>(work: () => Promise<T>): Promise<T> {
    const hold = setInterval(() => {}, 60_000);
    try {
        return await work();
    } finally {
        clearInterval(hold);
    }
}

/** FLUX works on a 16-px grid; keep sizes sensible for a 4-step model. */
const fluxSize = (px: number) => Math.min(1440, Math.max(256, Math.round(px / 16) * 16));

/**
 * The user's prompt -> FLUX.1 Schnell on Hugging Face -> image blob (and data URL)
 * for the Tauri and Expo apps.
 */
export async function generateFluxAsset(
    prompt: string,
    options: HubOptions & { width?: number; height?: number } = {},
): Promise<HubAsset> {
    const inputs = checkPrompt(prompt);
    const hf = client(options);
    try {
        const blob = await keepAlive(() => hf.textToImage({
            model: FLUX_SCHNELL_MODEL,
            provider: options.provider ?? 'auto',
            inputs,
            parameters: {
                width: fluxSize(options.width ?? 512),
                height: fluxSize(options.height ?? 512),
                num_inference_steps: 4, // Schnell is distilled for 4 steps
            },
        }, { outputType: 'blob' }));
        return { blob, dataUrl: await blobToDataUrl(blob), mimeType: blob.type || 'image/jpeg', model: FLUX_SCHNELL_MODEL };
    } catch (error) {
        throw friendly(error);
    }
}

/** Text -> video with Wan 2.1 on Hugging Face (slow and pricier than images: minutes per clip). */
export async function generateWanVideo(prompt: string, options: HubOptions & { numFrames?: number } = {}): Promise<HubAsset> {
    const inputs = checkPrompt(prompt);
    const hf = client(options);
    try {
        const blob = await keepAlive(() => hf.textToVideo({
            model: WAN_T2V_MODEL,
            provider: options.provider ?? 'auto',
            inputs,
            parameters: { num_frames: Math.min(121, Math.max(17, Math.round(options.numFrames ?? 81))) },
        }));
        return { blob, dataUrl: await blobToDataUrl(blob), mimeType: blob.type || 'video/mp4', model: WAN_T2V_MODEL };
    } catch (error) {
        throw friendly(error);
    }
}

/** A hub bound to one token: what the apps create from the token in their Settings. */
export function createGOATAIEngineHub(options: HubOptions = {}) {
    return {
        /** UNIVERSAL IMAGE PIPELINE (ImageGOAT, SEBastina, canvas layers): FLUX.1 Schnell, returns a data: URL. */
        async textToImage(prompt: string, width = 512, height = 512): Promise<string> {
            console.log(`[GOAT AI HUB] text-to-image (FLUX.1 Schnell, ${width}x${height})`);
            return (await generateFluxAsset(prompt, { ...options, width, height })).dataUrl;
        },
        /** UNIVERSAL VIDEO PIPELINE (MotionGOAT): Wan 2.1, returns the clip as a data: URL. */
        async textToVideo(prompt: string): Promise<{ videoUrl: string; blob: Blob; status: string }> {
            console.log('[GOAT AI HUB] text-to-video (Wan 2.1)');
            const video = await generateWanVideo(prompt, options);
            return { videoUrl: video.dataUrl, blob: video.blob, status: 'Render complete.' };
        },
    };
}

/** Default hub for Node (server, CLI): token from HF_ACCESS_TOKEN. Apps should use createGOATAIEngineHub({ token }). */
export const GOATAIEngineHub = createGOATAIEngineHub();
