"""Customer-scoped memory queries. All message reads join the owning conversation."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from customerops_ai.models import Conversation, Message
from customerops_ai.models.statuses import MessageRole

TEXT_ROLES = (MessageRole.USER, MessageRole.ASSISTANT, MessageRole.HUMAN)


class MemoryRepository:
    def __init__(self, session: AsyncSession, customer_id: UUID) -> None:
        self.session = session
        self.customer_id = customer_id

    async def conversations(
        self, active_since: datetime, limit: int, offset: int
    ) -> list[Conversation]:
        return list(
            await self.session.scalars(
                select(Conversation)
                .where(
                    Conversation.customer_id == self.customer_id,
                    Conversation.last_activity_at >= active_since,
                )
                .order_by(Conversation.last_activity_at.desc(), Conversation.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )

    async def get(self, conversation_id: UUID, active_since: datetime) -> Conversation | None:
        return await self.session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.customer_id == self.customer_id,
                Conversation.last_activity_at >= active_since,
            )
        )

    async def recent(self, conversation_id: UUID, since: datetime, limit: int) -> list[Message]:
        rows = list(
            await self.session.scalars(
                select(Message)
                .join(Conversation)
                .where(
                    Conversation.customer_id == self.customer_id,
                    Conversation.id == conversation_id,
                    Message.role.in_(TEXT_ROLES),
                    Message.created_at >= since,
                )
                .order_by(Message.sequence.desc())
                .limit(limit)
            )
        )
        return list(reversed(rows))

    async def older(
        self,
        conversation_id: UUID,
        since: datetime,
        through: int,
        before: int,
        limit: int,
    ) -> list[Message]:
        rows = list(
            await self.session.scalars(
                select(Message)
                .join(Conversation)
                .where(
                    Conversation.customer_id == self.customer_id,
                    Conversation.id == conversation_id,
                    Message.role.in_(TEXT_ROLES),
                    Message.created_at >= since,
                    Message.sequence > through,
                    Message.sequence < before,
                )
                .order_by(Message.sequence.desc())
                .limit(limit)
            )
        )
        return list(reversed(rows))

    async def messages(
        self,
        conversation_id: UUID,
        since: datetime,
        audit_since: datetime,
        after: int,
        limit: int,
    ) -> list[Message]:
        return list(
            await self.session.scalars(
                select(Message)
                .join(Conversation)
                .where(
                    Conversation.customer_id == self.customer_id,
                    Conversation.id == conversation_id,
                    Message.sequence > after,
                    or_(
                        (Message.role != MessageRole.TOOL) & (Message.created_at >= since),
                        (Message.role == MessageRole.TOOL) & (Message.created_at >= audit_since),
                    ),
                )
                .order_by(Message.sequence)
                .limit(limit)
            )
        )
