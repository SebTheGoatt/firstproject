"""Runtime configuration, loaded from environment variables / .env."""

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Storage -------------------------------------------------------
    # "supabase" in production; "memory" for local demos and tests.
    data_backend: str = "supabase"
    supabase_url: str = ""
    supabase_service_role_key: str = ""

    # --- Business base (Spring, TX) -----------------------------------
    business_timezone: str = "America/Chicago"
    base_lat: float = 30.0799
    base_lng: float = -95.4172
    # End point defaults to the base; override for a different yard/dump site.
    end_lat: float | None = None
    end_lng: float | None = None
    crew_start_time: str = "08:00"  # local time the crew leaves the base

    # --- Runway quota & freeze ----------------------------------------
    freeze_hour: int = 20           # 8 PM local: next day is locked
    daily_job_quota: int = 25       # max active jobs per service day
    booking_horizon_days: int = 60

    # --- Routing ------------------------------------------------------
    osrm_url: str = "https://router.project-osrm.org"
    optimize_for: str = "duration"  # "duration" | "distance"
    solver_time_limit_s: int = 10

    # --- Geocoding (Nominatim) ----------------------------------------
    census_geocoder_url: str = "https://geocoding.geo.census.gov/geocoder"
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    # Nominatim's usage policy requires an identifying User-Agent with a real
    # contact; placeholder domains like example.com are rejected with 403.
    geocoder_user_agent: str = "property-dispatch/1.0"
    geocoder_country: str = "us"

    # --- Twilio -------------------------------------------------------
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    business_name: str = "Spring Property Services"

    # --- Security -----------------------------------------------------
    crew_access_token: str = "change-me"   # crew dashboard + complete API
    webhook_secret: str = "change-me"      # external webhook callers
    cron_secret: str = "change-me"         # HTTP-triggered nightly run

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.business_timezone)

    @property
    def start_point(self) -> tuple[float, float]:
        return (self.base_lat, self.base_lng)

    @property
    def end_point(self) -> tuple[float, float]:
        if self.end_lat is None or self.end_lng is None:
            return self.start_point
        return (self.end_lat, self.end_lng)

    @property
    def twilio_enabled(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number)


@lru_cache
def get_settings() -> Settings:
    return Settings()
