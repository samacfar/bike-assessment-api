from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from supabase import Client

from app.db import get_supabase

router = APIRouter(tags=["save"])


class AuthorisedField(BaseModel):
    field: str
    value: str


class CorrectionRow(BaseModel):
    field: str
    note: str = ""
    corrected_value: str = ""


class SaveRequest(BaseModel):
    assessment_id:   str | None = None
    session_id:      str | None = None
    accuracy_log_id: str | None = None
    make:            str | None = None
    model:           str | None = None
    authorised_fields: list[AuthorisedField] = Field(default=[])
    corrections:     list[CorrectionRow] = Field(default=[])


class SaveResponse(BaseModel):
    saved_fields:      int
    saved_corrections: int
    timestamp:         str


@router.post("/save", response_model=SaveResponse)
async def save_assessment(
    body: SaveRequest,
    supabase: Client = Depends(get_supabase),
):
    timestamp = datetime.now(timezone.utc).isoformat()
    saved_fields = 0
    saved_corrections = 0

    # Update accuracy_log with human-verified verdict
    if body.accuracy_log_id and body.authorised_fields:
        verified_summary = {f.field: f.value for f in body.authorised_fields}
        try:
            supabase.table("accuracy_log").update({
                "human_verdict":   "accepted",
                "corrected_value": str(verified_summary),
            }).eq("id", body.accuracy_log_id).execute()
            saved_fields = len(body.authorised_fields)
        except Exception as e:
            print(f"[WARN] accuracy_log update failed: {e}")

    # Save corrections — these are the learning signals
    if body.corrections:
        records = []
        for c in body.corrections:
            if not c.corrected_value:
                continue
            records.append({
                "make":            body.make,
                "model":           body.model,
                "field":           c.field,
                "challenge_note":  c.note or None,
                "corrected_value": c.corrected_value,
                "created_at":      timestamp,
            })
        if records:
            try:
                supabase.table("corrections").insert(records).execute()
                saved_corrections = len(records)
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Corrections save failed: {str(e)}")

    return SaveResponse(
        saved_fields=saved_fields,
        saved_corrections=saved_corrections,
        timestamp=timestamp,
    )
