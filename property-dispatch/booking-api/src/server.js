// server.js — production entry point.

import { createApp } from './app.js';
import { geocoderFromEnv } from './geocode.js';
import { leadStoreFromEnv } from './leads.js';

const app = createApp({ geocode: geocoderFromEnv(), leads: leadStoreFromEnv() });
const port = Number(process.env.PORT) || 3001;

app.listen(port, () => console.log(`booking-api listening on :${port}`));
