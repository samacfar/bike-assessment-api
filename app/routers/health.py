from fastapi import APIRouter
from datetime import datetime, timezone

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "bike-assessment-api",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }