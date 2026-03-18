import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from supabase import Client

from app.db import get_supabase

router = APIRouter(tags=["save"])


class AuthorisedField(BaseModel):
    field: str
    value: str


class Correction(BaseModel):
    field: str
    ai_value: str                  # what Claude originally said
    note: str | None = None        # human challenge note
    corrected_value: str           # human-verified correct value


class SaveRequest(BaseModel):
    accuracy_log_id: str = Field(
        ...,
        description="ID returned by /assess. Links verified data back to the AI raw output."
    )
    make: str
    model_family: str
    authorised_fields: list[AuthorisedField] = Field(default_factory=list)
    corrections: list[Correction] = Field(default_factory=list)


class SaveResponse(BaseModel):
    assessment_id: str
    accuracy_log_id: str
    make: str
    model_family: str
    authorised_count: int
    corrections_count: int
    timestamp: str


@router.post("/save", response_model=SaveResponse)
async def save_assessment(
    body: SaveRequest,
    supabase: Client = Depends(get_supabase),
):
    timestamp = datetime.now(timezone.utc).isoformat()
    assessment_id = str(uuid.uuid4())

    # ── Write human-verified assessment to assessments table ─────────────────
    assessment_record = {
        "id": assessment_id,
        "session_id": assessment_id,
        "assessment": {
            "make": body.make,
            "model_family": body.model_family,
            "authorised_fields": [f.model_dump() for f in body.authorised_fields],
        },
        "image_count": 0,
    }
    try:
        supabase.table("assessments").insert(assessment_record).execute()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to write assessment: {str(e)}")

    # ── Write corrections to corrections table ────────────────────────────────
    if body.corrections:
        correction_records = [
            {
                "id": str(uuid.uuid4()),
                "session_id": assessment_id,
                "make": body.make,
                "model": body.model_family,
                "field": c.field,
                "challenge_note": c.note,
                "corrected_value": c.corrected_value,
                "created_at": timestamp,
            }
            for c in body.corrections
        ]
        try:
            supabase.table("corrections").insert(correction_records).execute()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to write corrections: {str(e)}")

    # ── Update accuracy_log with human verdict summary ────────────────────────
    total = len(body.authorised_fields) + len(body.corrections)
    accuracy_score = round(len(body.authorised_fields) / total, 2) if total > 0 else None

    try:
        supabase.table("accuracy_log").update({
            "human_verdict": "completed",
            "accuracy_score": accuracy_score,
            "verified_assessment_id": assessment_id,
        }).eq("id", body.accuracy_log_id).execute()
    except Exception as e:
        print(f"[WARN] accuracy_log update failed: {e}")

    return SaveResponse(
        assessment_id=assessment_id,
        accuracy_log_id=body.accuracy_log_id,
        make=body.make,
        model_family=body.model_family,
        authorised_count=len(body.authorised_fields),
        corrections_count=len(body.corrections),
        timestamp=timestamp,
    )
