"""Runtime configuration, loaded from environment variables / .env."""

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, Field
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
    # First stop around 7 AM. Texas has no statewide lawn-hours law; cities and
    # HOAs set noise rules, and 7 AM is a common earliest start. Change if needed.
    crew_start_time: str = "07:00"  # local time the crew leaves the base

    # --- Runway quota & freeze ----------------------------------------
    freeze_hour: int = 17           # 5 PM local (close of business): next day locks and its route is built
    daily_job_quota: int = 25       # max active jobs per service day
    booking_horizon_days: int = 60

    # --- Routing ------------------------------------------------------
    osrm_url: str = "https://router.project-osrm.org"
    optimize_for: str = "duration"  # "duration" | "distance"
    solver_time_limit_s: int = 10

    # --- Geocoding (Nominatim) ----------------------------------------
    census_geocoder_url: str = "https://geocoding.geo.census.gov/geocoder"
    # Optional Google Maps browser key for the address dropdowns on the home page and booking
    # form (Places API (New)). Restrict it to your site's address in Google Cloud. Either name works.
    google_maps_browser_key: str = Field(
        default="", validation_alias=AliasChoices("GOOGLE_MAPS_BROWSER_KEY", "GOOGLE_MAPS_API_KEY", "google_maps_browser_key"))
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    # Nominatim's usage policy requires an identifying User-Agent with a real
    # contact; placeholder domains like example.com are rejected with 403.
    geocoder_user_agent: str = "property-dispatch/1.0"
    geocoder_country: str = "us"

    # --- Twilio -------------------------------------------------------
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    business_name: str = "Semper Green Lawn Care"
    # Shown under the "Operational Base & Liability Allocation" line at booking, ONLY when the owner sets them.
    # Put the real amount from your insurance certificate (e.g. "$2M"); leave blank if you don't carry it.
    liability_coverage: str = ""
    crew_background_checked: bool = False    # set true only if every crew member has passed a background check
    # Used in texts sent outside a web request (e.g. the completion webhook).
    public_base_url: str = ""

    # --- Push notifications (leave blank to turn them off) --------------
    # Make a key pair at /push-setup; both values go only in Render's environment.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""      # "mailto:you@example.com"; defaults to PUBLIC_BASE_URL

    # --- Dispatch assistant (Ollama; leave OLLAMA_BASE_URL blank to turn it off) -----
    ollama_base_url: str = ""          # e.g. http://localhost:11434/v1, your tunnel + /v1, or https://ollama.com/v1
    ollama_model: str = "qwen2.5:14b"
    ollama_api_key: str = ""           # only for Ollama's cloud; keep it in Render, never in code
    ollama_basic_auth: str = ""        # "user:password" for a password-protected tunnel to your own computer
    ollama_timeout_s: float = 90.0

    # --- AI agent access (StarNet): leave blank to keep it off. See app/agent_api.py ---
    agent_key_read: str = ""     # can look only
    agent_key_ops: str = ""      # can look, build a day's route, and trigger the "on the way" message
    agent_actions_paused: bool = False   # AGENT_ACTIONS_PAUSED=true: the owner's off-switch for everything agents can DO

    # --- Donations: split 33% / 33% / 34% (see app/charity.py) ----------
    # Rename to the specific VFW post, hospital NICU and youth program you give to.
    charity_vfw_name: str = "Veterans of Foreign Wars (VFW)"
    charity_nicu_name: str = "Neonatal intensive care (NICU) families"
    charity_youth_name: str = "At-risk youth programs"
    # Set the official name only once the local program has said yes (e.g. "Marine Toys for Tots, Liberty County").
    charity_toys_name: str = "Holiday toy drive for local kids"
    # Google review link (Google Business Profile → "Ask for reviews"). Blank = no review requests are sent.
    google_review_url: str = ""
    review_requests_every_min: int = 5     # how often the web process looks for jobs to follow up on (0 = off)

    # --- Stripe card payments (leave blank to take cash only) ---------
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # --- Security -----------------------------------------------------
    crew_access_token: str = "change-me"   # crew dashboard + complete API
    webhook_secret: str = "change-me"      # external webhook callers
    cron_secret: str = "change-me"         # HTTP-triggered nightly run

    @property
    def agent_enabled(self) -> bool:
        return bool(self.ollama_base_url)

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key and (self.vapid_subject or self.public_base_url))

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
    def stripe_enabled(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_webhook_secret)

    @property
    def twilio_enabled(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number)


@lru_cache
def get_settings() -> Settings:
    return Settings()


LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "testserver")


def site_url(settings: "Settings", request) -> str:
    """The site's public address for links we send out (texts, Stripe return pages).

    PUBLIC_BASE_URL wins when it's set. Otherwise the request's own address is used, upgraded
    to https for any real host: Render ends TLS at its proxy, so the app can see plain http.
    """
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    base = str(request.base_url).rstrip("/")
    host = request.url.hostname or ""
    if base.startswith("http://") and host not in LOCAL_HOSTS:
        base = "https://" + base[len("http://"):]
    return base
