"""Authenticated chat transport; all business work is delegated to services."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from customerops_ai.agents.contracts import LLMProvider
from customerops_ai.core.auth import AuthenticatedCustomer
from customerops_ai.core.config import Settings
from customerops_ai.core.errors import AppError
from customerops_ai.infrastructure.database import DatabaseSession
from customerops_ai.schemas.chat import ChatRequest, ChatResponse, ErrorResponse
from customerops_ai.services.chat import ChatService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


async def get_chat_service(
    request: Request,
    identity: AuthenticatedCustomer,
    session: DatabaseSession,
) -> ChatService:
    provider: LLMProvider | None = request.app.state.llm_provider
    if provider is None:
        raise AppError("agent_not_configured", "The assistant is not configured.", 503)
    settings: Settings = request.app.state.settings
    return ChatService(
        session, provider, settings, identity, getattr(request.app.state, "knowledge", None)
    )


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        code: {"model": ErrorResponse} for code in (401, 404, 409, 422, 429, 500, 502, 503, 504)
    },
)
async def chat(
    body: ChatRequest,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResponse:
    try:
        return await service.chat(body)
    except AppError as exc:
        logger.warning("chat_failed", extra={"error_code": exc.code})
        raise
    except Exception as exc:
        logger.error("chat_failed", extra={"error_type": type(exc).__name__})
        raise AppError(
            "internal_error", "Customer support is temporarily unavailable.", 500
        ) from exc
