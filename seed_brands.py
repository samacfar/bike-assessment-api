"""
Seed script — loads bike_brand_visual_fingerprint_seed.json into Supabase brand_reference table.

Usage:
    pip install supabase python-dotenv
    python seed_brands.py

Requires .env file with:
    SUPABASE_URL=...
    SUPABASE_SERVICE_ROLE_KEY=...
"""

import json
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
JSON_FILE = "bike_brand_visual_fingerprint_seed.json"


def main():
    print(f"Connecting to Supabase...")
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    print(f"Loading {JSON_FILE}...")
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        brands = json.load(f)

    print(f"Found {len(brands)} brands. Upserting into brand_reference table...")

    records = [
        {
            "brand": entry["brand"],
            "reference_data": entry,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        for entry in brands
    ]

    # Upsert — safe to run multiple times, updates existing entries
    result = (
        client.table("brand_reference")
        .upsert(records, on_conflict="brand")
        .execute()
    )

    print(f"Done. {len(records)} brands seeded successfully.")
    for r in records:
        print(f"  ✓ {r['brand']}")


if __name__ == "__main__":
    main()
