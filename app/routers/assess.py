import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from supabase import Client

from app.db import get_supabase
from app.claude_client import run_assessment, run_challenge

router = APIRouter(tags=["assess"])


class AssessRequest(BaseModel):
    images: list[str] = Field(..., min_length=1, max_length=1,
                               description="Single base64-encoded JPEG image")


class ChallengeRequest(BaseModel):
    image: str = Field(..., description="Base64-encoded JPEG image")
    field: str = Field(..., description="Field name to resolve e.g. 'Trim Level'")
    confirmed_facts: str = Field(default="", description="Comma-separated confirmed field values")
    note: str = Field(default="", description="Optional user correction note")
    accuracy_log_id: str | None = None


class AssessResponse(BaseModel):
    assessment_id: str
    accuracy_log_id: str
    session_id: str
    raw_text: str


class ChallengeResponse(BaseModel):
    field: str
    result: str


@router.post("/assess", response_model=AssessResponse)
async def assess_bike(
    body: AssessRequest,
    supabase: Client = Depends(get_supabase),
):
    try:
        raw_text = run_assessment(body.images[0])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Claude API error: {str(e)}")

    assessment_id   = str(uuid.uuid4())
    accuracy_log_id = str(uuid.uuid4())
    session_id      = str(uuid.uuid4())
    timestamp       = datetime.now(timezone.utc).isoformat()

    # Save raw assessment to Supabase
    try:
        supabase.table("assessments").insert({
            "id":          assessment_id,
            "session_id":  session_id,
            "assessment":  {"raw_text": raw_text},
            "image_count": 1,
            "created_at":  timestamp,
        }).execute()

        supabase.table("accuracy_log").insert({
            "id":                 accuracy_log_id,
            "assessment_id":      assessment_id,
            "component_field":    "full_assessment",
            "ai_original_answer": raw_text,
            "human_verdict":      "pending",
            "corrected_value":    None,
            "created_at":         timestamp,
        }).execute()
    except Exception as e:
        # Non-fatal — return result even if DB write fails
        print(f"[WARN] Supabase write failed: {e}")

    return AssessResponse(
        assessment_id=assessment_id,
        accuracy_log_id=accuracy_log_id,
        session_id=session_id,
        raw_text=raw_text,
    )


@router.post("/challenge", response_model=ChallengeResponse)
async def challenge_field(
    body: ChallengeRequest,
    supabase: Client = Depends(get_supabase),
):
    try:
        result = run_challenge(
            body.image,
            body.field,
            body.confirmed_facts,
            body.note,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Claude API error: {str(e)}")

    # Log the challenge
    try:
        supabase.table("corrections").insert({
            "id":              str(uuid.uuid4()),
            "session_id":      None,
            "make":            None,
            "model":           None,
            "field":           body.field,
            "challenge_note":  body.note or None,
            "corrected_value": result,
            "created_at":      datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        print(f"[WARN] Corrections write failed: {e}")

    return ChallengeResponse(field=body.field, result=result)
