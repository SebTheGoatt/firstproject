"""Run the app locally with made-up demo data, for page checks and screenshots. Nothing touches the real database.

    python3 .claude/skills/post-one-standard/scripts/demo_server.py --port 8940 [--osrm] [--launch 2027-03-01]

Use a new port every run (never pkill: it takes the shell down with it). Demo data, all on next Monday (Spring):
five cash bookings "Customer A–E" at the test addresses with a built route, one paid "Sponsor a neighbor's mow"
booking, and two private nominations. Owner token for page_check.py --token: crew-test-token-123.
--osrm uses the public road router for the dispatch board's real road path (slower; off by default).
--launch sets LAUNCH_DATE (pre-orders open until then); the demo bookings move to the first Monday on or after it.
Prints the demo day and the pay page path, then serves until stopped.
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

APP = Path(__file__).resolve().parents[4] / "property-dispatch"
sys.path.insert(0, str(APP))

import uvicorn  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.community as community  # noqa: E402
import app.nightly as nightly  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import MemoryRepository  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.conftest import FakeGeocoder  # noqa: E402  (knows "100 A..E Example Rd", all in Spring)

TOKEN = "crew-test-token-123"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--osrm", action="store_true")
    ap.add_argument("--launch", type=date.fromisoformat)
    a = ap.parse_args()
    community.check_area_day = lambda day, zone: None
    nightly.one_area = lambda jobs, day: (jobs, [])
    kw = {} if a.osrm else {"osrm_url": ""}
    if a.launch:
        kw["launch_date"] = a.launch
    settings = Settings(_env_file=None, data_backend="memory", crew_access_token=TOKEN, **kw)
    repo = MemoryRepository()
    app = create_app(settings, repo=repo, geocoder=FakeGeocoder())
    c = TestClient(app)
    today = date.today()
    monday = today + timedelta(days=(0 - today.weekday()) % 7 or 7)
    if a.launch and monday < a.launch:
        monday = a.launch + timedelta(days=(0 - a.launch.weekday()) % 7)

    def book(i, letter, **extra):
        r = c.post("/api/jobs", json={"name": f"Customer {letter}", "phone": f"(281) 555-01{i:02d}",
                                      "address": f"100 {letter} Example Rd", "service": "mowing",
                                      "lawn_sqft": 5000 + 1500 * i, "yard_type": "STANDARD",
                                      "scheduled_date": monday.isoformat(), "payment_method": "cash", **extra})
        assert r.status_code == 201, r.text
        return r.json()

    for i, letter in enumerate("ABCDE"):
        book(i, letter, add_ons=["bin_cleaning"] if i % 2 else [])
    print("route:", nightly.run_nightly(repo, settings, monday))
    sponsor = book(9, "A", add_ons=["sponsor_mow"])
    repo.mark_paid(sponsor["id"], method="card", amount_paid=sponsor["total"], donation=0.0)
    unpaid = book(8, "B")
    for n in ("D", "E"):
        c.post("/api/nominations", json={"zone_key": "SPRING_LUXURY_LOOP", "nominee_name": f"Neighbor {n}",
                                         "nominee_address": f"100 {n} Example Rd", "nominee_phone": "(281) 555-0199",
                                         "reason": "Recovering from surgery this month.", "nominator_name": "Friend",
                                         "nominator_contact": "friend@example.com"})
    print(f"demo day: {monday}  (dispatch: /owner/dispatch?day={monday})")
    print(f"pay page: /pay/{repo.jobs[unpaid['id']].get('pay_token')}")
    print(f"owner token: {TOKEN}  ·  http://127.0.0.1:{a.port}")
    uvicorn.run(app, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
