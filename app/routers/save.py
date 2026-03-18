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
    note: str | None = None
    corrected_value: str


class SaveRequest(BaseModel):
    make: str
    model_family: str
    authorised_fields: list[AuthorisedField] = Field(default_factory=list)
    corrections: list[Correction] = Field(default_factory=list)


class SaveResponse(BaseModel):
    session_id: str
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
    session_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    # ── Write authorised fields to assessments table ──────────────────────────
    if body.authorised_fields:
        assessment_record = {
            "id": session_id,
            "session_id": session_id,
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
                "session_id": session_id,
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

    return SaveResponse(
        session_id=session_id,
        make=body.make,
        model_family=body.model_family,
        authorised_count=len(body.authorised_fields),
        corrections_count=len(body.corrections),
        timestamp=timestamp,
    )