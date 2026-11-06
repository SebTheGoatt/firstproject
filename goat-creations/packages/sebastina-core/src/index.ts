/**
 * sebastina-core: the shared GOAT CREATIONS pipeline.
 *
 * `sebastina-core`        works everywhere (Node, browser, Tauri, React Native):
 *                         the generation engine and the app client.
 * `sebastina-core/server` Node only: Lago billing, customer tokens, AI-crawler paywall.
 */
export { SEBastinaEngine, describeError } from './engine.js';
export type { GenerationConfig, GenerationResult, GenerationMiddleware, EngineOptions } from './engine.js';
export { SEBastinaClient, GOAT_MODULES } from './client.js';
export type { ClientOptions, GenerateRequest, GoatModuleId } from './client.js';
