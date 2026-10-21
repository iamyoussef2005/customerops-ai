"""Authenticated conversation retrieval. Client IDs never establish ownership."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from customerops_ai.core.auth import AuthenticatedCustomer
from customerops_ai.infrastructure.database import DatabaseSession
from customerops_ai.schemas.conversations import ConversationPage, ConversationRead, MessagePage
from customerops_ai.services.conversations import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])


def get_conversations(
    request: Request, identity: AuthenticatedCustomer, session: DatabaseSession
) -> ConversationService:
    return ConversationService(session, identity, request.app.state.settings)


Conversations = Annotated[ConversationService, Depends(get_conversations)]


@router.get("", response_model=ConversationPage)
async def listing(
    service: Conversations,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> ConversationPage:
    return await service.list(limit, offset)


@router.get("/{conversation_id}", response_model=ConversationRead)
async def detail(conversation_id: UUID, service: Conversations) -> ConversationRead:
    return await service.get(conversation_id)


@router.get("/{conversation_id}/messages", response_model=MessagePage)
async def messages(
    conversation_id: UUID,
    service: Conversations,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    after: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
) -> MessagePage:
    return await service.messages(conversation_id, limit, after)
