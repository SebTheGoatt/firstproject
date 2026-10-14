import assert from 'node:assert/strict';
import { after, before, beforeEach, describe, it } from 'node:test';

import { createApp } from '../src/app.js';
import { AddressNotFoundError, GeocoderUnavailableError, mapboxGeocoder } from '../src/geocode.js';
import { OUT_OF_AREA_MESSAGE } from '../src/routes/checkBooking.js';
import { validateCustomerLocation } from '../src/serviceZones.js';

// Fake geocoder keyed by the first word of the address.
const PLACES = {
  Rayford: { lat: 30.124, lng: -95.4126 },   // Spring zone
  Splendora: { lat: 30.233, lng: -95.161 },  // I-69 spine
  Cleveland: { lat: 30.34, lng: -94.98 },    // Cleveland hub box
  OldTown: { lat: 30.0799, lng: -95.4172 },  // outside every zone
};

let server, baseUrl, inserted, geocodeImpl;

before(async () => {
  const app = createApp({
    geocode: (address) => geocodeImpl(address),
    leads: { insertLead: async (lead) => (inserted.push(lead), { id: `lead-${inserted.length}` }) },
    trustProxy: false,
  });
  await new Promise((resolve) => { server = app.listen(0, resolve); });
  baseUrl = `http://127.0.0.1:${server.address().port}`;
});
after(() => server.close());
beforeEach(() => {
  inserted = [];
  geocodeImpl = async (address) => {
    const p = PLACES[address.split(' ')[0]];
    if (!p) throw new AddressNotFoundError('nope');
    return { ...p, formattedAddress: `${address}, TX` };
  };
});

const post = (body, raw = false) =>
  fetch(`${baseUrl}/api/check-booking`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: raw ? body : JSON.stringify(body),
  }).then(async (r) => ({ status: r.status, body: await r.json() }));

describe('POST /api/check-booking', () => {
  for (const [place, zoneName, rate] of [
    ['Rayford', "Spring / Woodson's Reserve Corridor", 55],
    ['Splendora', 'New Caney & Splendora High-Density Spine', 40],
    ['Cleveland', 'Cleveland / Grand Oaks Reserve Hub', 45],
  ]) {
    it(`in-zone (${place}) → 200, lead saved with $${rate}`, async () => {
      const { status, body } = await post({ address: `${place} Rd, TX 77386` });
      assert.equal(status, 200);
      assert.deepEqual(
        { ok: body.ok, zoneName: body.zoneName, baseMowRate: body.baseMowRate, next: body.next, leadId: body.leadId },
        { ok: true, zoneName, baseMowRate: rate, next: 'calendar', leadId: 'lead-1' },
      );
      assert.equal(inserted.length, 1);
      assert.equal(inserted[0].baseMowRate, rate);
      assert.equal(inserted[0].zoneName, zoneName);
      assert.equal(inserted[0].address, `${place} Rd, TX 77386`);
    });
  }

  it('out-of-zone → 400 waitlist message, nothing saved', async () => {
    const { status, body } = await post({ address: 'OldTown 26111 Hardy Rd, Spring, TX' });
    assert.equal(status, 400);
    assert.equal(body.message, OUT_OF_AREA_MESSAGE);
    assert.equal(body.waitlist, true);
    assert.equal(inserted.length, 0);
  });

  it('missing / non-string / too-short address → 400 without geocoding', async () => {
    let calls = 0;
    geocodeImpl = async () => { calls++; return PLACES.Rayford; };
    for (const body of [{}, { address: 12345 }, { address: '   ' }, { address: 'ab' }]) {
      const res = await post(body);
      assert.equal(res.status, 400);
      assert.notEqual(res.body.message, OUT_OF_AREA_MESSAGE);
    }
    assert.equal(calls, 0);
  });

  it('malformed JSON → 400', async () => {
    const res = await post('{"address":', true);
    assert.equal(res.status, 400);
  });

  it('unknown address → 422 (not the waitlist message)', async () => {
    const res = await post({ address: 'Nowhere Lane, Atlantis' });
    assert.equal(res.status, 422);
    assert.equal(inserted.length, 0);
  });

  it('geocoder outage → 503', async () => {
    geocodeImpl = async () => { throw new GeocoderUnavailableError('down'); };
    const res = await post({ address: 'Rayford Rd, Spring, TX' });
    assert.equal(res.status, 503);
  });

  it('database failure → 500 without leaking details', async () => {
    const app = createApp({
      geocode: async () => ({ ...PLACES.Rayford, formattedAddress: 'x' }),
      leads: { insertLead: async () => { throw new Error('secret db detail'); } },
      trustProxy: false,
    });
    const srv = await new Promise((r) => { const s = app.listen(0, () => r(s)); });
    const origError = console.error;
    console.error = () => {};
    try {
      const r = await fetch(`http://127.0.0.1:${srv.address().port}/api/check-booking`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address: 'Rayford Rd, Spring, TX' }),
      });
      assert.equal(r.status, 500);
      assert.doesNotMatch(await r.text(), /secret/);
    } finally {
      console.error = origError;
      srv.close();
    }
  });
});

describe('validateCustomerLocation', () => {
  it('edges are inclusive', () => {
    assert.equal(validateCustomerLocation(30.10, -95.42).isValid, true);
    assert.equal(validateCustomerLocation(30.18, -95.28).isValid, true);
    assert.equal(validateCustomerLocation(30.0999, -95.42).isValid, false);
  });

  it('covers the places each zone is named for', () => {
    const zoneOf = (lat, lng) => validateCustomerLocation(lat, lng).zoneName;
    assert.match(zoneOf(30.1160, -95.3636), /Woodson/);       // Woodson's Reserve
    assert.match(zoneOf(30.3391, -95.0579), /Grand Oaks/);    // Kingston Heath Dr (Grand Oaks Reserve)
    assert.match(zoneOf(30.3367, -95.0506), /Grand Oaks/);    // Spyglass Hill Dr (clubhouse)
    assert.match(zoneOf(30.3415, -95.0900), /Cleveland/);     // downtown Cleveland
  });
});

describe('mapboxGeocoder', () => {
  it('reads [lng, lat] correctly and requests permanent geocoding', async () => {
    const realFetch = globalThis.fetch;
    let requested;
    globalThis.fetch = async (url) => {
      requested = new URL(url);
      return new Response(JSON.stringify({
        features: [{ geometry: { coordinates: [-95.4126, 30.124] }, properties: { full_address: '3500 Rayford Rd' } }],
      }));
    };
    try {
      const geo = await mapboxGeocoder('pk.test')('3500 Rayford Rd');
      assert.deepEqual(geo, { lat: 30.124, lng: -95.4126, formattedAddress: '3500 Rayford Rd' });
      assert.equal(requested.searchParams.get('permanent'), 'true');
      assert.equal(requested.searchParams.get('country'), 'us');
    } finally {
      globalThis.fetch = realFetch;
    }
  });

  it('no features → AddressNotFoundError', async () => {
    const realFetch = globalThis.fetch;
    globalThis.fetch = async () => new Response(JSON.stringify({ features: [] }));
    try {
      await assert.rejects(mapboxGeocoder('pk.test')('nowhere'), AddressNotFoundError);
    } finally {
      globalThis.fetch = realFetch;
    }
  });
});
