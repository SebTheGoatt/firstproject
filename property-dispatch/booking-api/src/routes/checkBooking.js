// routes/checkBooking.js
//
// POST /api/check-booking   { "address": "123 Main St, Spring, TX 77386" }
//
//   200 → in a service zone; lead saved. Frontend proceeds to calendar selection.
//   400 → outside every zone (waitlist message), or missing/invalid address.
//   422 → the geocoder couldn't find the address.
//   503 → the geocoder is down; safe to retry.

import { Router } from 'express';

import { AddressNotFoundError, GeocoderUnavailableError } from '../geocode.js';
import { validateCustomerLocation } from '../serviceZones.js';

export const OUT_OF_AREA_MESSAGE =
  'We are currently fully booked in your area to maintain route efficiency. Please join our waitlist.';

/**
 * @param {object} deps
 * @param {(address: string) => Promise<{lat:number,lng:number,formattedAddress:string}>} deps.geocode
 * @param {{ insertLead: (lead: object) => Promise<{id: string}> }} deps.leads
 */
export function checkBookingRouter({ geocode, leads }) {
  const router = Router();

  router.post('/api/check-booking', async (req, res) => {
    // 1. Accept the address string.
    const address = typeof req.body?.address === 'string' ? req.body.address.trim() : '';
    if (address.length < 5 || address.length > 300) {
      return res.status(400).json({ ok: false, message: 'Please enter your full street address.' });
    }

    // 2. Geocode → lat/lng.
    let geo;
    try {
      geo = await geocode(address);
    } catch (err) {
      if (err instanceof AddressNotFoundError) {
        return res.status(422).json({
          ok: false,
          message: "We couldn't find that address. Please include street, city and ZIP.",
        });
      }
      if (err instanceof GeocoderUnavailableError) {
        console.error('[check-booking] geocoder unavailable:', err.message);
        return res.status(503).json({ ok: false, message: 'Address lookup is busy. Please try again in a minute.' });
      }
      throw err;
    }

    // 3. Zone check.
    const zone = validateCustomerLocation(geo.lat, geo.lng);

    // 4. Outside every zone → waitlist.
    if (!zone.isValid) {
      return res.status(400).json({ ok: false, waitlist: true, message: OUT_OF_AREA_MESSAGE });
    }

    // 5. Inside a zone → save the lead with the zone's mow rate.
    const lead = await leads.insertLead({
      address,
      formattedAddress: geo.formattedAddress,
      lat: geo.lat,
      lng: geo.lng,
      zoneName: zone.zoneName,
      baseMowRate: zone.baseMowRate,
    });

    return res.status(200).json({
      ok: true,
      leadId: lead.id,
      zoneName: zone.zoneName,
      baseMowRate: zone.baseMowRate,
      formattedAddress: geo.formattedAddress,
      next: 'calendar',
    });
  });

  return router;
}
