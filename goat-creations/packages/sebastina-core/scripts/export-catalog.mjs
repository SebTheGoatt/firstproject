// Export the shared catalog (models + Skills) and golden payload cases for the
// Python ComfyUI pack, so both languages build identical MuAPI requests.
//   node scripts/export-catalog.mjs          write the files
//   node scripts/export-catalog.mjs --check  fail if they are out of date
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { ALL_MODELS, SKILLS, buildPayload, renderPrompt, isVideoModel } from '../dist/index.js';

const pack = fileURLToPath(new URL('../../../apps/comfyui-goat/', import.meta.url));
const PHOTO = 'https://cdn.muapi.ai/uploads/photo.jpg';

const catalog = { note: 'Generated from packages/sebastina-core (npm run catalog). Do not edit by hand.', models: ALL_MODELS, skills: SKILLS };

// Every model with a few request shapes, plus every Skill's rendered prompts.
const requests = [
  { prompt: 'p' },
  { prompt: 'p', aspectRatio: '9:16' },
  { prompt: 'p', width: 1000, height: 700, duration: 30, resolution: '720p' },
  { prompt: 'p', aspectRatio: '5:4', duration: 2 },
];
const payloadCases = [];
for (const model of ALL_MODELS) {
  for (const base of requests) {
    const req = model.imageField ? { ...base, imageUrl: PHOTO } : base;
    payloadCases.push({ model: model.id, kind: isVideoModel(model) ? 'video' : 'image', request: req, payload: buildPayload(model.id, isVideoModel(model) ? 'video' : 'image', req) });
  }
}
payloadCases.push({ model: 'unknown-model', kind: 'image', request: { prompt: 'p', aspectRatio: '16:9' }, payload: buildPayload('unknown-model', 'image', { prompt: 'p', aspectRatio: '16:9' }) });
const promptCases = [];
for (const skill of SKILLS) {
  const full = Object.fromEntries(skill.fields.map((f) => [f.id, `my ${f.id}`]));
  for (const inputs of [full, {}]) {
    promptCases.push({ skill: skill.id, inputs, prompts: skill.steps.map((s) => renderPrompt(s.prompt, skill, inputs)) });
  }
}

const files = {
  [`${pack}goat_catalog.json`]: JSON.stringify(catalog, null, 2) + '\n',
  [`${pack}tests/golden_cases.json`]: JSON.stringify({ payloadCases, promptCases }, null, 2) + '\n',
};
const check = process.argv.includes('--check');
let stale = false;
for (const [path, text] of Object.entries(files)) {
  if (check) {
    let current = '';
    try { current = readFileSync(path, 'utf8'); } catch {}
    if (current !== text) { stale = true; console.error(`out of date: ${path} (run: npm run catalog)`); }
  } else {
    writeFileSync(path, text);
    console.log(`wrote ${path}`);
  }
}
if (check && stale) process.exit(1);
if (check) console.log('PASS    ComfyUI pack catalog and golden cases match sebastina-core');
