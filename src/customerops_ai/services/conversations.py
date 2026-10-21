"""Customer-only conversation reads, retention visibility and bounded pagination."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from customerops_ai.core.auth import CustomerIdentity
from customerops_ai.core.config import Settings
from customerops_ai.core.errors import AppError
from customerops_ai.core.privacy import redact_sensitive
from customerops_ai.models import Conversation, Customer
from customerops_ai.repositories.memory import MemoryRepository
from customerops_ai.schemas.conversations import (
    ConversationPage,
    ConversationRead,
    MessagePage,
    MessageRead,
)


def conversation_read(row: Conversation) -> ConversationRead:
    return ConversationRead(
        id=row.id,
        channel=row.channel,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_activity_at=row.last_activity_at,
    )


class ConversationService:
    def __init__(
        self, session: AsyncSession, identity: CustomerIdentity, settings: Settings
    ) -> None:
        self.session = session
        self.identity = identity
        self.settings = settings
        self.repository = MemoryRepository(session, identity.customer_id)

    async def authenticate(self) -> None:
        if await self.session.get(Customer, self.identity.customer_id) is None:
            raise AppError("unauthorized", "A valid customer bearer token is required.", 401)

    async def owned(self, conversation_id: UUID, now: datetime) -> Conversation:
        row = await self.repository.get(
            conversation_id, now - timedelta(days=self.settings.memory_conversation_retention_days)
        )
        if row is None:
            raise AppError("not_found", "Conversation not found.", 404)
        return row

    async def list(self, limit: int, offset: int) -> ConversationPage:
        try:
            async with self.session.begin():
                await self.authenticate()
                rows = await self.repository.conversations(
                    datetime.now(UTC)
                    - timedelta(days=self.settings.memory_conversation_retention_days),
                    limit + 1,
                    offset,
                )
                return ConversationPage(
                    items=[conversation_read(row) for row in rows[:limit]],
                    next_offset=offset + limit if len(rows) > limit else None,
                )
        except SQLAlchemyError as exc:
            raise AppError(
                "database_unavailable", "Conversation history is unavailable.", 503
            ) from exc

    async def get(self, conversation_id: UUID) -> ConversationRead:
        try:
            async with self.session.begin():
                await self.authenticate()
                return conversation_read(await self.owned(conversation_id, datetime.now(UTC)))
        except SQLAlchemyError as exc:
            raise AppError(
                "database_unavailable", "Conversation history is unavailable.", 503
            ) from exc

    async def messages(self, conversation_id: UUID, limit: int, after: int) -> MessagePage:
        try:
            async with self.session.begin():
                await self.authenticate()
                now = datetime.now(UTC)
                await self.owned(conversation_id, now)
                rows = await self.repository.messages(
                    conversation_id,
                    now - timedelta(days=self.settings.memory_message_retention_days),
                    now - timedelta(days=self.settings.memory_tool_retention_days),
                    after,
                    limit + 1,
                )
                return MessagePage(
                    items=[
                        MessageRead(
                            id=row.id,
                            sequence=row.sequence,
                            role=row.role,
                            content=redact_sensitive(row.content),
                            metadata=row.metadata_json,
                            created_at=row.created_at,
                            updated_at=row.updated_at,
                        )
                        for row in rows[:limit]
                    ],
                    next_after=rows[limit - 1].sequence if len(rows) > limit else None,
                )
        except SQLAlchemyError as exc:
            raise AppError(
                "database_unavailable", "Conversation history is unavailable.", 503
            ) from exc
