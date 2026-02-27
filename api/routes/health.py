"""Health check endpoints."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """Liveness probe."""
    return {"status": "ok"}


@router.get("/ready")
async def ready():
    """Readiness probe."""
    return {"status": "ready"}
