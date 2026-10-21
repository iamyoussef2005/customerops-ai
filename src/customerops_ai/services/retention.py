"""Explicit physical retention, coordinated with chat through customer row locks."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from customerops_ai.core.config import Settings
from customerops_ai.models import Conversation, Customer, Message, SupportTicket
from customerops_ai.models.statuses import MessageRole


class RetentionResult(BaseModel):
    customers_processed: int = 0
    messages_deleted: int = 0
    conversations_deleted: int = 0
    summaries_cleared: int = 0


class RetentionService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def purge_batch(
        self, after: UUID | None = None, batch_size: int = 50, now: datetime | None = None
    ) -> tuple[RetentionResult, UUID | None]:
        if not 1 <= batch_size <= 100:
            raise ValueError("Retention batch size must be between 1 and 100")
        clock = now if now is not None else datetime.now(UTC)
        config = self.settings
        result = RetentionResult()
        async with self.session.begin():
            statement = (
                select(Customer.id)
                .order_by(Customer.id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            if after is not None:
                statement = statement.where(Customer.id > after)
            customers = list(await self.session.scalars(statement))
            if not customers:
                return result, None
            result.customers_processed = len(customers)
            owned = select(Conversation.id).where(Conversation.customer_id.in_(customers))
            expired = select(Conversation.id).where(
                Conversation.customer_id.in_(customers),
                Conversation.last_activity_at
                < clock - timedelta(days=config.memory_conversation_retention_days),
                ~exists(
                    select(SupportTicket.id).where(SupportTicket.conversation_id == Conversation.id)
                ),
            )
            deleted = await self.session.execute(
                delete(Message).where(
                    Message.conversation_id.in_(owned),
                    or_(
                        Message.conversation_id.in_(expired),
                        (Message.role == MessageRole.TOOL)
                        & (
                            Message.created_at
                            < clock - timedelta(days=config.memory_tool_retention_days)
                        ),
                        (Message.role != MessageRole.TOOL)
                        & (
                            Message.created_at
                            < clock - timedelta(days=config.memory_message_retention_days)
                        ),
                    ),
                )
            )
            result.messages_deleted = int(getattr(deleted, "rowcount", 0))
            # Derived excerpts must not outlive their source. Rebuild from retained text next turn.
            cleared = await self.session.execute(
                update(Conversation)
                .where(
                    Conversation.customer_id.in_(customers),
                    Conversation.summary_through_sequence > 0,
                )
                .values(memory_summary={}, summary_through_sequence=0)
            )
            result.summaries_cleared = int(getattr(cleared, "rowcount", 0))
            removed = await self.session.execute(
                delete(Conversation).where(Conversation.id.in_(expired))
            )
            result.conversations_deleted = int(getattr(removed, "rowcount", 0))
            return result, customers[-1]
