// Hugging Face backend (GOATAIEngineHub, generateFluxAsset) against a stand-in for the
// HF router and fal.ai's queue, the flow the real client uses. No real token or credit.
import assert from 'node:assert/strict';
import { createGOATAIEngineHub, generateFluxAsset, generateWanVideo, SEBastinaEngine, FLUX_SCHNELL_MODEL } from '../dist/index.js';

const json = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { 'content-type': 'application/json' } });
const calls = [];
let submitStatus = 200;
const standIn = async (url, init = {}) => {
  const u = String(url);
  const headers = init.headers instanceof Headers ? Object.fromEntries(init.headers) : (init.headers ?? {});
  calls.push({ method: init.method ?? 'GET', url: u, auth: headers.Authorization ?? headers.authorization, body: typeof init.body === 'string' ? JSON.parse(init.body) : undefined });
  if (u.startsWith('https://huggingface.co/api/whoami-v2')) return headers.Authorization === 'Bearer hf_good' ? json({ name: 'sebthegoatt' }) : json({ error: 'bad' }, 401);
  if (u.includes('?expand')) {
    const flux = u.includes('FLUX');
    return json({ inferenceProviderMapping: { 'fal-ai': { status: 'live', task: flux ? 'text-to-image' : 'text-to-video', providerId: flux ? 'fal-ai/flux/schnell' : 'fal-ai/wan-t2v' } } });
  }
  if (init.method === 'POST' && u.includes('_subdomain=queue')) {
    if (submitStatus !== 200) return json({ error: 'nope' }, submitStatus);
    const model = u.includes('flux') ? 'fal-ai/flux/schnell' : 'fal-ai/wan-t2v';
    return json({ request_id: 'r1', status_url: `https://queue.fal.run/${model}/requests/r1/status`, response_url: `https://queue.fal.run/${model}/requests/r1` });
  }
  if (u.includes('/status')) return json({ status: 'COMPLETED' });
  if (u.includes('/requests/r1')) return u.includes('flux') ? json({ images: [{ url: 'https://v3.fal.media/files/goat.jpg' }] }) : json({ video: { url: 'https://v3.fal.media/files/goat.mp4' } });
  if (u.endsWith('goat.jpg')) return new Response(new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 7]), { headers: { 'content-type': 'image/jpeg' } });
  if (u.endsWith('goat.mp4')) return new Response(new Uint8Array([0, 0, 0, 24, 102, 116, 121, 112]), { headers: { 'content-type': 'video/mp4' } });
  return json({ error: `unexpected ${u}` }, 404);
};
// The HF client polls fal's queue with the global fetch, so stand in for both.
globalThis.fetch = standIn;
const quiet = console.log; console.log = (...a) => { if (!String(a[0]).startsWith('Auto selected') && !String(a[0]).startsWith('[GOAT AI HUB]')) quiet(...a); };

// generateFluxAsset: prompt straight to FLUX.1 Schnell, blob + data URL back.
const asset = await generateFluxAsset('a goat on a mountain', { token: 'hf_good', fetch: standIn, width: 1000, height: 560 });
assert.equal(asset.model, FLUX_SCHNELL_MODEL);
assert.equal(asset.mimeType, 'image/jpeg');
assert.equal(asset.blob.size, 5);
assert.equal(asset.dataUrl, 'data:image/jpeg;base64,/9j/4Ac=');
const submit = calls.find((c) => c.method === 'POST' && c.url.includes('flux'));
assert.equal(submit.url, 'https://router.huggingface.co/fal-ai/fal-ai/flux/schnell?_subdomain=queue');
assert.equal(submit.auth, 'Bearer hf_good');
assert.deepEqual(submit.body, { width: 1008, height: 560, num_inference_steps: 4, prompt: 'a goat on a mountain' });
console.log('PASS 1  generateFluxAsset: your prompt -> FLUX.1 Schnell (4 steps, 16-px grid) -> image blob + data: URL');

// GOATAIEngineHub API, as the apps call it.
const hub = createGOATAIEngineHub({ token: 'hf_good', fetch: standIn });
assert.match(await hub.textToImage('a goat', 512, 512), /^data:image\/jpeg;base64,/);
const video = await hub.textToVideo('a goat running');
assert.match(video.videoUrl, /^data:video\/mp4;base64,/);
assert.equal(video.blob.type, 'video/mp4');
assert.equal(calls.filter((c) => c.method === 'POST' && c.url.includes('wan-t2v'))[0].body.num_frames, 81);
console.log('PASS 2  GOATAIEngineHub.textToImage / textToVideo (Wan 2.1, 81 frames) return data: URLs the apps can show');

// Errors people hit.
const saved = process.env.HF_ACCESS_TOKEN; delete process.env.HF_ACCESS_TOKEN;
await assert.rejects(generateFluxAsset('a goat'), /No Hugging Face token/);
await assert.rejects(generateFluxAsset('   ', { token: 'hf_good' }), /Prompt cannot be empty/);
submitStatus = 402;
await assert.rejects(generateFluxAsset('a goat', { token: 'hf_good', fetch: standIn }), /credit is used up/);
submitStatus = 200;
if (saved) process.env.HF_ACCESS_TOKEN = saved;
console.log('PASS 3  missing token, empty prompt, out of credit: plain messages');

// Engine backend "huggingface": the apps' Generate button and text-only Skills.
const engine = new SEBastinaEngine({ backend: 'huggingface', hfToken: 'hf_good' });
assert.deepEqual(await engine.checkKey(), { ok: true, device: 'Hugging Face account sebthegoatt' });
assert.match((await new SEBastinaEngine({ backend: 'huggingface', hfToken: 'hf_bad' }).checkKey()).error, /rejected the token/);
let r = await engine.generateAsset({ prompt: 'a goat', aspectRatio: '16:9' });
assert.equal(r.success, true); assert.match(r.data, /^data:image\/jpeg/);
const lastFlux = calls.filter((c) => c.method === 'POST' && c.url.includes('flux')).at(-1);
assert.deepEqual([lastFlux.body.width, lastFlux.body.height], [1360, 768]);
r = await engine.runSkill({ skillId: 'logo', inputs: { name: 'GOAT' } });
assert.equal(r.success, true, r.error);
r = await engine.runSkill({ skillId: 'drone-video', inputs: { place: 'a valley' } });
assert.equal(r.success, true); assert.equal(r.kind, 'video');
assert.match((await engine.runSkill({ skillId: 'product-ad-video', photoUrl: 'x' })).error, /needs MuAPI or your own computer/);
await assert.rejects(engine.uploadImage(new Blob(['x'])), /Photo tools need MuAPI/);
assert.match((await engine.runSkill({ skillId: 'design-character', inputs: { look: 'naked' } })).error, /fully clothed/);
console.log('PASS 4  engine on Hugging Face: token check, Generate, text Skills and video; photo Skills say what they need; SEBastina rules hold');

console.log = quiet;
console.log('\nAll Hugging Face checks passed.');
