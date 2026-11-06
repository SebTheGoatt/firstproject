// Own-computer backend (ComfyUI) against a stand-in ComfyUI: workflows, chaining, profiles.
import http from 'node:http';
import assert from 'node:assert/strict';
import { SEBastinaEngine } from '../dist/index.js';

const queued = [];
let n = 0;
const server = http.createServer((req, res) => {
  const chunks = [];
  req.on('data', (c) => chunks.push(c));
  req.on('end', () => {
    const json = (o, code = 200) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(o)); };
    const url = new URL(req.url, 'http://x');
    if (url.pathname === '/system_stats') return json({ devices: [{ name: 'NVIDIA RTX 4090', type: 'cuda', vram_total: 25.7e9 }] });
    if (url.pathname === '/upload/image') return json({ name: 'me.jpg', subfolder: 'goat', type: 'input' });
    if (url.pathname === '/prompt') {
      const body = JSON.parse(Buffer.concat(chunks));
      const id = `p${++n}`;
      queued.push({ id, workflow: body.prompt });
      return json({ prompt_id: id, number: n, node_errors: {} });
    }
    const m = url.pathname.match(/^\/history\/(.+)$/);
    if (m) {
      const job = queued.find((q) => q.id === m[1]);
      const saver = Object.entries(job.workflow).find(([, node]) => /^Save/.test(node.class_type));
      const prefix = saver[1].inputs.filename_prefix;
      const ext = saver[1].class_type === 'SaveWEBM' ? 'webm' : 'png';
      return json({ [m[1]]: { status: { status_str: 'success', completed: true }, outputs: { [saver[0]]: { images: [{ filename: `${prefix}_${m[1]}.${ext}`, subfolder: '', type: 'output' }] } } } });
    }
    json({}, 404);
  });
});
await new Promise((ok) => server.listen(0, '127.0.0.1', ok));
const base = `http://127.0.0.1:${server.address().port}`;
const light = new SEBastinaEngine({ backend: 'comfyui', comfyUrl: base, localProfile: 'light', pollIntervalMs: 10 });
const full = new SEBastinaEngine({ backend: 'comfyui', comfyUrl: base, localProfile: 'full', pollIntervalMs: 10 });
const nodes = (wf) => Object.values(wf).map((x) => x.class_type);
const byType = (wf, type) => Object.values(wf).find((x) => x.class_type === type);

assert.deepEqual(await light.checkKey(), { ok: true, device: 'NVIDIA RTX 4090, 26 GB' });
const missing = await new SEBastinaEngine({ backend: 'comfyui' }).checkKey();
assert.match(missing.error, /My computer/);
console.log('PASS 1  connection check reports the GPU; missing address explained');

let r = await light.generateAsset({ prompt: 'a goat', aspectRatio: '16:9' });
assert.equal(r.success, true, r.error);
assert.equal(r.data, `${base}/view?filename=goat_p1.png&subfolder=&type=output`);
let wf = queued.at(-1).workflow;
assert.equal(byType(wf, 'CheckpointLoaderSimple').inputs.ckpt_name, 'v1-5-pruned-emaonly-fp16.safetensors');
assert.deepEqual([byType(wf, 'EmptyLatentImage').inputs.width, byType(wf, 'EmptyLatentImage').inputs.height], [704, 384]);
r = await full.generateAsset({ prompt: 'a goat' });
wf = queued.at(-1).workflow;
assert.equal(byType(wf, 'CheckpointLoaderSimple').inputs.ckpt_name, 'flux1-schnell-fp8.safetensors');
assert.deepEqual([byType(wf, 'KSampler').inputs.steps, byType(wf, 'KSampler').inputs.cfg], [4, 1]);
console.log('PASS 2  text -> image: SD 1.5 (light, 512-class sizes) or FLUX.1 Schnell (full, 4 steps)');

const photo = await full.uploadImage(new Blob([Buffer.from('jpeg')], { type: 'image/jpeg' }), 'me.jpg');
assert.equal(photo, `${base}/view?filename=me.jpg&subfolder=goat&type=input`);
r = await full.runSkill({ skillId: 'product-ad-video', photoUrl: photo });
assert.equal(r.success, true, r.error);
const [edit, video] = queued.slice(-2).map((q) => q.workflow);
assert.ok(nodes(edit).includes('TextEncodeQwenImageEdit'));
assert.equal(byType(edit, 'LoadImage').inputs.image, 'goat/me.jpg [input]');
assert.ok(nodes(video).includes('Wan22ImageToVideoLatent'));
assert.equal(byType(video, 'LoadImage').inputs.image, `goat_edit_${queued.at(-2).id}.png [output]`);
assert.equal(byType(video, 'Wan22ImageToVideoLatent').inputs.length, 121);
assert.match(r.data, /goat_video_.*\.webm/);
console.log('PASS 3  Product Ad Video on full: Qwen edit of your photo, then Wan 2.2 animates that result ([output] chaining)');

