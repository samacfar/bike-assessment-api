"""
Seed script — loads bike_brand_visual_fingerprint_seed.json into Supabase brand_reference table.
Uses only built-in Python libraries (urllib) — no pip installs needed.

Usage:
    python seed_brands.py

Requires .env file with:
    SUPABASE_URL=...
    SUPABASE_SERVICE_ROLE_KEY=...
"""

import json
import urllib.request
import urllib.error
import os
from datetime import datetime, timezone

# ── Load .env manually (no dotenv package needed) ────────────────────────────
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        raise FileNotFoundError(".env file not found — make sure it exists in the project root")
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

load_env()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
JSON_FILE = os.path.join(os.path.dirname(__file__), "bike_brand_visual_fingerprint_seed.json")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")


def supabase_upsert(records: list) -> dict:
    url = f"{SUPABASE_URL}/rest/v1/brand_reference"
    payload = json.dumps(records).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Prefer": "resolution=merge-duplicates",  # upsert on conflict
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode()
            return {"status": resp.status, "body": body}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Supabase error {e.code}: {body}")


def main():
    print(f"Loading {JSON_FILE}...")
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        brands = json.load(f)

    print(f"Found {len(brands)} brands.")

    timestamp = datetime.now(timezone.utc).isoformat()
    records = [
        {
            "brand": entry["brand"],
            "reference_data": entry,
            "updated_at": timestamp,
        }
        for entry in brands
    ]

    print(f"Upserting into brand_reference table...")
    result = supabase_upsert(records)
    print(f"Done. Status: {result['status']}")
    for r in records:
        print(f"  ✓ {r['brand']}")


if __name__ == "__main__":
    main()