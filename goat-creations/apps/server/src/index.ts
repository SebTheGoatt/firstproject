/**
 * SEBastina server: the one place that holds the MuAPI and Lago keys.
 *
 *   GET  /health          reachability check for the apps
 *   GET  /api/models      model endpoints customers may pick
 *   POST /api/generate    ImageGOAT / MotionGOAT generation for the desktop and
 *                         mobile apps (customer token + Lago credits required)
 *   GET  /data/<file>     data assets; AI crawlers pay per request (x402, USDC)
 *   GET  /                small landing page, same crawler rule
 */
import 'dotenv/config';
import http from 'node:http';
import { join, normalize, resolve, sep } from 'node:path';
import { promises as fs } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
    SEBastinaEngine,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_VIDEO_MODEL,
    LagoBilling,
    lagoCreditGate,
    verifyCustomerToken,
    crawlerPaywall,
    streamAsset,
    isAiCrawler,
    type GenerationConfig,
    type Middleware,
    type PaywallNetwork,
} from 'sebastina-core/server';

const env = process.env;
const PORT = Number(env.PORT || 8787);
const DATA_DIR = resolve(fileURLToPath(new URL('../data', import.meta.url)));
const MAX_BODY_BYTES = 16 * 1024;

// ---------------------------------------------------------------- generation
// Customers pay the same credit whatever the model, so only models the owner lists
// are offered (pricier ones like Veo or Kling cost more per generation at MuAPI).
const imageModel = env.SEBASTINA_IMAGE_MODEL || DEFAULT_IMAGE_MODEL;
const videoModel = env.SEBASTINA_VIDEO_MODEL || DEFAULT_VIDEO_MODEL;
const allowedModels = (env.SEBASTINA_SERVER_MODELS || `${imageModel},${videoModel}`)
    .split(',')
    .map((m) => m.trim())
    .filter(Boolean);
const engine = new SEBastinaEngine({
    apiBaseUrl: env.AI_BACKEND_URL || 'https://api.muapi.ai',
    apiKey: env.MUAPI_API_KEY,
    imageModel,
    videoModel,
    allowedModels,
});
const billingOn = (env.SEBASTINA_BILLING || 'on').toLowerCase() !== 'off';
if (billingOn) {
    engine.use(
        lagoCreditGate(LagoBilling.fromEnv(env), {
            image: Number(env.CREDITS_PER_IMAGE || 1),
            video: Number(env.CREDITS_PER_VIDEO || 1),
        }),
    );
}
const tokenSecret = env.SEBASTINA_TOKEN_SECRET || '';

// ---------------------------------------------------------------- crawler paywall
let paywall: Middleware;
if (env.PAYWALL_PAY_TO) {
    paywall = crawlerPaywall({
        payTo: env.PAYWALL_PAY_TO,
        network: (env.PAYWALL_NETWORK as PaywallNetwork) || 'base-sepolia',
        priceUsdc: env.PAYWALL_PRICE_USDC || '0.001',
        facilitatorUrl: env.PAYWALL_FACILITATOR_URL || undefined,
        publicOrigin: env.PUBLIC_ORIGIN || undefined,
    });
} else {
    // No wallet set: AI crawlers can't pay, so they get nothing (fail closed).
    paywall = (req, res, next) => {
        if (!isAiCrawler(req.headers['user-agent'])) return next();
        sendJson(res, 403, { error: 'AI crawler access is not available.' }, { Connection: 'close' });
    };
    console.warn('[server] PAYWALL_PAY_TO is not set: AI crawlers are refused instead of charged.');
}

// ---------------------------------------------------------------- helpers
function sendJson(res: http.ServerResponse, status: number, body: unknown, headers: Record<string, string> = {}) {
    const text = JSON.stringify(body);
    res.writeHead(status, { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(text), ...headers });
    res.end(text);
}

async function readJson(req: http.IncomingMessage): Promise<any> {
    let size = 0;
    const chunks: Buffer[] = [];
    for await (const chunk of req) {
        size += (chunk as Buffer).length;
        if (size > MAX_BODY_BYTES) throw new Error('Request body too large.');
        chunks.push(chunk as Buffer);
    }
    return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
}

