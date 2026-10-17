"""Estimated lawn size for an address, so customers don't have to guess square footage.

No map service publishes lot or turf area, so this is an honest estimate per service area:
- once the crew has confirmed enough real lawns in the area, the median of those (rounded to 100 sq ft);
- until then, a typical lot (LAWN_SIZES["medium"]).
The customer can change it, and the crew confirms the real size on site before anything is charged.
"""

from statistics import median

from .pricing import DEFAULT_SIZE, LAWN_SIZES
from .zones import ServiceZone

MIN_SAMPLE = 5           # confirmed lawns needed before the area's own median is used
SAMPLE_SIZE = 50         # most recent confirmed lawns considered


def estimate_lawn(repo, zone: ServiceZone) -> dict:
    sizes: list[int] = []
    try:
        sizes = [s for s in repo.recent_lawn_sizes(zone.key, SAMPLE_SIZE) if s]
    except Exception:            # never block the address check on this
        sizes = []
    if len(sizes) >= MIN_SAMPLE:
        return {"sqft": int(round(median(sizes) / 100) * 100), "basis": "recent", "sample": len(sizes), "zone_name": zone.name}
    return {"sqft": LAWN_SIZES[DEFAULT_SIZE]["sqft"], "basis": "typical", "sample": len(sizes), "zone_name": zone.name}
