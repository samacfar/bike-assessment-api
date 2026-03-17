import uuid
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from supabase import Client

from app.db import get_supabase
from app.claude_client import run_assessment

router = APIRouter(tags=["assess"])

MAX_BRAND_ENTRIES_UNKNOWN = 10  # cap to avoid oversized prompts


class AssessRequest(BaseModel):
    images: list[str] = Field(
        ...,
        min_length=1,
        description="List of base64-encoded bike photos (JPEG). Min 1, max 6.",
    )
    session_id: str | None = Field(
        None,
        description="Optional session ID to associate this assessment with an existing record.",
    )
    suspected_brand: str | None = Field(
        None,
        description=(
            "Optional brand name hint (e.g. 'Specialized'). "
            "If provided, only that brand's fingerprint is injected. "
            "If omitted, all brand fingerprints are injected."
        ),
    )


class AssessResponse(BaseModel):
    assessment_id: str
    session_id: str
    assessment: dict
    brand_reference_used: list[str]


def fetch_brand_entries(supabase: Client, suspected_brand: str | None) -> list[dict]:
    """
    Query brand_reference table.
    - If suspected_brand is given: fetch that one brand only.
    - If unknown: fetch all entries (capped at MAX_BRAND_ENTRIES_UNKNOWN).
    Returns list of reference_data dicts.
    """
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
        # Each row has reference_data as the full fingerprint dict
        return [row["reference_data"] for row in rows if row.get("reference_data")]

    except Exception as e:
        # Non-fatal — log and continue without brand reference
        print(f"[WARN] brand_reference lookup failed: {e}")
        return []


@router.post("/assess", response_model=AssessResponse)
async def assess_bike(
    body: AssessRequest,
    supabase: Client = Depends(get_supabase),
):
    if len(body.images) > 6:
        raise HTTPException(status_code=400, detail="Maximum 6 images per assessment.")

    # ── Stage 1: fetch brand reference fingerprints ──────────────────────────
    brand_entries = fetch_brand_entries(supabase, body.suspected_brand)
    brand_names_used = [e.get("brand", "") for e in brand_entries]

    if brand_entries:
        scope = body.suspected_brand or "all brands"
        print(f"[INFO] Brand reference injected for: {scope} ({len(brand_entries)} entries)")
    else:
        print("[INFO] No brand reference entries available — running without fingerprint context")

    # ── Stage 2: run Claude Vision assessment ────────────────────────────────
    try:
        assessment = run_assessment(body.images, brand_entries)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Claude API error: {str(e)}")

    # ── Stage 3: persist to Supabase ─────────────────────────────────────────
    assessment_id = str(uuid.uuid4())
    session_id = body.session_id or str(uuid.uuid4())

    try:
        supabase.table("assessments").insert({
            "id": assessment_id,
            "session_id": session_id,
            "assessment": assessment,
            "image_count": len(body.images),
        }).execute()
    except Exception as e:
        print(f"[WARN] Supabase insert failed: {e}")

    return AssessResponse(
        assessment_id=assessment_id,
        session_id=session_id,
        assessment=assessment,
        brand_reference_used=brand_names_used,
    )