/** Resolve /data/<name> inside DATA_DIR only (no ../ escapes). */
function dataPath(urlPath: string): string | null {
    const relative = decodeURIComponent(urlPath.replace(/^\/data\//, ''));
    const full = resolve(DATA_DIR, normalize(relative));
    return full.startsWith(DATA_DIR + sep) ? full : null;
}

// Bearer tokens (no cookies), so any origin may call the API: the Tauri webview,
// Expo web, or a local dev server.
const CORS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
};

async function handleGenerate(req: http.IncomingMessage, res: http.ServerResponse) {
    if (tokenSecret.length < 32) {
        return sendJson(res, 503, { success: false, error: 'Server is missing SEBASTINA_TOKEN_SECRET.' }, CORS);
    }
    const bearer = /^Bearer\s+(.+)$/i.exec(req.headers.authorization ?? '')?.[1];
    const customerId = verifyCustomerToken(bearer, tokenSecret);
    if (!customerId) return sendJson(res, 401, { success: false, error: 'Missing or invalid access token.' }, CORS);

    let body: any;
    try {
        body = await readJson(req);
    } catch (error: any) {
        return sendJson(res, 400, { success: false, error: error.message || 'Invalid JSON.' }, CORS);
    }
    if (typeof body.prompt !== 'string' || !body.prompt.trim() || body.prompt.length > 3000) {
        return sendJson(res, 400, { success: false, error: 'Prompt must be 1 to 3000 characters.' }, CORS);
    }
    // Only pass through known fields; the customer ID comes from the token, never the body.
    const config: GenerationConfig = {
        prompt: body.prompt.trim(),
        isMotion: body.isMotion === true,
        model: typeof body.model === 'string' && body.model ? body.model : undefined,
        width: Number.isFinite(body.width) ? body.width : undefined,
        height: Number.isFinite(body.height) ? body.height : undefined,
        aspectRatio: typeof body.aspectRatio === 'string' ? body.aspectRatio : undefined,
        duration: Number.isFinite(body.duration) ? body.duration : undefined,
        resolution: typeof body.resolution === 'string' ? body.resolution : undefined,
        customerId,
    };
    const result = await engine.generateAsset(config);
    sendJson(res, result.success ? 200 : 422, result, CORS);
}

const LANDING = `<!doctype html><meta charset="utf-8"><title>GOAT CREATIONS</title>
<body style="background:#0b0c0f;color:#e7e9ec;font-family:system-ui;padding:48px">
<h1 style="letter-spacing:.12em"><span style="color:#f2b82e">GOAT</span> CREATIONS</h1>
<p>The Greatest of All Time Open-Source Creative Suite. SEBastina server is running.</p></body>`;

// ---------------------------------------------------------------- routes
const server = http.createServer(async (req, res) => {
    try {
        const path = new URL(req.url ?? '/', 'http://x').pathname;

        if (req.method === 'OPTIONS') {
            res.writeHead(204, CORS);
            return res.end();
        }
        if (path === '/health') return sendJson(res, 200, { ok: true, billing: billingOn }, CORS);
        if (path === '/api/models') return sendJson(res, 200, { models: allowedModels }, CORS);
        if (path === '/api/generate') {
            if (req.method !== 'POST') return sendJson(res, 405, { error: 'Use POST.' }, CORS);
            return await handleGenerate(req, res);
        }

        // Everything else is content: AI crawlers pay first.
        paywall(req, res, async () => {
            try {
                if (path === '/') {
                    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
                    return res.end(LANDING);
                }
                const file = path.startsWith('/data/') ? dataPath(path) : null;
                if (!file || !(await fs.stat(file).catch(() => null))?.isFile()) {
                    return sendJson(res, 404, { error: 'Not found.' });
                }
                await streamAsset(res, file);
            } catch (error) {
                console.error('[server] asset error', error);
                if (!res.headersSent) sendJson(res, 500, { error: 'Server error.' });
                else res.destroy();
            }
        });
    } catch (error) {
        console.error('[server] request error', error);
        if (!res.headersSent) sendJson(res, 500, { error: 'Server error.' });
    }
});

server.listen(PORT, () => {
    console.log(`[server] SEBastina listening on http://127.0.0.1:${PORT} (billing ${billingOn ? 'on' : 'OFF'})`);
    console.log(`[server] data assets from ${join(DATA_DIR)}`);
});
