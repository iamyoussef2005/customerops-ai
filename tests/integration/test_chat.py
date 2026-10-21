"""Real PostgreSQL services/API with only the LLM provider boundary replaced by a fake."""

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from uuid import UUID

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from customerops_ai.agents.contracts import ProviderReply
from customerops_ai.core.auth import CustomerIdentity
from customerops_ai.core.config import Settings
from customerops_ai.core.errors import AppError
from customerops_ai.infrastructure.database import get_session
from customerops_ai.main import create_app
from customerops_ai.models import Conversation, Message, Product, SupportTicket
from customerops_ai.models.statuses import Channel, ConversationStatus
from customerops_ai.repositories.customer_ops import CustomerRepository
from customerops_ai.schemas.chat import ChatRequest
from customerops_ai.schemas.products import ProductFilters
from customerops_ai.seed import seed_data, seed_id
from customerops_ai.services.chat import ChatService
from customerops_ai.services.customer_tools import CustomerToolService
from tests.agent_helpers import FakeProvider, tool_reply

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
CUSTOMER = seed_id("customer:0")


async def seed(session: AsyncSession) -> None:
    await seed_data(session)
    await session.commit()


async def make_conversation(session: AsyncSession, customer: UUID = CUSTOMER) -> Conversation:
    conversation = Conversation(customer_id=customer, channel=Channel.REST)
    session.add(conversation)
    await session.commit()
    return conversation


async def test_real_order_ownership_and_no_existence_disclosure(db_session: AsyncSession) -> None:
    await seed(db_session)
    conversation = await make_conversation(db_session)
    service = CustomerToolService(db_session, CUSTOMER, conversation, 3)
    assert (await service.get_order_status(seed_id("order:0")))["status"] == "pending"
    with pytest.raises(AppError, match="not_found"):
        await service.get_order_status(seed_id("order:1"))


async def test_search_filters_stock_details_and_literal_wildcards(db_session: AsyncSession) -> None:
    await seed(db_session)
    conversation = await make_conversation(db_session)
    service = CustomerToolService(db_session, CUSTOMER, conversation, 3)
    result = await service.search_products("Desk", ProductFilters(in_stock=True))
    products = result["products"]
    assert isinstance(products, list) and len(products) == 2
    assert (await service.get_product_details(seed_id("DESK-001")))["price"] == "24.90"
    assert (await service.check_product_stock(seed_id("DESK-003")))["in_stock"] is False
    assert (await service.search_products("%", None))["products"] == []
    product = await db_session.get(Product, seed_id("DESK-001"))
    assert product is not None
    product.is_active = False
    await db_session.flush()
    with pytest.raises(AppError, match="not_found"):
        await service.get_product_details(product.id)


async def test_ticket_reuse_rate_limit_and_owner_checks(db_session: AsyncSession) -> None:
    await seed(db_session)
    conversation = await make_conversation(db_session)
    service = CustomerToolService(db_session, CUSTOMER, conversation, 1)
    first = await service.create_support_ticket("Demo request", "Fictional delivery assistance")
    second = await service.create_support_ticket("Demo request", "Fictional delivery assistance")
    assert first["ticket_id"] == second["ticket_id"] and second["already_exists"] is True
    assert conversation.status == ConversationStatus.WAITING_HUMAN
    await db_session.commit()
    another = await make_conversation(db_session)
    with pytest.raises(AppError, match="ticket_limit"):
        await CustomerToolService(db_session, CUSTOMER, another, 1).create_support_ticket(
            "Another request", "Fictional request with valid length"
        )
    with pytest.raises(AppError, match="invalid_arguments"):
        await service.create_support_ticket(" ", " ")
    with pytest.raises(AppError, match="not_found"):
        await CustomerToolService(
            db_session, seed_id("customer:1"), conversation, 3
        ).create_support_ticket("Foreign request", "Fictional description with enough length")


async def test_real_chat_context_and_conversation_ownership(db_session: AsyncSession) -> None:
    await seed(db_session)
    provider = FakeProvider(
        ProviderReply(text="How can I help?"), ProviderReply(text="I remember your question.")
    )
    service = ChatService(db_session, provider, Settings(), CustomerIdentity(CUSTOMER))
    first = await service.chat(ChatRequest(message="Hello"))
    second = await service.chat(
        ChatRequest(message="Do you remember?", conversation_id=first.conversation_id)
    )
    assert second.conversation_id == first.conversation_id
    assert provider.inputs[1][0] == {"role": "user", "content": "Hello"}
    assert provider.inputs[1][1] == {"role": "assistant", "content": "How can I help?"}
    with pytest.raises(AppError, match="not_found"):
        await ChatService(
            db_session, provider, Settings(), CustomerIdentity(seed_id("customer:1"))
        ).chat(ChatRequest(message="Read another customer", conversation_id=first.conversation_id))


async def test_tool_failure_after_ticket_rolls_back_entire_turn(db_session: AsyncSession) -> None:
    await seed(db_session)
    provider = FakeProvider(
        tool_reply(
            "create_support_ticket",
            '{"subject":"Demo help","description":"Fictional ticket request"}',
        ),
        AppError("provider_timeout", "The assistant timed out.", 504),
    )
    with pytest.raises(AppError, match="provider_timeout"):
        await ChatService(db_session, provider, Settings(), CustomerIdentity(CUSTOMER)).chat(
            ChatRequest(message="Open a ticket")
        )
    assert await db_session.scalar(select(func.count()).select_from(SupportTicket)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Message)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Conversation)) == 0


async def test_turn_timeout_rolls_back(db_session: AsyncSession) -> None:
    await seed(db_session)

    class SlowProvider(FakeProvider):
        async def complete(self, items: object, tools: object) -> ProviderReply:
            await asyncio.sleep(1)
            return ProviderReply(text="late")

    with pytest.raises(AppError, match="agent_timeout"):
        await ChatService(
            db_session,
            SlowProvider(),
            Settings(agent_turn_timeout=0.05),
            CustomerIdentity(CUSTOMER),
        ).chat(ChatRequest(message="Hello"))
    assert await db_session.scalar(select(func.count()).select_from(Message)) == 0


async def test_chat_api_uses_authenticated_identity_and_returns_errors(
    db_session: AsyncSession,
) -> None:
    await seed(db_session)
    token = "fictional-integration-token-with-32-characters"
    config = Settings(auth_token_customers={hashlib.sha256(token.encode()).hexdigest(): CUSTOMER})
    app = create_app(config)
    provider = FakeProvider(
        tool_reply("get_order_status", json.dumps({"order_id": str(seed_id("order:1"))})),
        ProviderReply(text="I could not find that order."),
    )

    async def isolated_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = isolated_session
    async with app.router.lifespan_context(app):
        app.state.llm_provider = provider
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {"Authorization": f"Bearer {token}"}
            response = await client.post(
                "/api/v1/chat", headers=headers, json={"message": "Where is this order?"}
            )
            assert response.status_code == 200
            assert response.json()["tool_executions"][0]["error_code"] == "not_found"
            invalid = await client.post(
                "/api/v1/chat",
                headers=headers,
                json={"message": "Hello", "customer_id": str(seed_id("customer:1"))},
            )
            assert (
                invalid.status_code == 422 and invalid.json()["error"]["code"] == "invalid_request"
            )
            app.state.llm_provider = FakeProvider(
                AppError("provider_timeout", "The assistant timed out.", 504)
            )
            failure = await client.post("/api/v1/chat", headers=headers, json={"message": "Hello"})
            assert (
                failure.status_code == 504 and failure.json()["error"]["code"] == "provider_timeout"
            )


async def test_ticket_conversation_stops_further_automated_replies(
    db_session: AsyncSession,
) -> None:
    await seed(db_session)
    provider = FakeProvider(
        tool_reply(
            "create_support_ticket",
            '{"subject":"Demo help","description":"Fictional ticket request"}',
        ),
        ProviderReply(text="Your request is queued for human support."),
    )
    service = ChatService(db_session, provider, Settings(), CustomerIdentity(CUSTOMER))
    response = await service.chat(ChatRequest(message="Please open a ticket"))
    assert response.tool_executions[0].status == "ok"
    with pytest.raises(AppError, match="conversation_unavailable"):
        await service.chat(
            ChatRequest(message="Anything else?", conversation_id=response.conversation_id)
        )


async def test_concurrent_customer_turn_is_rejected_before_provider_call(
    db_session: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    await seed(db_session)
    provider = FakeProvider()
    async with db_session.begin():
        assert await CustomerRepository(db_session).lock(CUSTOMER) is not None
        async with async_sessionmaker(db_engine)() as contender:
            with pytest.raises(AppError, match="conversation_busy"):
                await ChatService(contender, provider, Settings(), CustomerIdentity(CUSTOMER)).chat(
                    ChatRequest(message="Concurrent request")
                )
    assert provider.inputs == []
