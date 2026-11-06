// Skills: templates, chaining, photo upload and per-step billing, against a stand-in MuAPI + Lago.
import http from 'node:http';
import assert from 'node:assert/strict';
import { SKILLS, findSkill, renderPrompt, skillCredits, skillOutput, findModel } from '../dist/index.js';
import { SEBastinaEngine, LagoBilling, lagoCreditGate } from '../dist/server.js';

// ---- catalog sanity: every step uses a catalog model; photo Skills start from the photo
for (const skill of SKILLS) {
  for (const [i, step] of skill.steps.entries()) {
    const spec = findModel(step.model);
    assert.ok(spec, `${skill.id}: unknown model ${step.model}`);
    if (spec.imageField) assert.ok(step.from === 'photo' || (step.from === 'previous' && i > 0), `${skill.id} step ${i + 1} needs a picture source`);
    else assert.equal(step.from, undefined, `${skill.id} step ${i + 1}: text model given a picture`);
  }
  assert.equal(skill.needsPhoto, skill.steps.some((s) => s.from === 'photo'), `${skill.id}: needsPhoto mismatch`);
}
assert.equal(SKILLS.filter((s) => s.category === 'create').length, 8);
assert.equal(SKILLS.filter((s) => s.category === 'photo').length, 4);
console.log('PASS 1  catalog: 8 Skills + 4 photo tools, every step wired to a known model and picture source');

// ---- templates
const thumb = findSkill('youtube-thumbnail');
const r = renderPrompt(thumb.steps[0].prompt, thumb, { subject: 'a goat on a peak', headline: 'GOAT MODE' });
assert.match(r.prompt, /a goat on a peak/); assert.match(r.prompt, /"GOAT MODE"/); assert.doesNotMatch(r.prompt, /\{/);
assert.equal(renderPrompt(thumb.steps[0].prompt, thumb, { subject: 'x' }).missing.label, 'Headline text');
const logo = findSkill('logo');
assert.match(renderPrompt(logo.steps[0].prompt, logo, { name: 'GOAT' }).prompt, /simple geometric mark/);
assert.equal(skillCredits(findSkill('product-ad-video'), { image: 1, video: 3 }), 4);
assert.equal(skillOutput(findSkill('product-ad-video')), 'video');
assert.equal(skillOutput(findSkill('upscale-photo')), 'image');
console.log('PASS 2  templates fill your words, use fallbacks, flag missing fields; credits counted per step');

// ---- stand-in MuAPI + Lago
const calls = [];
let failModel = null;
let credits = 10;
const server = http.createServer((req, res) => {
  const chunks = [];
  req.on('data', (c) => chunks.push(c));
  req.on('end', async () => {
    const json = (o, code = 200) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(o)); };
    const url = new URL(req.url, 'http://x');
    const raw = Buffer.concat(chunks);
    if (url.pathname === '/lago/api/v1/subscriptions') return json({ subscriptions: [{ status: 'active' }], meta: {} });
    if (url.pathname === '/lago/api/v1/wallets') return json({ wallets: [{ lago_id: 'w', status: 'active', credits_balance: String(credits) }], meta: {} });
    if (url.pathname === '/lago/api/v1/wallet_transactions') {
      const t = JSON.parse(raw).wallet_transaction;
      credits += Number(t.granted_credits || 0) - Number(t.voided_credits || 0);
      return json({ wallet_transactions: [{}] });
    }
    if (url.pathname === '/api/v1/upload_file') {
      const form = await new Response(raw, { headers: { 'content-type': req.headers['content-type'] } }).formData();
      const file = form.get('file');
      calls.push({ upload: file.name, size: file.size, type: file.type });
      return json({ url: 'https://cdn.muapi.ai/uploads/photo.jpg' });
    }
    const m = url.pathname.match(/^\/api\/v1\/predictions\/(.+)\/result$/);
    if (m) {
      const id = m[1];
      if (id === `job-${failModel}`) return json({ status: 'failed', error: 'model overloaded' }, 400);
      const ext = id.includes('i2v') || id.includes('video') || id.includes('t2v') ? 'mp4' : 'png';
      return json({ status: 'completed', outputs: [`https://cdn.muapi.ai/out/${id}.${ext}`] });
    }
    const model = url.pathname.replace('/api/v1/', '');
    calls.push({ model, body: JSON.parse(raw) });
    json({ request_id: `job-${model}` });
  });
});
await new Promise((ok) => server.listen(0, '127.0.0.1', ok));
const base = `http://127.0.0.1:${server.address().port}`;
const engine = new SEBastinaEngine({ apiBaseUrl: base, apiKey: 'k', pollIntervalMs: 5 });

