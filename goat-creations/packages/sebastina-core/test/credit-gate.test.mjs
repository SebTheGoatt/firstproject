// Stand-in MuAPI + Lago server, then exercise SEBastina's credit gate end to end.
import http from 'node:http';
import assert from 'node:assert/strict';

// Run with `npm test` (builds first). Uses a local stand-in server: no real keys or network.
import { SEBastinaEngine, lagoCreditGate, LagoBilling } from '../dist/server.js';

const customers = {
  'goat-pro':    { active: true,  wallet: { lago_id: 'w-pro', credits: 3 } },
  'goat-broke':  { active: true,  wallet: { lago_id: 'w-broke', credits: 0 } },
  'goat-lapsed': { active: false, wallet: { lago_id: 'w-lapsed', credits: 10 } },
};
const log = [];
const polls = {};

const server = http.createServer((req, res) => {
  let body = '';
  req.on('data', (c) => (body += c));
  req.on('end', () => {
    const url = new URL(req.url, 'http://x');
    const json = (code, obj) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(obj)); };
    const parsed = body ? JSON.parse(body) : undefined;
    log.push({ method: req.method, path: url.pathname, query: url.search, body: parsed, auth: req.headers.authorization, key: req.headers['x-api-key'] });

    // ---- Lago
    if (url.pathname === '/api/v1/subscriptions') {
      const c = customers[url.searchParams.get('external_customer_id')];
      const wantActive = url.searchParams.getAll('status[]').includes('active');
      const subs = c && c.active ? [{ status: 'active', plan_code: 'creator' }] : [];
      return json(200, { subscriptions: wantActive ? subs : subs, meta: {} });
    }
    if (url.pathname === '/api/v1/wallets') {
      const c = customers[url.searchParams.get('external_customer_id')];
      const wallets = c ? [{ lago_id: c.wallet.lago_id, status: 'active', credits_balance: c.wallet.credits.toFixed(2) }] : [];
      return json(200, { wallets, meta: {} });
    }
    if (url.pathname === '/api/v1/wallet_transactions' && req.method === 'POST') {
      const t = parsed.wallet_transaction;
      const c = Object.values(customers).find((x) => x.wallet.lago_id === t.wallet_id);
      c.wallet.credits += Number(t.granted_credits || 0) - Number(t.voided_credits || 0);
      return json(200, { wallet_transactions: [{ lago_id: 'tx', wallet_id: t.wallet_id }] });
    }
    // ---- MuAPI
    if (req.headers['x-api-key'] !== 'test-muapi-key') return json(401, { detail: 'bad key' });
    if (url.pathname === '/api/v1/flux-dev-image') return json(200, { request_id: 'img-1' });
    if (url.pathname === '/api/v1/seedance-lite-t2v') return json(200, { request_id: 'vid-fail' });
    const m = url.pathname.match(/^\/api\/v1\/predictions\/(.+)\/result$/);
    if (m) {
      polls[m[1]] = (polls[m[1]] || 0) + 1;
      if (m[1] === 'vid-fail') return json(200, { status: 'failed', error: 'model overloaded' });
      if (polls[m[1]] < 2) return json(200, { status: 'processing' });
      return json(200, { status: 'completed', outputs: ['https://cdn.example/goat.png'] });
    }
    json(404, { detail: 'not found' });
  });
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));

const base = `http://127.0.0.1:${server.address().port}`;
const billing = new LagoBilling('test-lago-key', `${base}/api/v1`);
const engine = new SEBastinaEngine({ apiBaseUrl: base, apiKey: 'test-muapi-key', pollIntervalMs: 10 })
  .use(lagoCreditGate(billing));
const muapiCalls = () => log.filter((l) => !['/api/v1/subscriptions', '/api/v1/wallets', '/api/v1/wallet_transactions'].includes(l.path));

// 1. Paid-up customer: image succeeds, 1 credit taken, Flux payload matches MuAPI's format.
let r = await engine.generateAsset({ prompt: 'a golden goat', customerId: 'goat-pro', width: 1000, height: 700 });
assert.deepEqual(r, { success: true, data: 'https://cdn.example/goat.png' });
assert.equal(customers['goat-pro'].wallet.credits, 2);
const submit = log.find((l) => l.path === '/api/v1/flux-dev-image');
assert.deepEqual(submit.body, { prompt: 'a golden goat', width: 1024, height: 704, num_images: 1 });
assert.equal(submit.key, 'test-muapi-key');
const subQuery = log.find((l) => l.path === '/api/v1/subscriptions');
assert.match(decodeURIComponent(subQuery.query), /external_customer_id=goat-pro/);
assert.match(decodeURIComponent(subQuery.query), /status\[\]=active/);
assert.equal(subQuery.auth, 'Bearer test-lago-key');
const debit = log.find((l) => l.path === '/api/v1/wallet_transactions');
assert.deepEqual(debit.body.wallet_transaction, { wallet_id: 'w-pro', voided_credits: '1.00', name: 'ImageGOAT generation' });
console.log('PASS 1  active subscription + credits -> image generated, 3 -> 2 credits, Flux payload correct');

// 2. Video fails at the provider: credit refunded, video payload correct.
r = await engine.generateAsset({ prompt: 'goat running', customerId: 'goat-pro', isMotion: true });
assert.equal(r.success, false);
assert.match(r.error, /model overloaded.*1 credit\(s\) refunded/);
assert.equal(customers['goat-pro'].wallet.credits, 2);
assert.deepEqual(log.find((l) => l.path === '/api/v1/seedance-lite-t2v').body,
  { prompt: 'goat running', aspect_ratio: '16:9', duration: 5, resolution: '480p' });
console.log('PASS 2  failed video -> credit refunded (still 2), Seedance payload correct');

// 3. Out of credits: refused, MuAPI never called.
let before = muapiCalls().length;
r = await engine.generateAsset({ prompt: 'x', customerId: 'goat-broke' });
assert.equal(r.success, false); assert.match(r.error, /Not enough credits: 0 left/);
assert.equal(muapiCalls().length, before);
console.log('PASS 3  zero credits -> refused before generation:', r.error);

// 4. No active subscription (even with credits): refused, nothing debited.
before = muapiCalls().length;
r = await engine.generateAsset({ prompt: 'x', customerId: 'goat-lapsed' });
assert.equal(r.success, false); assert.match(r.error, /No active subscription/);
assert.equal(customers['goat-lapsed'].wallet.credits, 10);
assert.equal(muapiCalls().length, before);
console.log('PASS 4  lapsed subscription -> refused, credits untouched:', r.error);

// 5. No customer ID: refused.
r = await engine.generateAsset({ prompt: 'x' });
assert.match(r.error, /No customer ID/);
console.log('PASS 5  missing customer ID -> refused');

// 6. Lago unreachable: fails closed (no free generation).
const down = new SEBastinaEngine({ apiBaseUrl: base, apiKey: 'test-muapi-key', pollIntervalMs: 10 })
  .use(lagoCreditGate(new LagoBilling('k', 'http://127.0.0.1:9/api/v1')));
before = muapiCalls().length;
r = await down.generateAsset({ prompt: 'x', customerId: 'goat-pro' });
assert.equal(r.success, false); assert.equal(muapiCalls().length, before);
console.log('PASS 6  billing server down -> refused (fails closed):', r.error);

server.close();
console.log('\nAll credit-gate checks passed.');
