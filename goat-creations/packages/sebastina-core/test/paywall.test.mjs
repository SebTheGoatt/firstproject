// AI-crawler paywall checks against a stand-in x402 facilitator. No real money or network.
import http from 'node:http';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { crawlerPaywall, streamAsset, usdcToAtomic, isAiCrawler } from '../dist/server.js';

const PAY_TO = '0x1111111111111111111111111111111111111111';
const listen = (server) => new Promise((r) => server.listen(0, '127.0.0.1', () => r(`http://127.0.0.1:${server.address().port}`)));

// --- unit checks
assert.equal(usdcToAtomic('0.001'), '1000');
assert.equal(usdcToAtomic('1'), '1000000');
assert.throws(() => usdcToAtomic('0.0000001'));
assert.throws(() => usdcToAtomic('0'));
assert.ok(isAiCrawler('Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)'));
assert.ok(isAiCrawler('Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)'));
assert.ok(isAiCrawler('Mozilla/5.0 (compatible; PerplexityBot/1.0)'));
assert.ok(!isAiCrawler('Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) Safari/605.1.15'));
assert.ok(!isAiCrawler(undefined));
assert.throws(() => crawlerPaywall({ payTo: 'not-a-wallet' }), /payTo/);
console.log('PASS 0  fee math, crawler detection, config checks');

// --- stand-in facilitator: accepts the payload whose signature is "0xgood"
const facilitatorCalls = [];
const facilitator = http.createServer((req, res) => {
  let body = '';
  req.on('data', (c) => (body += c));
  req.on('end', () => {
    const call = JSON.parse(body);
    facilitatorCalls.push({ path: req.url, call });
    const good = call.paymentPayload?.payload?.signature === '0xgood';
    res.setHeader('content-type', 'application/json');
    if (req.url === '/verify') return res.end(JSON.stringify(good ? { isValid: true, payer: '0xpayer' } : { isValid: false, invalidReason: 'invalid_exact_evm_payload_signature' }));
    if (req.url === '/settle') return res.end(JSON.stringify({ success: true, transaction: '0xtxhash', network: 'base-sepolia', payer: '0xpayer' }));
    res.statusCode = 404; res.end('{}');
  });
});
const facilitatorUrl = await listen(facilitator);

// --- the protected site: a data asset behind the paywall
const dir = mkdtempSync(join(tmpdir(), 'goat-asset-'));
const asset = join(dir, 'dataset.json');
const assetBody = JSON.stringify({ title: 'GOAT CREATIONS dataset', rows: Array.from({ length: 2000 }, (_, i) => ({ i })) });
writeFileSync(asset, assetBody);
const paywall = crawlerPaywall({ payTo: PAY_TO, facilitatorUrl });
const site = http.createServer((req, res) => paywall(req, res, () => streamAsset(res, asset)));
const siteUrl = await listen(site);

const GPTBOT = 'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)';
const payment = (signature) => Buffer.from(JSON.stringify({
  x402Version: 1, scheme: 'exact', network: 'base-sepolia',
  payload: { signature, authorization: { from: '0xpayer', to: PAY_TO, value: '1000', validAfter: '0', validBefore: '9999999999', nonce: '0x01' } },
})).toString('base64');

// 1. A person gets the asset for free.
let r = await fetch(`${siteUrl}/data/dataset.json`, { headers: { 'user-agent': 'Mozilla/5.0 Safari/605.1.15' } });
assert.equal(r.status, 200); assert.equal(await r.text(), assetBody);
console.log('PASS 1  normal visitor -> 200, asset delivered free');

// 2. GPTBot with no payment: 402, fee details, no content.
r = await fetch(`${siteUrl}/data/dataset.json`, { headers: { 'user-agent': GPTBOT } });
assert.equal(r.status, 402);
let body = await r.json();
assert.equal(body.x402Version, 1);
assert.deepEqual(body.accepts[0], {
  scheme: 'exact', network: 'base-sepolia', maxAmountRequired: '1000',
  resource: `${siteUrl}/data/dataset.json`,
  description: 'Access fee for AI crawlers (GOAT CREATIONS data asset)',
  mimeType: 'application/json', payTo: PAY_TO, maxTimeoutSeconds: 60,
  asset: '0x036CbD53842c5426634e7929541eC2318f3dCF7e', extra: { name: 'USDC', version: '2' },
});
assert.ok(!JSON.stringify(body).includes('GOAT CREATIONS dataset"'));
console.log('PASS 2  GPTBot, no payment -> 402 with x402 fee: 0.001 USDC (1000 atomic) on Base Sepolia');

// 3. ClaudeBot with a bad signature: 402 and the connection is closed. Asset never sent.
r = await fetch(`${siteUrl}/data/dataset.json`, { headers: { 'user-agent': 'ClaudeBot/1.0', 'x-payment': payment('0xforged') } });
assert.equal(r.status, 402);
assert.equal(r.headers.get('connection'), 'close');
body = await r.json();
assert.match(body.error, /invalid_exact_evm_payload_signature/);
assert.equal(facilitatorCalls.filter((c) => c.path === '/settle').length, 0);
console.log('PASS 3  ClaudeBot, forged signature -> 402, Connection: close, nothing settled');

// 4. Garbage payment header: closed without calling the facilitator.
const before = facilitatorCalls.length;
r = await fetch(`${siteUrl}/data/dataset.json`, { headers: { 'user-agent': 'PerplexityBot/1.0', 'x-payment': '%%%not-base64-json' } });
assert.equal(r.status, 402); assert.equal(r.headers.get('connection'), 'close');
assert.equal(facilitatorCalls.length, before);
console.log('PASS 4  PerplexityBot, malformed header -> 402, Connection: close');

// 5. PerplexityBot pays with a valid signature in the Authorization header: verified, settled, streamed.
r = await fetch(`${siteUrl}/data/dataset.json`, { headers: { 'user-agent': 'PerplexityBot/1.0', authorization: `x402 ${payment('0xgood')}` } });
assert.equal(r.status, 200);
assert.equal(await r.text(), assetBody);
const receipt = JSON.parse(Buffer.from(r.headers.get('x-payment-response'), 'base64').toString());
assert.equal(receipt.transaction, '0xtxhash');
const verifyCall = facilitatorCalls.find((c) => c.path === '/verify' && c.call.paymentPayload.payload.signature === '0xgood').call;
assert.equal(verifyCall.paymentRequirements.maxAmountRequired, '1000');
assert.equal(verifyCall.x402Version, 1);
console.log('PASS 5  PerplexityBot, valid payment -> verified, settled, asset streamed with X-PAYMENT-RESPONSE receipt');

// 6. Facilitator down: the asset stays locked (503).
facilitator.close();
const down = crawlerPaywall({ payTo: PAY_TO, facilitatorUrl: 'http://127.0.0.1:9' });
const site2 = http.createServer((req, res) => down(req, res, () => streamAsset(res, asset)));
const site2Url = await listen(site2);
r = await fetch(`${site2Url}/data/dataset.json`, { headers: { 'user-agent': GPTBOT, 'x-payment': payment('0xgood') } });
assert.equal(r.status, 503);
console.log('PASS 6  payment checker unreachable -> 503, asset not delivered');

site.close(); site2.close();
console.log('\nAll paywall checks passed.');
