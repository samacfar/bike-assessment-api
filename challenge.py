import uuid
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from supabase import Client

from app.db import get_supabase
from app.claude_client import run_challenge

router = APIRouter(tags=["challenge"])


class ChallengeRequest(BaseModel):
    assessment_id: str = Field(..., description="ID of the original assessment to challenge.")
    component_name: str = Field(
        ...,
        description="The component key to re-examine, e.g. 'groupset', 'wheels', 'brakes'.",
    )
    images: list[str] = Field(
        ...,
        min_length=1,
        description="Base64-encoded images (same set as original, or updated photos).",
    )


class ChallengeResponse(BaseModel):
    challenge_id: str
    assessment_id: str
    component_name: str
    result: dict


@router.post("/challenge", response_model=ChallengeResponse)
async def challenge_component(
    body: ChallengeRequest,
    supabase: Client = Depends(get_supabase),
):
    # Fetch original assessment from Supabase
    try:
        result = (
            supabase.table("assessments")
            .select("assessment")
            .eq("id", body.assessment_id)
            .single()
            .execute()
        )
        original = result.data
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Assessment not found: {str(e)}")

    components = original.get("assessment", {}).get("components", {})
    previous = components.get(body.component_name)

    if previous is None:
        raise HTTPException(
            status_code=400,
            detail=f"Component '{body.component_name}' not found in original assessment.",
        )

    try:
        revised = run_challenge(body.images, body.component_name, previous)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Claude API error: {str(e)}")

    challenge_id = str(uuid.uuid4())

    try:
        supabase.table("challenges").insert({
            "id": challenge_id,
            "assessment_id": body.assessment_id,
            "component_name": body.component_name,
            "previous_assessment": previous,
            "revised_assessment": revised,
        }).execute()
    except Exception as e:
        print(f"[WARN] Supabase insert failed: {e}")

    return ChallengeResponse(
        challenge_id=challenge_id,
        assessment_id=body.assessment_id,
        component_name=body.component_name,
        result=revised,
    )