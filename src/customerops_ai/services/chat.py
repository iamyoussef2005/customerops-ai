"""Conversation ownership, atomic turns, customer serialization, and bounded agent work."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from customerops_ai.agents.contracts import LLMProvider
from customerops_ai.agents.execution import ToolExecutor
from customerops_ai.agents.orchestrator import AgentOrchestrator
from customerops_ai.core.auth import CustomerIdentity
from customerops_ai.core.config import Settings
from customerops_ai.core.errors import AppError
from customerops_ai.core.privacy import redact_sensitive
from customerops_ai.models import Conversation, Message
from customerops_ai.models.statuses import Channel, ConversationStatus, MessageRole
from customerops_ai.repositories.customer_ops import CustomerRepository
from customerops_ai.repositories.memory import MemoryRepository
from customerops_ai.schemas.chat import ChatRequest, ChatResponse
from customerops_ai.services.customer_tools import CustomerToolService
from customerops_ai.services.knowledge import KnowledgeService
from customerops_ai.services.memory import ConversationMemory


class ChatService:
    def __init__(
        self,
        session: AsyncSession,
        provider: LLMProvider,
        settings: Settings,
        identity: CustomerIdentity,
        knowledge: KnowledgeService | None = None,
    ) -> None:
        self.session = session
        self.provider = provider
        self.settings = settings
        self.identity = identity
        self.knowledge = knowledge

    async def chat(self, request: ChatRequest) -> ChatResponse:
        try:
            async with asyncio.timeout(self.settings.agent_turn_timeout):
                async with self.session.begin():
                    return await self._turn(request)
        except TimeoutError as exc:
            raise AppError(
                "agent_timeout", "The assistant timed out. Please try again.", 504
            ) from exc
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == "55P03":
                raise AppError(
                    "conversation_busy", "Another request is in progress. Please try again.", 409
                ) from exc
            raise AppError(
                "database_unavailable", "Customer support is temporarily unavailable.", 503
            ) from exc
        except SQLAlchemyError as exc:
            raise AppError(
                "database_unavailable", "Customer support is temporarily unavailable.", 503
            ) from exc

    async def _turn(self, request: ChatRequest) -> ChatResponse:
        customer_id = self.identity.customer_id
        # Held until commit/rollback: serializes conversations and ticket limits across workers.
        customer = await CustomerRepository(self.session).lock(customer_id)
        if customer is None:
            raise AppError("unauthorized", "A valid customer bearer token is required.", 401)
        now = datetime.now(UTC)
        if request.conversation_id is None:
            conversation = Conversation(customer_id=customer_id, channel=Channel.REST)
            self.session.add(conversation)
            await self.session.flush()
        else:
            found = await MemoryRepository(self.session, customer_id).get(
                request.conversation_id,
                now - timedelta(days=self.settings.memory_conversation_retention_days),
            )
            if found is None:
                raise AppError("not_found", "Conversation not found.", 404)
            conversation = found
        if conversation.status != ConversationStatus.OPEN:
            raise AppError(
                "conversation_unavailable",
                "This conversation is closed or awaiting human support.",
                409,
            )
        conversation_id = conversation.id
        history = await ConversationMemory(self.session, customer_id, self.settings).context(
            conversation, now
        )
        current = redact_sensitive(request.message)
        history.append({"role": "user", "content": current})
        turn_id = str(uuid4())
        self.session.add(
            Message(
                conversation_id=conversation_id,
                role=MessageRole.USER,
                content=current,
                metadata_json={"turn_id": turn_id},
                created_at=now,
            )
        )
        await self.session.flush()
        operations = CustomerToolService(
            self.session,
            customer_id,
            conversation,
            self.settings.agent_tickets_per_hour,
        )
        executor = ToolExecutor(operations, self.settings.agent_tool_timeout, self.knowledge)
        orchestrator = AgentOrchestrator(
            self.provider,
            executor,
            self.settings,
        )
        answer, traces = await orchestrator.run(history)
        answer = redact_sensitive(answer)
        if self.settings.memory_persist_tool_audit:
            for audit in executor.audits:
                self.session.add(
                    Message(
                        conversation_id=conversation_id,
                        role=MessageRole.TOOL,
                        content="Tool execution audit",
                        created_at=audit.finished_at,
                        metadata_json={**audit.metadata, "turn_id": turn_id},
                    )
                )
            await self.session.flush()
        conversation.last_activity_at = datetime.now(UTC)
        self.session.add(
            Message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=answer,
                metadata_json={"turn_id": turn_id},
                created_at=datetime.now(UTC),
            )
        )
        return ChatResponse(
            conversation_id=conversation_id,
            message=answer,
            tool_executions=traces,
            sources=executor.cited_sources(answer),
        )
