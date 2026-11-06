// Check every local workflow against a ComfyUI /object_info dump:
//   node scripts/check-workflows.mjs object_info.json
// Node types must exist, every required input must be given, and choice inputs
// (samplers, schedulers, codecs, encoder types) must use an allowed value.
// Model file names are not checked (they depend on what's downloaded).
import { readFileSync } from 'node:fs';
import { t2iWorkflow, editWorkflow, videoWorkflow, upscaleWorkflow, removeBackgroundWorkflow, zImageWorkflow, qwenImageWorkflow, qwenEdit2511Workflow, wan14bWorkflow } from '../dist/local.js';

const info = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const req = { prompt: 'a goat', aspectRatio: '9:16', duration: 5 };
const img = 'goat/photo.jpg [input]';
const workflows = {
  't2i SD 1.5': t2iWorkflow(req, false), 't2i FLUX.1 Schnell': t2iWorkflow(req, true), 'edit Qwen': editWorkflow(req, img),
  'text-to-video Wan 2.2': videoWorkflow(req), 'photo-to-video Wan 2.2': videoWorkflow(req, img),
  'upscale Real-ESRGAN': upscaleWorkflow(img), 'remove background BiRefNet': removeBackgroundWorkflow(img),
  'PRO t2i Z-Image Turbo': zImageWorkflow(req), 'PRO t2i Qwen-Image 2512': qwenImageWorkflow(req),
  'PRO edit Qwen-Image-Edit 2511': qwenEdit2511Workflow(req, img),
  'PRO text-to-video Wan 2.2 14B': wan14bWorkflow(req), 'PRO photo-to-video Wan 2.2 14B': wan14bWorkflow(req, img),
};
const choices = (spec) => (Array.isArray(spec?.[0]) ? spec[0] : spec?.[0] === 'COMBO' ? spec?.[1]?.options : null);
let problems = 0;
for (const [name, wf] of Object.entries(workflows)) {
  for (const [id, node] of Object.entries(wf)) {
    const def = info[node.class_type];
    if (!def) { problems++; console.log(`✗ ${name}: node ${id} ${node.class_type} does not exist`); continue; }
    const required = def.input.required ?? {}, optional = def.input.optional ?? {};
    for (const key of Object.keys(required)) {
      if (!(key in node.inputs)) { problems++; console.log(`✗ ${name}: ${node.class_type} missing input "${key}"`); }
    }
    for (const [key, value] of Object.entries(node.inputs)) {
      const spec = required[key] ?? optional[key];
      if (!spec) { problems++; console.log(`✗ ${name}: ${node.class_type} has unknown input "${key}"`); continue; }
      if (Array.isArray(value)) {
        const [from, slot] = value; const src = wf[from];
        const outType = src && info[src.class_type]?.output?.[slot];
        const want = spec[0] === 'COMBO' ? null : typeof spec[0] === 'string' ? spec[0] : null;
        if (!src) { problems++; console.log(`✗ ${name}: ${key} links to missing node ${from}`); }
        else if (want && outType && want !== outType && want !== '*') { problems++; console.log(`✗ ${name}: ${node.class_type}.${key} wants ${want}, gets ${outType}`); }
        continue;
      }
      const allowed = choices(spec);
      if (allowed && !/_name$/.test(key) && key !== 'image' && !allowed.includes(value)) {
        problems++; console.log(`✗ ${name}: ${node.class_type}.${key} = ${JSON.stringify(value)} not in ${JSON.stringify(allowed.slice(0, 12))}`);
      }
    }
  }
  console.log(`${problems ? '…' : '✓'} ${name}: ${Object.keys(wf).length} nodes`);
}
if (problems) { console.log(`\n${problems} problem(s)`); process.exit(1); }
console.log('\nPASS    every local workflow matches this ComfyUI\'s node definitions');
