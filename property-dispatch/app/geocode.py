"""Address → latitude/longitude via OpenStreetMap Nominatim (free, no key).

Nominatim policy: max 1 request/second and an identifying User-Agent.
Intake volume for a local service business is far below that, but calls are
still serialized with a lock + minimum spacing to stay compliant.
"""

import threading
import time

import httpx

from .config import Settings
from .models import GeoPoint


class GeocodingError(Exception):
    """Address could not be resolved (customer should fix the input)."""


class GeocoderUnavailable(GeocodingError):
    """Upstream outage or rate limit (customer should retry)."""


class NominatimGeocoder:
    MIN_INTERVAL_S = 1.0

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=10)
        self._lock = threading.Lock()
        self._last_call = 0.0

    def geocode(self, address: str) -> GeoPoint:
        params = {
            "q": address,
            "format": "jsonv2",
            "limit": 1,
            "countrycodes": self.settings.geocoder_country,
        }
        headers = {"User-Agent": self.settings.geocoder_user_agent}

        with self._lock:
            wait = self.MIN_INTERVAL_S - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self.client.get(f"{self.settings.nominatim_url}/search", params=params, headers=headers)
                resp.raise_for_status()
                results = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise GeocoderUnavailable("Address lookup is temporarily unavailable. Please try again in a minute.") from exc
            finally:
                self._last_call = time.monotonic()

        if not results:
            raise GeocodingError("We couldn't find that address. Please include street, city and ZIP.")

        hit = results[0]
        return GeoPoint(
            lat=float(hit["lat"]),
            lng=float(hit["lon"]),
            formatted_address=hit.get("display_name", address),
        )
