import uuid
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from supabase import Client

from app.db import get_supabase
from app.claude_client import run_assessment

router = APIRouter(tags=["assess"])


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


class AssessResponse(BaseModel):
    assessment_id: str
    session_id: str
    assessment: dict


@router.post("/assess", response_model=AssessResponse)
async def assess_bike(
    body: AssessRequest,
    supabase: Client = Depends(get_supabase),
):
    if len(body.images) > 6:
        raise HTTPException(status_code=400, detail="Maximum 6 images per assessment.")

    try:
        assessment = run_assessment(body.images)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Claude API error: {str(e)}")

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
        # Log but don't fail — return assessment even if DB write fails
        print(f"[WARN] Supabase insert failed: {e}")

    return AssessResponse(
        assessment_id=assessment_id,
        session_id=session_id,
        assessment=assessment,
    )