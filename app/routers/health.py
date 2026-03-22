from datetime import datetime, timezone
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "bikeid-assessment-api",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
