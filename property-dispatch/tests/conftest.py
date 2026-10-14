import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import MemoryRepository
from app.main import create_app
from app.models import GeoPoint

# Points inside the Spring zone, plus one per other zone and one outside all.
ADDRESSES = {
    "A": (30.1500, -95.3900),
    "B": (30.1200, -95.3000),
    "C": (30.1700, -95.4000),
    "D": (30.1300, -95.3500),
    "E": (30.1600, -95.3200),
    "Spl": (30.2330, -95.1610),   # Splendora → I-69 spine
    "Clv": (30.3400, -94.9800),   # Cleveland hub box
    "Old": (30.0799, -95.4172),   # Old Town Spring → outside every zone
}


class FakeGeocoder:
    def geocode(self, address: str) -> GeoPoint:
        key = address.split()[0]
        lat, lng = ADDRESSES[key]
        return GeoPoint(lat=lat, lng=lng, formatted_address=f"{address}, Spring, TX")


class FakeSMS:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send_sms(self, to: str, body: str) -> str:
        self.sent.append((to, body))
        return f"SM{len(self.sent):04d}"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        data_backend="memory",
        osrm_url="",            # tests never hit the network
        solver_time_limit_s=1,
        crew_access_token="crew",
        webhook_secret="hook",
        cron_secret="cron",
    )


@pytest.fixture
def repo() -> MemoryRepository:
    return MemoryRepository()


@pytest.fixture
def sms() -> FakeSMS:
    return FakeSMS()


@pytest.fixture
def client(settings, repo, sms) -> TestClient:
    return TestClient(create_app(settings, repo=repo, geocoder=FakeGeocoder(), sms=sms))
