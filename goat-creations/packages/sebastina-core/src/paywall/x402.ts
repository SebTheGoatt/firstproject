/**
 * AI-crawler paywall using the x402 standard (HTTP 402 + USDC, github.com/x402-foundation/x402).
 *
 * People and ordinary bots pass straight through. Requests whose User-Agent
 * names a known AI crawler get:
 *   1. HTTP 402 Payment Required, no content,
 *   2. a JSON body describing the fee (default 0.001 USDC on Base) in x402 format,
 *   3. on retry with a signed payment (X-PAYMENT header, or `Authorization: x402 <payload>`):
 *      the payment is verified and settled through an x402 facilitator, then the
 *      request continues to the asset handler, which streams the file.
 *      Missing, malformed or invalid payments get a 402 and the connection is closed.
 *
 * Works as Express / Connect middleware or with plain node:http (see `streamAsset`).
 */
import type { IncomingMessage, ServerResponse } from 'node:http';
import { createReadStream, promises as fs } from 'node:fs';
import { extname } from 'node:path';

/** User-Agent tokens of AI crawlers that gather training or answer data. */
export const DEFAULT_AI_CRAWLERS = [
    'GPTBot',
    'ClaudeBot',
    'Claude-Web',
    'anthropic-ai',
    'PerplexityBot',
    'CCBot',
    'Bytespider',
    'meta-externalagent',
    'cohere-ai',
];

