// geocode.js — address string → { lat, lng, formattedAddress }
//
// Uses Mapbox when MAPBOX_ACCESS_TOKEN is set, otherwise free OpenStreetMap
// Nominatim. Both return [lng, lat] / lon-lat ordering in their raw payloads;
// everything leaving this module is normalized to named { lat, lng }.

export class AddressNotFoundError extends Error {}
export class GeocoderUnavailableError extends Error {}

const TIMEOUT_MS = 8000;

async function getJson(url, headers = {}) {
  let res;
  try {
    res = await fetch(url, { headers, signal: AbortSignal.timeout(TIMEOUT_MS) });
  } catch (err) {
    throw new GeocoderUnavailableError(`Geocoder request failed: ${err.message}`);
  }
  if (!res.ok) throw new GeocoderUnavailableError(`Geocoder responded ${res.status}`);
  return res.json();
}

/**
 * Mapbox Geocoding API v6.
 * `permanent=true` is required by Mapbox's terms because we store the result
 * in the database; it is billed under Mapbox's permanent-geocoding pricing.
 */
export function mapboxGeocoder(accessToken) {
  return async function geocode(address) {
    const params = new URLSearchParams({
      q: address,
      access_token: accessToken,
      country: 'us',
      types: 'address',
      limit: '1',
      permanent: 'true',
    });
    const data = await getJson(`https://api.mapbox.com/search/geocode/v6/forward?${params}`);
    const hit = data.features?.[0];
    if (!hit) throw new AddressNotFoundError('Address not found');
    const [lng, lat] = hit.geometry.coordinates;
    return { lat, lng, formattedAddress: hit.properties?.full_address ?? address };
  };
}

/**
 * OpenStreetMap Nominatim (free). Policy: ≤1 request/second and a real
 * contact in the User-Agent; placeholder domains such as example.com get 403.
 */
export function nominatimGeocoder(userAgent) {
  let queue = Promise.resolve();
  let lastCall = 0;

  async function lookup(address) {
    const wait = 1000 - (Date.now() - lastCall);
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    lastCall = Date.now();
    const params = new URLSearchParams({ q: address, format: 'jsonv2', limit: '1', countrycodes: 'us' });
    const data = await getJson(`https://nominatim.openstreetmap.org/search?${params}`, {
      'User-Agent': userAgent,
    });
    const hit = data[0];
    if (!hit) throw new AddressNotFoundError('Address not found');
    return { lat: Number(hit.lat), lng: Number(hit.lon), formattedAddress: hit.display_name ?? address };
  }

  // Serialize calls so concurrent requests respect the 1 req/s limit.
  return function geocode(address) {
    const result = queue.then(() => lookup(address));
    queue = result.catch(() => {});
    return result;
  };
}

export function geocoderFromEnv(env = process.env) {
  if (env.MAPBOX_ACCESS_TOKEN) return mapboxGeocoder(env.MAPBOX_ACCESS_TOKEN);
  if (!env.GEOCODER_USER_AGENT) {
    throw new Error('Set MAPBOX_ACCESS_TOKEN, or GEOCODER_USER_AGENT (with a contact email) for Nominatim');
  }
  return nominatimGeocoder(env.GEOCODER_USER_AGENT);
}
