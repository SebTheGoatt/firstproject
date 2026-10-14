# booking-api

Express service behind the first step of the booking flow: check that an
address is inside a service zone, save it as a lead with that zone's mowing
rate, and send the customer on to calendar selection.

## `POST /api/check-booking`

Request:
```json
{ "address": "3500 Rayford Rd, Spring, TX 77386" }
```

| Status | When | Body |
|---|---|---|
| **200** | Address is inside a zone; lead saved | `{ ok: true, leadId, zoneName, baseMowRate, formattedAddress, next: "calendar" }` |
| **400** | Outside every zone | `{ ok: false, waitlist: true, message: "We are currently fully booked in your area…" }` |
| 400 | Missing, too short, or malformed request | `{ ok: false, message }` (no `waitlist` flag) |
| 422 | Geocoder couldn't find the address | `{ ok: false, message }` |
| 429 | More than 20 attempts from one IP in 15 min | `{ ok: false, message }` |
| 503 | Geocoder down or rate-limited; safe to retry | `{ ok: false, message }` |

On the frontend, branch on `body.waitlist`, not just the status code, because a
bad request also returns 400.

```js
const res = await fetch('/api/check-booking', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ address }),
});
const body = await res.json();
if (res.ok) goToCalendar(body.leadId, body.baseMowRate);
else if (body.waitlist) showWaitlist(body.message);
else showError(body.message);
```

## Setup

1. In Supabase SQL Editor, run `../supabase/migrations/20261016000000_leads.sql`.
2. `cp .env.example .env` and fill it in.
3. `npm install && npm run dev` (Node 20+). Run tests with `npm test`.

## Geocoding: use Mapbox in production

With `MAPBOX_ACCESS_TOKEN` set, Mapbox is used; otherwise free Nominatim is.

Nominatim often doesn't know house numbers, so it returns a point somewhere on
the street. That matters at zone edges: in testing, "3500 Rayford Rd, Spring"
geocoded to a Rayford Road segment about 0.3 mi west of the Spring zone's edge
and was turned away. Mapbox (`types=address`) resolves to the house.

The Mapbox request sets `permanent=true` because the coordinates are stored in
`leads`. Mapbox's terms require this for stored results, and it is billed
under their permanent-geocoding pricing.
