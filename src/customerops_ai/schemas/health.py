"""Health endpoint response contract."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """A successful process liveness response."""

    status: Literal["ok"]
