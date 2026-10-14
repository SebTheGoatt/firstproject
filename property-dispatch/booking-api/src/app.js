// app.js — Express app factory. Dependencies are injected so tests can run
// without hitting a real geocoder or database.

import express from 'express';
import { rateLimit } from 'express-rate-limit';

import { checkBookingRouter } from './routes/checkBooking.js';

export function createApp({ geocode, leads, trustProxy = 1 }) {
  const app = express();
  app.set('trust proxy', trustProxy); // real client IP behind Render/Heroku/etc. for rate limiting
  app.use(express.json({ limit: '10kb' }));

  // Public endpoint that spends geocoder quota and writes rows → throttle per IP.
  app.use(
    '/api/check-booking',
    rateLimit({
      windowMs: 15 * 60 * 1000,
      limit: 20,
      standardHeaders: 'draft-8',
      legacyHeaders: false,
      message: { ok: false, message: 'Too many attempts. Please try again in a few minutes.' },
    }),
  );

  app.use(checkBookingRouter({ geocode, leads }));

  app.get('/healthz', (_req, res) => res.json({ ok: true }));

  // Malformed JSON → 400; anything else unexpected → 500 without leaking details.
  app.use((err, _req, res, _next) => {
    if (err.type === 'entity.parse.failed') {
      return res.status(400).json({ ok: false, message: 'Invalid request body.' });
    }
    console.error('[booking-api]', err);
    res.status(500).json({ ok: false, message: 'Something went wrong. Please try again.' });
  });

  return app;
}
