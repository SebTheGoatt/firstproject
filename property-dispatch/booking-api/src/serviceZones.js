// serviceZones.js

/**
 * Geo-fence bounding boxes for high-density lawn care corridors.
 * Format: [Min Longitude, Min Latitude, Max Longitude, Max Latitude]
 * (Bottom-Left corner to Top-Right corner)
 */
export const SERVICE_ZONES = {
  SPRING_LUXURY_LOOP: {
    name: "Spring / Woodson's Reserve Corridor",
    // Covers Woodson's Reserve and surrounding SH-99 / Rayford Rd developments.
    // South edge at 30.10 so all of Woodson's Reserve (center ~30.116) fits.
    boundingBox: [-95.4200, 30.1000, -95.2800, 30.1800],
    targetRateMow: 50.00, // $50 minimum per mow in every area
  },
  KLEIN_CORE: {
    name: "Klein",
    // ZIPs 77379 and 77388: FM 1960 (south) to just below 77389 (north),
    // west of Champion Forest Dr to just west of I-45.
    boundingBox: [-95.5850, 29.9950, -95.4250, 30.0900],
    targetRateMow: 50.00, // $50 minimum per mow in every area
  },
  I69_HIGH_DENSITY_SPINE: {
    name: "New Caney & Splendora High-Density Spine",
    // Concentrated spine covering The Canopies, Gemini, and Porters Mill developments.
    // West edge at -95.26 so The Canopies (~-95.234 to -95.237) is inside.
    // East edge at -95.115 so Plum Grove belongs to the Cleveland hub.
    boundingBox: [-95.2600, 30.1850, -95.1150, 30.2950],
    targetRateMow: 50.00, // $50 minimum per mow in every area
  },
  CLEVELAND_HUB: {
    name: "Cleveland, Plum Grove & Grand Oaks Reserve",
    // Covers Grand Oaks Reserve and new construction off FM 1010 / SH-105.
    // West edge at -95.15 to include Grand Oaks Reserve (~-95.05 to -95.06)
    // and downtown Cleveland (~-95.09).
    boundingBox: [-95.1500, 30.3000, -94.9100, 30.3800],
    // Plum Grove (~-95.10, 30.20), served from the Cleveland hub.
    extraBoxes: [[-95.1120, 30.1650, -95.0800, 30.2350]],
    targetRateMow: 50.00, // $50 minimum per mow in every area
  },
  COLONY_RIDGE: {
    name: "Colony Ridge",
    // Liberty County, east of Plum Grove: Santa Fe, Grand San Jacinto, Montebello,
    // Camino Real, Bella Vista and the main Colony Ridge area.
    boundingBox: [-95.0795, 30.1450, -95.0000, 30.2750],
    targetRateMow: 50.00, // $50 minimum per mow in every area
  }
};

/**
 * Validates if a coordinate falls inside any of our high-density zones.
 * @param {number} lat - Latitude of the customer address
 * @param {number} lng - Longitude of the customer address
 * @returns {{isValid: boolean, zoneName: string|null, baseMowRate: number|null}}
 *   Always an object: check `isValid`, not truthiness.
 */
export function validateCustomerLocation(lat, lng) {
  for (const zoneKey in SERVICE_ZONES) {
    const zone = SERVICE_ZONES[zoneKey];
    const boxes = [zone.boundingBox, ...(zone.extraBoxes || [])];
    const inside = boxes.some(([minLng, minLat, maxLng, maxLat]) =>
      lng >= minLng && lng <= maxLng && lat >= minLat && lat <= maxLat);

    if (inside) {
      return {
        isValid: true,
        zoneName: zone.name,
        baseMowRate: zone.targetRateMow
      };
    }
  }
  return { isValid: false, zoneName: null, baseMowRate: null };
}
