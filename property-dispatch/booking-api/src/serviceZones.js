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
    targetRateMow: 55.00, // Premium pricing for larger luxury lots
  },
  KLEIN_CORE: {
    name: "Klein",
    // ZIPs 77379 and 77388: FM 1960 (south) to just below 77389 (north),
    // west of Champion Forest Dr to just west of I-45.
    boundingBox: [-95.5850, 29.9950, -95.4250, 30.0900],
    targetRateMow: 55.00,
  },
  I69_HIGH_DENSITY_SPINE: {
    name: "New Caney & Splendora High-Density Spine",
    // Concentrated spine covering The Canopies, Gemini, and Porters Mill developments.
    // West edge at -95.26 so The Canopies (~-95.234 to -95.237) is inside.
    boundingBox: [-95.2600, 30.1850, -95.0900, 30.2950],
    targetRateMow: 40.00, // Clustered pricing optimized for foot-traffic speed
  },
  CLEVELAND_HUB: {
    name: "Cleveland / Grand Oaks Reserve Hub",
    // Covers Grand Oaks Reserve and new construction off FM 1010 / SH-105.
    // West edge at -95.15 to include Grand Oaks Reserve (~-95.05 to -95.06)
    // and downtown Cleveland (~-95.09).
    boundingBox: [-95.1500, 30.3000, -94.9100, 30.3800],
    targetRateMow: 45.00,
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
    const [minLng, minLat, maxLng, maxLat] = zone.boundingBox;

    if (lng >= minLng && lng <= maxLng && lat >= minLat && lat <= maxLat) {
      return {
        isValid: true,
        zoneName: zone.name,
        baseMowRate: zone.targetRateMow
      };
    }
  }
  return { isValid: false, zoneName: null, baseMowRate: null };
}
