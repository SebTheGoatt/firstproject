// Engine behaviour against a stand-in MuAPI: failures, plain-language errors, output shapes, model allowlist.
import http from 'node:http';
import assert from 'node:assert/strict';
import { SEBastinaEngine } from '../dist/index.js';

let scenario = 'ok';
const server = http.createServer((req, res) => {
  const json = (o, code = 200) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(o)); };
  if (req.method === 'POST') {
    if (scenario === 'badkey') return json({ detail: 'Invalid API key' }, 401);
    if (scenario === 'broke') return json({ detail: 'Insufficient credits' }, 402);
    if (scenario === 'busy') return json({ detail: 'Too many requests' }, 429);
    return json({ request_id: 'r1' });
  }
  // poll
  if (scenario === 'fail400') return json({ status: 'failed', error: { message: 'Prompt was flagged' } }, 400);
  if (scenario === 'videourl') return json({ status: 'completed', video_url: 'https://cdn.muapi.ai/v.mp4' });
  if (scenario === 'outputstr') return json({ status: 'completed', output: 'https://cdn.muapi.ai/o.png' });
  json({ status: 'completed', outputs: ['https://cdn.muapi.ai/a.png'] });
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;
const engine = new SEBastinaEngine({ apiBaseUrl: base, apiKey: 'k', pollIntervalMs: 5 });
const run = async (s, extra = {}) => { scenario = s; return engine.generateAsset({ prompt: 'goat', ...extra }); };

assert.deepEqual(await run('ok'), { success: true, data: 'https://cdn.muapi.ai/a.png' });
assert.deepEqual(await run('videourl', { isMotion: true }), { success: true, data: 'https://cdn.muapi.ai/v.mp4' });
assert.deepEqual(await run('outputstr'), { success: true, data: 'https://cdn.muapi.ai/o.png' });
console.log('PASS 1  result URL found in outputs[], video_url and output string');

assert.deepEqual(await run('fail400'), { success: false, error: 'Generation failed: Prompt was flagged' });
console.log('PASS 2  failed generation (HTTP 400 on poll) -> MuAPI\'s reason, not "HTTP 400"');

assert.match((await run('badkey')).error, /rejected the API key/);
assert.match((await run('broke')).error, /out of credit/);
assert.match((await run('busy')).error, /rate limited/);
console.log('PASS 3  401 / 402 / 429 -> plain-language messages');

const strict = new SEBastinaEngine({ apiBaseUrl: base, apiKey: 'k', pollIntervalMs: 5, allowedModels: ['flux-dev-image'] });
scenario = 'ok';
assert.equal((await strict.generateAsset({ prompt: 'goat' })).success, true);
assert.match((await strict.generateAsset({ prompt: 'goat', model: 'veo3-fast-text-to-video', isMotion: true })).error, /isn't offered/);
assert.match((await engine.generateAsset({ prompt: 'goat', model: '../../admin' })).error, /Invalid model/);
assert.match((await new SEBastinaEngine({}).generateAsset({ prompt: 'goat' })).error, /No MuAPI key/);
console.log('PASS 4  model allowlist enforced, odd model names refused, missing key explained');

server.close();
console.log('\nAll engine checks passed.');
