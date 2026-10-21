"""Chat's public input, response, and consistent error contracts."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from customerops_ai.schemas.knowledge import SourceReference


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=4000, strict=True)
    conversation_id: UUID | None = None


class ToolExecution(BaseModel):
    name: str
    status: Literal["ok", "error"]
    duration_ms: float
    error_code: str | None = None


class ChatResponse(BaseModel):
    conversation_id: UUID
    message: str
    tool_executions: list[ToolExecution]
    sources: list[SourceReference] = Field(default_factory=list)


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
