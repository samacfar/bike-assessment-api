import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from supabase import Client

from app.db import get_supabase
from app.claude_client import run_assessment

router = APIRouter(tags=["assess"])

MAX_BRAND_ENTRIES_UNKNOWN = 10


class AssessRequest(BaseModel):
    images: list[str] = Field(
        ...,
        min_length=1,
        description="List of base64-encoded bike photos (JPEG). Min 1, max 6.",
    )
    session_id: str | None = None
    suspected_brand: str | None = None


class AssessResponse(BaseModel):
    accuracy_log_id: str          # ID to pass to /save for linking
    session_id: str
    assessment: dict
    brand_reference_used: list[str]
    model_used: str


def fetch_brand_entries(supabase: Client, suspected_brand: str | None) -> list[dict]:
    try:
        if suspected_brand:
            result = (
                supabase.table("brand_reference")
                .select("brand, reference_data")
                .ilike("brand", suspected_brand.strip())
                .limit(1)
                .execute()
            )
        else:
            result = (
                supabase.table("brand_reference")
                .select("brand, reference_data")
                .limit(MAX_BRAND_ENTRIES_UNKNOWN)
                .execute()
            )
        rows = result.data or []
        return [row["reference_data"] for row in rows if row.get("reference_data")]
    except Exception as e:
        print(f"[WARN] brand_reference lookup failed: {e}")
        return []


@router.post("/assess", response_model=AssessResponse)
async def assess_bike(
    body: AssessRequest,
    supabase: Client = Depends(get_supabase),
):
    if len(body.images) > 6:
        raise HTTPException(status_code=400, detail="Maximum 6 images per assessment.")

    # ── Fetch brand fingerprints ──────────────────────────────────────────────
    brand_entries = fetch_brand_entries(supabase, body.suspected_brand)
    brand_names_used = [e.get("brand", "") for e in brand_entries]

    # ── Run Claude assessment ─────────────────────────────────────────────────
    try:
        assessment, model_used = run_assessment(body.images, brand_entries)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Claude API error: {str(e)}")

    # ── Write to accuracy_log only — no verified data yet ────────────────────
    accuracy_log_id = str(uuid.uuid4())
    session_id = body.session_id or str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        supabase.table("accuracy_log").insert({
            "id": accuracy_log_id,
            "session_id": session_id,
            "ai_raw_output": assessment,
            "model_used": model_used,
            "brand_reference_used": brand_names_used,
            "image_count": len(body.images),
            "human_verdict": None,       # set by /save
            "created_at": timestamp,
        }).execute()
    except Exception as e:
        print(f"[WARN] accuracy_log insert failed: {e}")

    return AssessResponse(
        accuracy_log_id=accuracy_log_id,
        session_id=session_id,
        assessment=assessment,
        brand_reference_used=brand_names_used,
        model_used=model_used,
    )