r = await light.runSkill({ skillId: 'remove-background', photoUrl: photo });
assert.ok(nodes(queued.at(-1).workflow).includes('GOATRemoveBackgroundLocal'));
r = await light.runSkill({ skillId: 'upscale-photo', photoUrl: photo });
assert.ok(nodes(queued.at(-1).workflow).includes('ImageUpscaleWithModel'));
console.log('PASS 4  photo tools on light: BiRefNet cut-out (GOAT node) and Real-ESRGAN upscale');

const before = queued.length;
assert.match((await light.runSkill({ skillId: 'drone-video', inputs: { place: 'x' } })).error, /Full or Pro local setup/);
assert.match((await light.runSkill({ skillId: 'restyle-photo', inputs: { change: 'x' }, photoUrl: photo })).error, /Full or Pro local setup/);
assert.match((await light.runSkill({ skillId: 'upscale-photo', photoUrl: 'https://evil.example/a.jpg' })).error, /not on your ComfyUI/);
assert.match((await light.runSkill({ skillId: 'upscale-photo', photoUrl: `${base}/view?filename=../../etc/passwd&type=input` })).error, /not on your ComfyUI/);
assert.match((await full.runSkill({ skillId: 'character-post', inputs: { scene: 'topless' }, characterUrl: photo })).error, /fully clothed/);
assert.equal(queued.length, before);
assert.equal(light.isOwnFile(photo), true); assert.equal(light.isOwnFile('https://cdn.muapi.ai/x.png'), false);
console.log('PASS 5  light setup says what it needs; outside or path-trick photos refused; SEBastina rules hold locally');

// Pro: flagship open models, wired like ComfyUI's official templates.
const pro = new SEBastinaEngine({ backend: 'comfyui', comfyUrl: base, localProfile: 'pro', pollIntervalMs: 10 });
r = await pro.generateAsset({ prompt: 'a goat', aspectRatio: '1:1' });
wf = queued.at(-1).workflow;
assert.equal(byType(wf, 'UNETLoader').inputs.unet_name, 'z_image_turbo_bf16.safetensors');
assert.deepEqual([byType(wf, 'KSampler').inputs.steps, byType(wf, 'KSampler').inputs.sampler_name], [8, 'res_multistep']);
r = await pro.runSkill({ skillId: 'youtube-thumbnail', inputs: { subject: 'a goat', headline: 'GOAT MODE' } });
wf = queued.at(-1).workflow;
assert.equal(byType(wf, 'UNETLoader').inputs.unet_name, 'qwen_image_2512_fp8_e4m3fn.safetensors');
assert.equal(byType(wf, 'LoraLoaderModelOnly').inputs.lora_name, 'Qwen-Image-2512-Lightning-4steps-V1.0-fp32.safetensors');
assert.equal(byType(wf, 'KSampler').inputs.steps, 4);
console.log('PASS 6  Pro images: Z-Image Turbo by default; lettering Skills (thumbnail) go to Qwen-Image 2512 + 4-step Lightning');

r = await pro.runSkill({ skillId: 'product-ad-video', photoUrl: photo });
assert.equal(r.success, true, r.error);
const [pEdit, pVideo] = queued.slice(-2).map((q) => q.workflow);
assert.equal(byType(pEdit, 'UNETLoader').inputs.unet_name, 'qwen_image_edit_2511_fp8mixed.safetensors');
assert.ok(nodes(pEdit).includes('TextEncodeQwenImageEditPlus') && nodes(pEdit).includes('CFGNorm'));
const stages = Object.values(pVideo).filter((x) => x.class_type === 'KSamplerAdvanced');
assert.deepEqual(stages.map((x) => [x.inputs.start_at_step, x.inputs.end_at_step, x.inputs.add_noise]), [[0, 2, 'enable'], [2, 4, 'disable']]);
assert.deepEqual(Object.values(pVideo).filter((x) => x.class_type === 'UNETLoader').map((x) => x.inputs.unet_name), ['wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors', 'wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors']);
assert.equal(byType(pVideo, 'LoadImage').inputs.image, `goat_edit_${queued.at(-2).id}.png [output]`);
assert.equal(byType(pVideo, 'WanImageToVideo').inputs.length, 81);
r = await pro.generateAsset({ prompt: 'a goat running', isMotion: true });
assert.ok(nodes(queued.at(-1).workflow).includes('EmptyHunyuanLatentVideo'));
console.log('PASS 7  Pro edit (Qwen-Image-Edit 2511) and video (Wan 2.2 14B: high-noise 0-2, low-noise 2-4, 81 frames @16 fps)');

server.close();
console.log('\nAll own-computer checks passed.');
