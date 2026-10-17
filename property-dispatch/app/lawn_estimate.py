"""Lawn size for an address, so customers don't have to guess square footage.

The customer picks what to mow; the server sets the size for that choice in their service area:
- "Yard only": the median of crew-measured lawns in the area once there are enough (jobs priced before
  the yard/full choice existed, which the crew confirmed on site), otherwise the area's yard_sqft;
- "Full property": the area's full_property_sqft (the whole lot minus the house).
No map service publishes lot or turf area, so these are per-area numbers, set in app/zones.py.
Bookings with a choice are price-locked: the crew mows the area booked and does not re-measure.
"""

from statistics import median

from .zones import ServiceZone

MIN_SAMPLE = 5           # crew-measured lawns needed before the area's own median is used
SAMPLE_SIZE = 50         # most recent measured lawns considered


def estimate_lawn(repo, zone: ServiceZone) -> dict:
    sizes: list[int] = []
    try:
        sizes = [s for s in repo.recent_lawn_sizes(zone.key, SAMPLE_SIZE) if s]
    except Exception:            # never block the address check on this
        sizes = []
    recent = len(sizes) >= MIN_SAMPLE
    return {"sqft": int(round(median(sizes) / 100) * 100) if recent else zone.yard_sqft,
            "full_sqft": zone.full_property_sqft,
            "basis": "recent" if recent else "typical", "sample": len(sizes), "zone_name": zone.name}


def scope_sqft(repo, zone: ServiceZone, scope: str) -> int:
    """The size the server prices for a 'what to mow' choice (never the browser's number)."""
    est = estimate_lawn(repo, zone)
    return est["full_sqft"] if scope == "scope_full" else est["sqft"]