/** USDC contracts and their EIP-712 names (from the x402 reference implementation). */
const USDC = {
    base: { asset: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913', name: 'USD Coin' },
    'base-sepolia': { asset: '0x036CbD53842c5426634e7929541eC2318f3dCF7e', name: 'USDC' },
} as const;

export type PaywallNetwork = keyof typeof USDC;

export interface CrawlerPaywallOptions {
    /** Wallet address that receives the fees (0x…). Required. */
    payTo: string;
    /** `base-sepolia` (test money, default) or `base` (real USDC). */
    network?: PaywallNetwork;
    /** Fee per request in USDC, as a decimal string. Default "0.001". */
    priceUsdc?: string;
    /** x402 facilitator that checks and settles payments. Default: the public test facilitator. */
    facilitatorUrl?: string;
    /** Extra headers for the facilitator (a mainnet facilitator needs an API key). */
    facilitatorHeaders?: () => Promise<Record<string, string>> | Record<string, string>;
    /** User-Agent tokens to charge (case-insensitive). Default: DEFAULT_AI_CRAWLERS. */
    crawlers?: string[];
    description?: string;
    /** Seconds the signed payment stays valid. Default 60. */
    maxTimeoutSeconds?: number;
    /** Public origin used in the `resource` URL, e.g. https://goatcreations.app. Default: from the Host header. */
    publicOrigin?: string;
    fetchImpl?: typeof fetch;
}

export interface PaymentRequirements {
    scheme: 'exact';
    network: PaywallNetwork;
    maxAmountRequired: string;
    resource: string;
    description: string;
    mimeType: string;
    payTo: string;
    maxTimeoutSeconds: number;
    asset: string;
    extra: { name: string; version: string };
}

type Next = (error?: unknown) => void;
export type Middleware = (req: IncomingMessage, res: ServerResponse, next: Next) => void;

const X402_VERSION = 1;
const USDC_DECIMALS = 6;

/** Convert "0.001" USDC to atomic units ("1000"), without floating-point error. */
export function usdcToAtomic(amount: string): string {
    const match = /^(\d+)(?:\.(\d+))?$/.exec(amount.trim());
    if (!match) throw new Error(`Invalid USDC amount: ${amount}`);
    const fraction = (match[2] ?? '').padEnd(USDC_DECIMALS, '0');
    if (fraction.length > USDC_DECIMALS) throw new Error(`USDC has ${USDC_DECIMALS} decimals at most: ${amount}`);
    const atomic = BigInt(match[1]) * 10n ** BigInt(USDC_DECIMALS) + BigInt(fraction || '0');
    if (atomic <= 0n) throw new Error('The fee must be more than zero.');
    return atomic.toString();
}

export function isAiCrawler(userAgent: string | undefined, crawlers: string[] = DEFAULT_AI_CRAWLERS): boolean {
    if (!userAgent) return false;
    const ua = userAgent.toLowerCase();
    return crawlers.some((token) => ua.includes(token.toLowerCase()));
}

/** The signed payment from `X-PAYMENT`, or `Authorization: x402 <payload>`. */
function readPaymentHeader(req: IncomingMessage): string | undefined {
    const xPayment = req.headers['x-payment'];
    if (typeof xPayment === 'string' && xPayment.trim()) return xPayment.trim();
    const auth = req.headers.authorization;
    const match = auth && /^x402\s+(.+)$/i.exec(auth.trim());
    return match ? match[1] : undefined;
}

function decodePayment(header: string): any {
    const json = Buffer.from(header, 'base64').toString('utf8');
    const payment = JSON.parse(json);
    if (!payment || typeof payment !== 'object' || !payment.payload) throw new Error('missing payload');
    return payment;
}

export function crawlerPaywall(options: CrawlerPaywallOptions): Middleware {
    if (!/^0x[0-9a-fA-F]{40}$/.test(options.payTo || '')) {
        throw new Error('crawlerPaywall: payTo must be your wallet address (0x followed by 40 hex characters).');
    }
    const network = options.network ?? 'base-sepolia';
    const usdc = USDC[network];
    if (!usdc) throw new Error(`crawlerPaywall: unsupported network ${network}`);
    const amount = usdcToAtomic(options.priceUsdc ?? '0.001');
    const facilitator = (options.facilitatorUrl ?? 'https://x402.org/facilitator').replace(/\/+$/, '');
    const crawlers = options.crawlers ?? DEFAULT_AI_CRAWLERS;
    const doFetch = options.fetchImpl ?? fetch;

    const requirementsFor = (req: IncomingMessage): PaymentRequirements => {
        const origin = options.publicOrigin ?? `http://${req.headers.host ?? 'localhost'}`;
        return {
            scheme: 'exact',
            network,
            maxAmountRequired: amount,
            resource: new URL(req.url ?? '/', origin).toString(),
            description: options.description ?? 'Access fee for AI crawlers (GOAT CREATIONS data asset)',
            mimeType: mimeTypeFor(req.url ?? ''),
            payTo: options.payTo,
            maxTimeoutSeconds: options.maxTimeoutSeconds ?? 60,
            asset: usdc.asset,
            extra: { name: usdc.name, version: '2' },
        };
    };

    /** Reply 402 with the fee details; `close` also ends the connection. */
    const paymentRequired = (res: ServerResponse, requirements: PaymentRequirements, error: string, close: boolean) => {
        const body = JSON.stringify({ x402Version: X402_VERSION, error, accepts: [requirements] });
        res.writeHead(402, {
            'Content-Type': 'application/json',
            'Content-Length': Buffer.byteLength(body),
            'Cache-Control': 'no-store',
            ...(close ? { Connection: 'close' } : {}),
        });
        res.end(body);
    };

    const callFacilitator = async (path: 'verify' | 'settle', payment: any, requirements: PaymentRequirements) => {
        const extra = options.facilitatorHeaders ? await options.facilitatorHeaders() : {};
        const response = await doFetch(`${facilitator}/${path}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...extra },
            body: JSON.stringify({ x402Version: payment.x402Version ?? X402_VERSION, paymentPayload: payment, paymentRequirements: requirements }),
        });
        return { status: response.status, data: (await response.json().catch(() => ({}))) as any };
    };

    return (req, res, next) => {
        if (!isAiCrawler(req.headers['user-agent'], crawlers)) return next();

        const requirements = requirementsFor(req);
        const header = readPaymentHeader(req);
        if (!header) {
            // Step 1 + 2: no content, just the price list.
            return paymentRequired(res, requirements, 'Payment required: AI crawlers pay per request. Send a signed x402 payment in the X-PAYMENT header.', false);
        }

        // Step 3: check the signature and settle, then let the asset stream.
        (async () => {
            let payment: any;
            try {
                payment = decodePayment(header);
            } catch {
                return paymentRequired(res, requirements, 'Malformed payment header.', true);
            }
            if (payment.scheme !== 'exact' || payment.network !== network) {
                return paymentRequired(res, requirements, `Payment must use scheme "exact" on ${network}.`, true);
            }

            const verified = await callFacilitator('verify', payment, requirements);
            if (verified.status !== 200 || verified.data?.isValid !== true) {
                return paymentRequired(res, requirements, `Invalid payment: ${verified.data?.invalidReason ?? 'signature rejected'}.`, true);
            }
            const settled = await callFacilitator('settle', payment, requirements);
            if (settled.status !== 200 || settled.data?.success !== true) {
                return paymentRequired(res, requirements, `Payment could not be settled: ${settled.data?.errorReason ?? 'unknown reason'}.`, true);
            }

            // Receipt for the payer, as in the x402 spec.
            res.setHeader('X-PAYMENT-RESPONSE', Buffer.from(JSON.stringify(settled.data)).toString('base64'));
            next();
        })().catch(() => {
            // Facilitator down or unreachable: never give the asset away.
            if (res.headersSent) return res.destroy();
            const body = JSON.stringify({ x402Version: X402_VERSION, error: 'Payment verification is unavailable. Try again later.' });
            res.writeHead(503, { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body), Connection: 'close' });
            res.end(body);
        });
    };
}

/** Stream a file to the response (the "data asset"), with its content type and length. */
export async function streamAsset(res: ServerResponse, filePath: string): Promise<void> {
    const stat = await fs.stat(filePath);
    res.writeHead(res.statusCode && res.statusCode !== 200 ? res.statusCode : 200, {
        'Content-Type': mimeTypeFor(filePath),
        'Content-Length': stat.size,
    });
    await new Promise<void>((resolve, reject) => {
        createReadStream(filePath).on('error', reject).on('end', resolve).pipe(res);
    });
}

const MIME: Record<string, string> = {
    '.json': 'application/json',
    '.txt': 'text/plain; charset=utf-8',
    '.md': 'text/markdown; charset=utf-8',
    '.html': 'text/html; charset=utf-8',
    '.csv': 'text/csv; charset=utf-8',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.mp4': 'video/mp4',
};

function mimeTypeFor(path: string): string {
    return MIME[extname(path.split('?')[0]).toLowerCase()] ?? 'application/octet-stream';
}
