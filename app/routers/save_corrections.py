import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from supabase import Client

from app.db import get_supabase

router = APIRouter(tags=["save-corrections"])


class CorrectionRow(BaseModel):
    make: str | None = None
    model: str | None = None
    field: str = Field(..., description="The component or field that was corrected e.g. 'groupset', 'make'")
    challenge_note: str | None = Field(None, description="The user's challenge note explaining the correction")
    corrected_value: str = Field(..., description="The corrected value")


class SaveCorrectionsRequest(BaseModel):
    corrections: list[CorrectionRow] = Field(..., min_length=1)
    session_id: str | None = None


class SaveCorrectionsResponse(BaseModel):
    saved: int
    session_id: str
    timestamp: str


@router.post("/save-corrections", response_model=SaveCorrectionsResponse)
async def save_corrections(
    body: SaveCorrectionsRequest,
    supabase: Client = Depends(get_supabase),
):
    timestamp = datetime.now(timezone.utc).isoformat()
    session_id = body.session_id or str(uuid.uuid4())

    records = [
        {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "make": row.make,
            "model": row.model,
            "field": row.field,
            "challenge_note": row.challenge_note,
            "corrected_value": row.corrected_value,
            "created_at": timestamp,
        }
        for row in body.corrections
    ]

    try:
        supabase.table("corrections").insert(records).execute()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Supabase insert failed: {str(e)}")

    return SaveCorrectionsResponse(
        saved=len(records),
        session_id=session_id,
        timestamp=timestamp,
    )