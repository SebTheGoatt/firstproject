"""Geo-fenced service zones: mowing flat fee and sales tax rate per area.

Each bounding box is (min_lng, min_lat, max_lng, max_lat): bottom-left
corner to top-right corner, edges inclusive. A zone can cover several boxes
(e.g. Cleveland plus Plum Grove). Addresses outside every box are turned
away at intake. Boxes must not overlap, so a point maps to at most one zone
and one price.

tax_rate is the combined Texas state + local sales tax for the area
(6.25% state + up to 2% local). 8.25% is the default; check each area with
the Comptroller's Sales Tax Rate Locator and adjust here.
"""

from dataclasses import dataclass, field

Box = tuple[float, float, float, float]  # min_lng, min_lat, max_lng, max_lat
DEFAULT_TAX_RATE = 0.0825
FLAT_FEE = 50.00  # mowing base trip fee per visit, the same in every area


@dataclass(frozen=True)
class ServiceZone:
    key: str
    name: str
    bbox: Box                                 # main box (map pin + label)
    mow_rate: float                           # mowing base trip fee per visit, USD (+ rate × sq ft)
    extra_boxes: tuple[Box, ...] = field(default=())
    tax_rate: float = DEFAULT_TAX_RATE

    @property
    def boxes(self) -> tuple[Box, ...]:
        return (self.bbox, *self.extra_boxes)

    def contains(self, lat: float, lng: float) -> bool:
        return any(w <= lng <= e and s <= lat <= n for w, s, e, n in self.boxes)


SERVICE_ZONES: tuple[ServiceZone, ...] = (
    ServiceZone(
        key="SPRING_LUXURY_LOOP",
        name="Spring / Woodson's Reserve Corridor",
        # Woodson's Reserve and surrounding SH-99 / Rayford Rd developments.
        # South edge at 30.10 so all of Woodson's Reserve (center ~30.116) fits.
        bbox=(-95.4200, 30.1000, -95.2800, 30.1800),
        mow_rate=FLAT_FEE,
    ),
    ServiceZone(
        key="KLEIN_CORE",
        name="Klein",
        # ZIPs 77379 and 77388: FM 1960 (south) to just below 77389 (north),
        # west of Champion Forest Dr to just west of I-45. Stops at -95.425 so
        # it never touches the Spring corridor or takes in Old Town Spring.
        bbox=(-95.5850, 29.9950, -95.4250, 30.0900),
        mow_rate=FLAT_FEE,
    ),
    ServiceZone(
        key="I69_HIGH_DENSITY_SPINE",
        name="New Caney & Splendora High-Density Spine",
        # The Canopies, Gemini, and Porters Mill developments.
        # West edge at -95.26 so The Canopies (~-95.234 to -95.237) is inside.
        # East edge at -95.115 so Plum Grove (~-95.109 to -95.087) belongs to Cleveland.
        bbox=(-95.2600, 30.1850, -95.1150, 30.2950),
        mow_rate=FLAT_FEE,
    ),
    ServiceZone(
        key="CLEVELAND_HUB",
        name="Cleveland, Plum Grove & Grand Oaks Reserve",
        # Grand Oaks Reserve and new construction off FM 1010 / SH-105.
        # West edge at -95.15 to include Grand Oaks Reserve (~-95.05 to -95.06)
        # and downtown Cleveland (~-95.09).
        bbox=(-95.1500, 30.3000, -94.9100, 30.3800),
        # Plum Grove (Liberty County, ~30.171-30.227, -95.109 to -95.087), served
        # with the Cleveland sector.
        extra_boxes=((-95.1120, 30.1650, -95.0800, 30.2350),),
        mow_rate=FLAT_FEE,
    ),
    ServiceZone(
        key="COLONY_RIDGE",
        name="Colony Ridge",
        # Colony Ridge (Liberty County, east of Plum Grove off FM 1010 / FM 2100): Santa Fe
        # (~30.161, -95.051), Grand San Jacinto (~30.179, -95.070), Montebello (~30.188, -95.073),
        # the main Colony Ridge area (~30.187, -95.045), Camino Real (~30.201, -95.067) and
        # Bella Vista (~30.256, -95.064). West edge just east of the Plum Grove box, so
        # Rancho San Vicente (~30.232, -95.087), which sits in Plum Grove, stays in that zone.
        bbox=(-95.0795, 30.1450, -95.0000, 30.2750),
        mow_rate=FLAT_FEE,
    ),
)


def zone_by_key(key: str | None) -> ServiceZone | None:
    return next((z for z in SERVICE_ZONES if z.key == key), None)


def find_zone(lat: float, lng: float) -> ServiceZone | None:
    return next((z for z in SERVICE_ZONES if z.contains(lat, lng)), None)


def validate_zones(zones: tuple[ServiceZone, ...]) -> None:
    """Fail fast on a typo'd box: inverted corners, out-of-range, overlap, or a bad rate."""
    for z in zones:
        for box in z.boxes:
            min_lng, min_lat, max_lng, max_lat = box
            if not (-180 <= min_lng < max_lng <= 180 and -90 <= min_lat < max_lat <= 90):
                raise ValueError(f"{z.key}: box must be (min_lng, min_lat, max_lng, max_lat), got {box}")
        if z.mow_rate < 0:
            raise ValueError(f"{z.key}: mow_rate must be non-negative")
        if not 0 <= z.tax_rate < 0.2:
            raise ValueError(f"{z.key}: tax_rate looks wrong ({z.tax_rate}); use 0.0825 for 8.25%")
    labeled = [(z.key, box) for z in zones for box in z.boxes]
    for i, (ka, a) in enumerate(labeled):
        for kb, b in labeled[i + 1:]:
            if a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]:
                raise ValueError(f"Zones {ka} and {kb} overlap")


validate_zones(SERVICE_ZONES)
