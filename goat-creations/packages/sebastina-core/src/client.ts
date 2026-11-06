/**
 * The SEBastina client used by the desktop (Tauri) and mobile (Expo) apps.
 *
 * Apps talk to the SEBastina server, which runs the shared engine with the
 * MuAPI and Lago keys. Keys never ship inside an app (anyone can unpack an app
 * and read them). Uses only `fetch`, so it runs in browsers, Tauri webviews,
 * React Native and Node alike.
 */
import { appendFile, type GenerationResult, type SkillRequest, type UploadInput } from './engine.js';

/** The suite's generation modules, shared so every app labels them the same way. */
export const GOAT_MODULES = [
    { id: 'image', name: 'ImageGOAT', tagline: 'Raster & photo generation', isMotion: false },
    { id: 'motion', name: 'MotionGOAT', tagline: 'Video & animation generation', isMotion: true },
] as const;

export type GoatModuleId = (typeof GOAT_MODULES)[number]['id'];

export interface GenerateRequest {
    prompt: string;
    isMotion?: boolean;
    /** MuAPI model endpoint from IMAGE_MODELS / VIDEO_MODELS. */
    model?: string;
    width?: number;
    height?: number;
    aspectRatio?: string;
    duration?: number;
    resolution?: string;
}

export interface ClientOptions {
    /** e.g. http://127.0.0.1:8787 or https://api.goatcreations.app */
    serverUrl: string;
    /** The customer's access token (from the server owner). */
    token: string;
    fetchImpl?: typeof fetch;
}

export class SEBastinaClient {
    private readonly serverUrl: string;
    private readonly token: string;
    private readonly doFetch: typeof fetch;

    constructor(options: ClientOptions) {
        this.serverUrl = options.serverUrl.replace(/\/+$/, '');
        this.token = options.token.trim();
        this.doFetch = options.fetchImpl ?? ((input, init) => fetch(input, init));
    }

    /** Ask the server to generate an image or video. Never throws: errors come back in the result. */
    async generate(request: GenerateRequest): Promise<GenerationResult> {
        if (!request.prompt.trim()) return { success: false, error: 'Prompt cannot be empty.' };
        if (!this.serverUrl) return { success: false, error: 'Set the server address first.' };
        if (!this.token) return { success: false, error: 'No access token yet. Open Settings and paste the token you were given.' };
        try {
            const response = await this.doFetch(`${this.serverUrl}/api/generate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${this.token}` },
                body: JSON.stringify(request),
            });
            const data = (await response.json().catch(() => null)) as GenerationResult | null;
            if (data && typeof data.success === 'boolean') return data;
            return { success: false, error: `Server answered ${response.status} without a result.` };
        } catch (error: any) {
            return { success: false, error: `Can't reach the server: ${error?.message ?? error}` };
        }
    }

    /** Model endpoints this server allows (empty list if it can't be reached). */
    async allowedModels(): Promise<string[]> {
        try {
            const response = await this.doFetch(`${this.serverUrl}/api/models`, { headers: this.token ? { Authorization: `Bearer ${this.token}` } : {} });
            const data = (await response.json()) as { models?: unknown };
            return Array.isArray(data.models) ? data.models.filter((m): m is string => typeof m === 'string') : [];
        } catch {
            return [];
        }
    }

    /** Skill ids this server allows (empty list if none or unreachable). */
    async allowedSkills(): Promise<string[]> {
        try {
            const response = await this.doFetch(`${this.serverUrl}/api/skills`, { headers: this.token ? { Authorization: `Bearer ${this.token}` } : {} });
            const data = (await response.json()) as { skills?: unknown };
            return Array.isArray(data.skills) ? data.skills.filter((m): m is string => typeof m === 'string') : [];
        } catch {
            return [];
        }
    }

    /** Upload a photo through the server; resolves to its public URL. Throws with a readable message. */
    async uploadImage(file: UploadInput, fileName = 'photo.jpg'): Promise<string> {
        const form = new FormData();
        await appendFile(form, 'file', file, fileName);
        let response: Response;
        try {
            response = await this.doFetch(`${this.serverUrl}/api/upload`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${this.token}` },
                body: form,
            });
        } catch (error: any) {
            throw new Error(`Can't reach the server: ${error?.message ?? error}`);
        }
        const data = (await response.json().catch(() => ({}))) as { url?: string; error?: string };
        if (!response.ok || !data.url) throw new Error(data.error || `Upload failed (${response.status}).`);
        return data.url;
    }

    /** Run a Skill on the server (the customer comes from the token, not the request). */
    async runSkill(request: Omit<SkillRequest, 'customerId'>): Promise<GenerationResult> {
        try {
            const response = await this.doFetch(`${this.serverUrl}/api/skill`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${this.token}` },
                body: JSON.stringify(request),
            });
            const data = (await response.json().catch(() => null)) as GenerationResult | null;
            if (data && typeof data.success === 'boolean') return data;
            return { success: false, error: `Server answered ${response.status} without a result.` };
        } catch (error: any) {
            return { success: false, error: `Can't reach the server: ${error?.message ?? error}` };
        }
    }

    /** Quick reachability check for settings screens. */
    async health(): Promise<boolean> {
        try {
            const response = await this.doFetch(`${this.serverUrl}/health`);
            return response.ok;
        } catch {
            return false;
        }
    }
}
