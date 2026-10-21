"""Process liveness endpoint; does not assert dependency readiness."""

from fastapi import APIRouter

from customerops_ai.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    """Report that the application can serve HTTP requests."""
    return HealthResponse(status="ok")
