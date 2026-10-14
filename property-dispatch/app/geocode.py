"""Customer address → latitude/longitude, using free services only.

Lookup order (first hit wins):
  1. U.S. Census Bureau geocoder: house-number accuracy for most U.S.
     addresses, no key or account needed.
  2. OpenStreetMap Nominatim with the address as typed.
  3. Nominatim retries without the house number, then with street + ZIP only.
     Brand-new subdivisions often aren't in the Census data yet, and
     OSM rarely has house numbers, so these find the street instead.

Nominatim policy: max 1 request/second and an identifying User-Agent, so
those calls are serialized with a lock + minimum spacing.
"""

import re
import threading
import time

import httpx

from .config import Settings
from .models import GeoPoint


class GeocodingError(Exception):
    """Address could not be resolved (customer should fix the input)."""


class GeocoderUnavailable(GeocodingError):
    """Upstream outage or rate limit (customer should retry)."""


class _ServiceDown(Exception):
    pass


HOUSE_NUMBER = re.compile(r"^\s*\d+[A-Za-z]?\s+")
STATE_ZIP = re.compile(r"\b([A-Za-z]{2})\.?,?\s+(\d{5})(?:-\d{4})?\s*$")


def street_variants(address: str) -> list[str]:
    """Looser spellings of an address for a second try, most specific first."""
    no_number = HOUSE_NUMBER.sub("", address, count=1).strip()
    parts = [p.strip() for p in no_number.split(",") if p.strip()]
    variants = [", ".join(parts)]
    m = STATE_ZIP.search(address)
    if m and parts:
        variants.append(f"{parts[0]}, {m.group(1).upper()} {m.group(2)}")  # drop the city
    seen, out = {address.strip().lower()}, []
    for v in variants:
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def _tidy_census(matched: str) -> str:
    """'4726 WHISPERING ROCK LN, SPRING, TX, 77388' → '4726 Whispering Rock Ln, Spring, TX 77388'."""
    parts = [p.strip() for p in matched.split(",")]
    if len(parts) >= 4:
        street, city, state, zip_ = parts[0], parts[1], parts[2], parts[3]
        return f"{street.title()}, {city.title()}, {state.upper()} {zip_}"
    return matched.title()


class AddressGeocoder:
    MIN_INTERVAL_S = 1.0  # Nominatim spacing

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=10)
        self._lock = threading.Lock()
        self._last_call = 0.0

    # --- services -----------------------------------------------------
    def _census(self, address: str) -> GeoPoint | None:
        try:
            resp = self.client.get(
                f"{self.settings.census_geocoder_url}/locations/onelineaddress",
                params={"address": address, "benchmark": "Public_AR_Current", "format": "json"},
            )
            resp.raise_for_status()
            matches = resp.json()["result"]["addressMatches"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise _ServiceDown from exc
        if not matches:
            return None
        m = matches[0]
        return GeoPoint(
            lat=float(m["coordinates"]["y"]),
            lng=float(m["coordinates"]["x"]),
            formatted_address=_tidy_census(m["matchedAddress"]),
            precision="address",
        )

    def _nominatim(self, query: str, precision: str) -> GeoPoint | None:
        params = {"q": query, "format": "jsonv2", "limit": 1, "countrycodes": self.settings.geocoder_country}
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
                raise _ServiceDown from exc
            finally:
                self._last_call = time.monotonic()
        if not isinstance(results, list) or not results:
            return None
        hit = results[0]
        # OSM usually returns the street, not the house; only trust "address" for a house hit.
        if hit.get("addresstype") not in ("house", "building") and hit.get("type") != "house":
            precision = "street"
        return GeoPoint(
            lat=float(hit["lat"]),
            lng=float(hit["lon"]),
            formatted_address=hit.get("display_name", query),
            precision=precision,
        )

    # --- public -------------------------------------------------------
    def geocode(self, address: str) -> GeoPoint:
        attempts = [lambda: self._census(address), lambda: self._nominatim(address, "address")]
        attempts += [lambda v=v: self._nominatim(v, "street") for v in street_variants(address)]

        answered = 0
        for attempt in attempts:
            try:
                hit = attempt()
            except _ServiceDown:
                continue
            answered += 1
            if hit is not None:
                return hit

        if answered == 0:
            raise GeocoderUnavailable("Address lookup is temporarily unavailable. Please try again in a minute.")
        raise GeocodingError(
            "We couldn't find that address. Please check the street name and include city, state and ZIP."
        )


# Backwards-compatible name used by earlier code and tests.
NominatimGeocoder = AddressGeocoder
