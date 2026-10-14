import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import MemoryRepository
from app.main import create_app
from app.models import GeoPoint

# A handful of real-ish points around Spring, TX.
ADDRESSES = {
    "A": (30.1320, -95.4530),
    "B": (30.0450, -95.3800),
    "C": (30.1100, -95.4400),
    "D": (30.0600, -95.3900),
    "E": (30.0900, -95.4100),
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
