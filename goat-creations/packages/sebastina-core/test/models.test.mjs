// Each catalog model gets exactly the fields its MuAPI schema accepts.
import assert from 'node:assert/strict';
import { buildPayload, IMAGE_MODELS, VIDEO_MODELS, findModel } from '../dist/index.js';

// Pixel models: width/height on the 64-grid, from a size or an aspect ratio.
assert.deepEqual(buildPayload('flux-dev-image', 'image', { prompt: 'p', width: 1000, height: 700 }),
  { prompt: 'p', width: 1024, height: 704, num_images: 1 });
assert.deepEqual(buildPayload('flux-schnell-image', 'image', { prompt: 'p', aspectRatio: '9:16' }),
  { prompt: 'p', width: 768, height: 1344, num_images: 1 });
assert.deepEqual(buildPayload('hidream_i1_fast_image', 'image', { prompt: 'p' }),
  { prompt: 'p', width: 1024, height: 1024, num_images: 1 });

// Aspect models: no width/height; closest allowed ratio; their own quality default.
assert.deepEqual(buildPayload('nano-banana', 'image', { prompt: 'p', width: 768, height: 1344 }),
  { prompt: 'p', aspect_ratio: '9:16' });
assert.deepEqual(buildPayload('gpt-image-1.5', 'image', { prompt: 'p', width: 768, height: 1344 }),
  { prompt: 'p', aspect_ratio: '2:3', quality: 'medium' });

// Video: duration clamped to the model's range, resolution only where offered.
assert.deepEqual(buildPayload('seedance-lite-t2v', 'video', { prompt: 'p', aspectRatio: '9:16', duration: 5 }),
  { prompt: 'p', aspect_ratio: '9:16', duration: 5, resolution: '480p' });
assert.deepEqual(buildPayload('seedance-v1.5-pro-t2v-fast', 'video', { prompt: 'p', aspectRatio: '16:9', duration: 2 }),
  { prompt: 'p', aspect_ratio: '16:9', duration: 4, resolution: '720p' });
assert.deepEqual(buildPayload('kling-v2.1-master-t2v', 'video', { prompt: 'p', aspectRatio: '5:4', duration: 30 }),
  { prompt: 'p', aspect_ratio: '1:1', duration: 10 });
assert.deepEqual(buildPayload('veo3-fast-text-to-video', 'video', { prompt: 'p', aspectRatio: '9:16', duration: 8 }),
  { prompt: 'p', aspect_ratio: '9:16' });
assert.deepEqual(buildPayload('wan2.2-text-to-video', 'video', { prompt: 'p', aspectRatio: '1:1', resolution: '720p' }),
  { prompt: 'p', aspect_ratio: '16:9', duration: 5, resolution: '720p', quality: 'medium' });

// A model outside the catalog (set by env) keeps the generic shape.
assert.deepEqual(buildPayload('some-new-video', 'video', { prompt: 'p' }),
  { prompt: 'p', aspect_ratio: '16:9', duration: 5, resolution: '480p' });

assert.equal(IMAGE_MODELS.length, 5); assert.equal(VIDEO_MODELS.length, 5);
assert.equal(findModel('veo3-fast-text-to-video').kind, 'video');
console.log('PASS    model catalog: 10 models, each request shaped to its MuAPI schema');
