"""Owned conversation and ordered message read contracts; no internal memory cursor exposure."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, JsonValue

from customerops_ai.models.statuses import Channel, ConversationStatus, MessageRole


class ConversationRead(BaseModel):
    id: UUID
    channel: Channel
    status: ConversationStatus
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime


class ConversationPage(BaseModel):
    items: list[ConversationRead]
    next_offset: int | None


class MessageRead(BaseModel):
    id: UUID
    sequence: int
    role: MessageRole
    content: str
    metadata: dict[str, JsonValue]
    created_at: datetime
    updated_at: datetime


class MessagePage(BaseModel):
    items: list[MessageRead]
    next_after: int | None
