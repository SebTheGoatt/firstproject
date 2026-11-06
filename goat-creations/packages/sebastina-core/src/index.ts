/**
 * sebastina-core: the shared GOAT CREATIONS pipeline.
 *
 * `sebastina-core`        works everywhere (Node, browser, Tauri, React Native):
 *                         the generation engine and the app client.
 * `sebastina-core/server` Node only: Lago billing, customer tokens, AI-crawler paywall.
 */
export { SEBastinaEngine, describeError } from './engine.js';
export type { GenerationConfig, GenerationResult, GenerationMiddleware, EngineOptions, SkillRequest, UploadInput } from './engine.js';
export { SEBastinaClient, GOAT_MODULES } from './client.js';
export {
    IMAGE_MODELS,
    VIDEO_MODELS,
    PHOTO_MODELS,
    ALL_MODELS,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_VIDEO_MODEL,
    findModel,
    isVideoModel,
    buildPayload,
} from './models.js';
export type { ModelSpec, ModelTask, PayloadRequest } from './models.js';
export { SKILLS, CHARACTER_SKILLS, findSkill, renderPrompt, skillOutput, skillCredits, contentIssue } from './skills.js';
export type { Skill, SkillField, SkillStep } from './skills.js';
export type { ClientOptions, GenerateRequest, GoatModuleId } from './client.js';
