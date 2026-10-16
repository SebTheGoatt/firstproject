"""Write customer_audit.txt (count + addresses of active customers) to the repo root.

Run it on your own computer; the Supabase key never goes in chat:

    $env:SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"
    $env:SUPABASE_SERVICE_ROLE_KEY = "sb_secret_..."
    python property-dispatch/tools/customer_audit.py

"Active" = the customer has at least one job that is not cancelled.
MOCK practice customers are left out and counted separately.
"""
import json
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fetch(url: str, key: str) -> list[dict]:
    query = "/rest/v1/customers?select=name,jobs(address,formatted_address,status)"
    req = urllib.request.Request(
        url.rstrip("/") + query, headers={"apikey": key, "Authorization": f"Bearer {key}"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def main() -> int:
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY first (see the top of this file).")
        return 1
    active, mock = [], 0
    for c in fetch(url, key):
        if c["name"].startswith("MOCK "):
            mock += 1
            continue
        jobs = [j for j in c["jobs"] if j["status"] != "cancelled"]
        if jobs:
            active.append(sorted({j["formatted_address"] or j["address"] for j in jobs}))
    addresses = sorted({a for group in active for a in group})
    lines = [
        f"Customer audit - {date.today().isoformat()}",
        "Active = at least one job that is not cancelled. MOCK practice customers excluded.",
        "",
        f"Total active customers: {len(active)}",
        f"Unique service addresses: {len(addresses)}",
        f"MOCK customers skipped: {mock}",
        "",
        "Addresses:",
        *[f"  {i}. {a}" for i, a in enumerate(addresses, 1)],
    ]
    (ROOT / "customer_audit.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved {ROOT / 'customer_audit.txt'}: {len(active)} active customers, {len(addresses)} addresses.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
