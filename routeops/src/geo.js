// Geometry + travel-time helpers. No external routing service is required:
// straight-line distance is inflated by a "road factor" to approximate
// real street distance.

const EARTH_RADIUS_KM = 6371;

function toRad(deg) {
  return (deg * Math.PI) / 180;
}

function haversineKm(a, b) {
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(h));
}

function roadKm(a, b, roadFactor = 1.3) {
  return haversineKm(a, b) * roadFactor;
}

function travelMinutes(km, speedKmh) {
  return (km / speedKmh) * 60;
}

// Move from `from` toward `to` by `km`. Returns { point, arrived }.
function stepToward(from, to, km) {
  const total = haversineKm(from, to);
  if (total <= km || total === 0) return { point: { lat: to.lat, lng: to.lng }, arrived: true };
  const f = km / total;
  return {
    point: { lat: from.lat + (to.lat - from.lat) * f, lng: from.lng + (to.lng - from.lng) * f },
    arrived: false,
  };
}

// "08:30" <-> 510
function parseHHMM(s) {
  if (typeof s === 'number') return s;
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(s || '').trim());
  if (!m) return null;
  return Number(m[1]) * 60 + Number(m[2]);
}

function fmtHHMM(min) {
  if (min == null || Number.isNaN(min)) return '--:--';
  const m = Math.round(min);
  const h = Math.floor(m / 60) % 24;
  return `${String(h).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
}

module.exports = { haversineKm, roadKm, travelMinutes, stepToward, parseHHMM, fmtHHMM };