// Upload (Blob path, as browsers / Node use).
const photoUrl = await engine.uploadImage(new Blob([Buffer.from('fake-jpeg-bytes')], { type: 'image/jpeg' }), 'me.jpg');
assert.equal(photoUrl, 'https://cdn.muapi.ai/uploads/photo.jpg');
assert.deepEqual(calls.pop(), { upload: 'me.jpg', size: 15, type: 'image/jpeg' });
console.log('PASS 3  photo upload: multipart "file" to /upload_file, URL returned');

// Two-step chain: photo -> re-staged product -> video, step 1's result feeds step 2.
let result = await engine.runSkill({ skillId: 'product-ad-video', inputs: {}, photoUrl });
assert.equal(result.success, true, result.error);
assert.equal(result.kind, 'video');
assert.deepEqual(result.outputs, ['https://cdn.muapi.ai/out/job-flux-2-pro-edit.png', 'https://cdn.muapi.ai/out/job-wan2.5-image-to-video.mp4']);
const [s1, s2] = calls.splice(0);
assert.equal(s1.model, 'flux-2-pro-edit');
assert.deepEqual(s1.body.images_list, [photoUrl]);
assert.equal(s1.body.aspect_ratio, 'auto');
assert.match(s1.body.prompt, /polished dark surface with dramatic rim light/);
assert.equal(s2.model, 'wan2.5-image-to-video');
assert.equal(s2.body.image_url, result.outputs[0]);
assert.deepEqual([s2.body.duration, s2.body.resolution], [5, '720p']);
console.log('PASS 4  Product Ad Video: photo -> FLUX.2 edit -> Wan 2.5 video, step 1 output fed into step 2');

// Text Skill with user's words; photo tool without prompt.
result = await engine.runSkill({ skillId: 'youtube-thumbnail', inputs: { subject: 'a goat', headline: 'GOAT MODE' } });
assert.equal(result.kind, 'image');
let call = calls.pop();
assert.equal(call.model, 'gpt-image-2-text-to-image');
assert.deepEqual([call.body.aspect_ratio, call.body.resolution], ['16:9', '2K']);
result = await engine.runSkill({ skillId: 'remove-background', photoUrl });
call = calls.pop();
assert.deepEqual(call, { model: 'ai-background-remover', body: { image_url: photoUrl } });
console.log('PASS 5  text Skill sends your headline; photo tool sends only the photo');

// Refusals before any spending.
assert.match((await engine.runSkill({ skillId: 'action-figure' })).error, /needs a photo/);
assert.match((await engine.runSkill({ skillId: 'logo', inputs: {} })).error, /Fill in "Brand name"/);
assert.match((await engine.runSkill({ skillId: 'nope' })).error, /Unknown Skill/);
const strict = new SEBastinaEngine({ apiBaseUrl: base, apiKey: 'k', pollIntervalMs: 5, allowedSkills: ['logo'] });
assert.match((await strict.runSkill({ skillId: 'drone-video', inputs: { place: 'x' } })).error, /isn't offered/);
assert.equal(calls.length, 0);
console.log('PASS 6  missing photo / field, unknown or not-offered Skill: refused, nothing sent to MuAPI');

// Billing: one debit for all steps; refund if a later step fails.
const billed = new SEBastinaEngine({ apiBaseUrl: base, apiKey: 'k', pollIntervalMs: 5 })
  .use(lagoCreditGate(new LagoBilling('lk', `${base}/lago/api/v1`), { image: 1, video: 3 }));
result = await billed.runSkill({ skillId: 'product-ad-video', photoUrl, customerId: 'c1' });
assert.equal(result.success, true); assert.equal(credits, 6);
failModel = 'wan2.5-image-to-video';
result = await billed.runSkill({ skillId: 'product-ad-video', photoUrl, customerId: 'c1' });
assert.equal(result.success, false);
assert.match(result.error, /model overloaded \(step 2 of 2\).*4 credit\(s\) refunded/);
assert.equal(credits, 6);
console.log('PASS 7  Lago: 2-step video Skill charges 4 (1 image + 3 video) once; step 2 failure refunds all 4');

server.close();
console.log('\nAll Skill checks passed.');
