/** Node-only parts of sebastina-core (import from `sebastina-core/server`). */
// Load .env (HF_ACCESS_TOKEN, MUAPI_API_KEY, ...) for Node users. Never imported by the apps.
import 'dotenv/config';
export * from './index.js';
export { LagoBilling } from './billing/lago.js';
export type { CreditStatus } from './billing/lago.js';
export { lagoCreditGate } from './billing/creditGate.js';
export { issueCustomerToken, verifyCustomerToken } from './auth.js';
export { crawlerPaywall, streamAsset, isAiCrawler, usdcToAtomic, DEFAULT_AI_CRAWLERS } from './paywall/x402.js';
export type { CrawlerPaywallOptions, PaymentRequirements, PaywallNetwork, Middleware } from './paywall/x402.js';
