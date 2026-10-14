"""Geo-fenced service zones and their mowing rates.

Each bounding box is (min_lng, min_lat, max_lng, max_lat): bottom-left
corner to top-right corner, edges inclusive. Addresses outside every zone
are turned away at intake. Boxes must not overlap, so a point maps to at
most one zone and one price.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceZone:
    key: str
    name: str
    bbox: tuple[float, float, float, float]  # min_lng, min_lat, max_lng, max_lat
    mow_rate: float                           # USD per mowing visit

    def contains(self, lat: float, lng: float) -> bool:
        min_lng, min_lat, max_lng, max_lat = self.bbox
        return min_lng <= lng <= max_lng and min_lat <= lat <= max_lat


SERVICE_ZONES: tuple[ServiceZone, ...] = (
    ServiceZone(
        key="SPRING_LUXURY_LOOP",
        name="Spring / Woodson's Reserve Corridor",
        # Woodson's Reserve and surrounding SH-99 / Rayford Rd developments.
        # South edge at 30.10 so all of Woodson's Reserve (center ~30.116) fits.
        bbox=(-95.4200, 30.1000, -95.2800, 30.1800),
        mow_rate=55.00,  # premium pricing for larger luxury lots
    ),
    ServiceZone(
        key="I69_HIGH_DENSITY_SPINE",
        name="New Caney & Splendora High-Density Spine",
        # The Canopies, Gemini, and Porters Mill developments.
        # West edge at -95.26 so The Canopies (~-95.234 to -95.237) is inside.
        bbox=(-95.2600, 30.1850, -95.0900, 30.2950),
        mow_rate=40.00,  # clustered pricing optimized for foot-traffic speed
    ),
    ServiceZone(
        key="CLEVELAND_HUB",
        name="Cleveland / Grand Oaks Reserve Hub",
        # Grand Oaks Reserve and new construction off FM 1010 / SH-105.
        # West edge at -95.15 to include Grand Oaks Reserve (~-95.05 to -95.06)
        # and downtown Cleveland (~-95.09).
        bbox=(-95.1500, 30.3000, -94.9100, 30.3800),
        mow_rate=45.00,
    ),
)


def find_zone(lat: float, lng: float) -> ServiceZone | None:
    return next((z for z in SERVICE_ZONES if z.contains(lat, lng)), None)


def validate_zones(zones: tuple[ServiceZone, ...]) -> None:
    """Fail fast on a typo'd box: inverted corners, out-of-range, or overlap."""
    for z in zones:
        min_lng, min_lat, max_lng, max_lat = z.bbox
        if not (-180 <= min_lng < max_lng <= 180 and -90 <= min_lat < max_lat <= 90):
            raise ValueError(f"{z.key}: bbox must be (min_lng, min_lat, max_lng, max_lat), got {z.bbox}")
        if z.mow_rate < 0:
            raise ValueError(f"{z.key}: mow_rate must be non-negative")
    for i, a in enumerate(zones):
        for b in zones[i + 1:]:
            if (a.bbox[0] <= b.bbox[2] and b.bbox[0] <= a.bbox[2]
                    and a.bbox[1] <= b.bbox[3] and b.bbox[1] <= a.bbox[3]):
                raise ValueError(f"Zones {a.key} and {b.key} overlap")


validate_zones(SERVICE_ZONES)
