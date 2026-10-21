"""Database readiness, separate from process liveness."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from customerops_ai.infrastructure.database import DatabaseSession
from customerops_ai.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={503: {"description": "Database unavailable"}},
)
async def get_readiness(session: DatabaseSession) -> HealthResponse:
    """Probe connectivity and the applied migration; never expose connection details."""
    try:
        revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != "0002_memory":
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database schema is not ready")
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database unavailable") from exc
    return HealthResponse(status="ok")
