"""Exercise migrated PostgreSQL tables, real constraints, transactions, and seeds."""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from customerops_ai.models import (
    Base,
    Conversation,
    Customer,
    Message,
    Order,
    OrderItem,
    Product,
    SupportTicket,
)
from customerops_ai.models.statuses import (
    Channel,
    ConversationStatus,
    MessageRole,
    OrderStatus,
    TicketPriority,
    TicketStatus,
)
from customerops_ai.seed import seed_data, seed_id
from tests.integration.conftest import migration_config

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_migration_round_trip_and_metadata(schema_engine: AsyncEngine) -> None:
    async with schema_engine.begin() as connection:
        await connection.run_sync(lambda sync: command.upgrade(migration_config(sync), "head"))
        names = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
        assert set(names) == {*Base.metadata.tables, "alembic_version"}
        differences = await connection.run_sync(
            lambda sync: compare_metadata(MigrationContext.configure(sync), Base.metadata)
        )
        assert differences == []
        await connection.run_sync(lambda sync: command.downgrade(migration_config(sync), "base"))
        names = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
        assert names == ["alembic_version"]
        assert (
            await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_proc "
                    "WHERE proname = 'customerops_set_updated_at' "
                    "AND pronamespace = current_schema()::regnamespace"
                )
            )
            == 0
        )
        await connection.run_sync(lambda sync: command.upgrade(migration_config(sync), "head"))


async def test_seed_is_repeatable_and_preserves_existing_data(db_session: AsyncSession) -> None:
    await seed_data(db_session)
    await db_session.commit()
    product = await db_session.get(Product, seed_id("DESK-001"))
    assert product is not None
    product.stock_quantity = 17
    await db_session.commit()
    await seed_data(db_session)
    await db_session.commit()

    for model, count in ((Product, 15), (Customer, 5), (Order, 10), (OrderItem, 20)):
        assert await db_session.scalar(select(func.count()).select_from(model)) == count
    assert (
        await db_session.scalar(select(Product.stock_quantity).where(Product.id == product.id))
        == 17
    )
    assert set(await db_session.scalars(select(Order.status))) == set(OrderStatus)
    orders = (
        await db_session.scalars(
            select(Order).options(
                selectinload(Order.customer),
                selectinload(Order.items).selectinload(OrderItem.product),
            )
        )
    ).all()
    assert all(
        len(order.items) == 2 and order.customer.email.endswith(".example") for order in orders
    )
    assert all(item.unit_price == item.product.price for order in orders for item in order.items)
    assert orders[0].created_at.tzinfo is not None


async def test_conversation_message_ticket_relationships(db_session: AsyncSession) -> None:
    customer = Customer(full_name="Fictional Tester", email="tester@example.test")
    conversation = Conversation(
        customer=customer, channel=Channel.REST, status=ConversationStatus.WAITING_HUMAN
    )
    message = Message(
        conversation=conversation, role=MessageRole.USER, content="Fictional support request"
    )
    ticket = SupportTicket(
        conversation=conversation,
        subject="Demo delivery question",
        description="Fictional test case",
        priority=TicketPriority.HIGH,
        status=TicketStatus.IN_PROGRESS,
        assigned_to="Fictional Agent",
    )
    db_session.add_all([message, ticket])
    await db_session.commit()
    customer_id = customer.id
    db_session.expunge_all()
    loaded = await db_session.scalar(
        select(Customer)
        .where(Customer.id == customer_id)
        .options(
            selectinload(Customer.conversations).selectinload(Conversation.messages),
            selectinload(Customer.conversations).selectinload(Conversation.tickets),
        )
    )
    assert loaded is not None
    assert loaded.conversations[0].messages[0].role == MessageRole.USER
    assert loaded.conversations[0].tickets[0].status == TicketStatus.IN_PROGRESS


@pytest.mark.parametrize(
    "assignment", ["price = -1", "stock_quantity = -1", "currency = 'bad'", "name = ' '"]
)
async def test_product_constraints(db_session: AsyncSession, assignment: str) -> None:
    await seed_data(db_session)
    await db_session.commit()
    with pytest.raises(IntegrityError):
        await db_session.execute(text(f"UPDATE products SET {assignment}"))
    await db_session.rollback()


async def test_unique_customer_email(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            Customer(full_name="First Fictional", email="duplicate@example.test"),
            Customer(full_name="Second Fictional", email="duplicate@example.test"),
        ]
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    assert await db_session.scalar(select(func.count()).select_from(Customer)) == 0


async def test_foreign_key_and_status_constraints(db_session: AsyncSession) -> None:
    db_session.add(
        Order(customer_id=uuid4(), order_number="DEMO-MISSING", shipping_address="FICTIONAL")
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    await seed_data(db_session)
    await db_session.commit()
    with pytest.raises(IntegrityError):
        await db_session.execute(text("UPDATE orders SET status = 'invented'"))
    await db_session.rollback()


@pytest.mark.parametrize("assignment", ["quantity = 0", "unit_price = -1"])
async def test_order_item_constraints(db_session: AsyncSession, assignment: str) -> None:
    await seed_data(db_session)
    await db_session.commit()
    with pytest.raises(IntegrityError):
        await db_session.execute(text(f"UPDATE order_items SET {assignment}"))
    await db_session.rollback()


async def test_deletion_restrictions_and_item_cascade(db_session: AsyncSession) -> None:
    await seed_data(db_session)
    await db_session.commit()
    with pytest.raises(IntegrityError):
        await db_session.execute(delete(Customer).where(Customer.id == seed_id("customer:0")))
    await db_session.rollback()
    with pytest.raises(IntegrityError):
        await db_session.execute(delete(Product).where(Product.id == seed_id("DESK-001")))
    await db_session.rollback()
    await db_session.execute(delete(Order).where(Order.id == seed_id("order:0")))
    await db_session.commit()
    assert await db_session.scalar(select(func.count()).select_from(OrderItem)) == 18


async def test_server_updated_timestamp_and_decimal_precision(db_session: AsyncSession) -> None:
    await seed_data(db_session)
    await db_session.commit()
    before = await db_session.scalar(select(Product.updated_at).where(Product.sku == "DESK-001"))
    updated = await db_session.scalar(
        text("UPDATE products SET price = 123.45 WHERE sku = 'DESK-001' RETURNING updated_at")
    )
    await db_session.commit()
    assert isinstance(before, datetime) and isinstance(updated, datetime)
    assert updated > before
    assert await db_session.scalar(
        select(Product.price).where(Product.sku == "DESK-001")
    ) == Decimal("123.45")


async def test_uncommitted_session_changes_are_rolled_back(db_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(db_engine)
    async with factory() as session:
        session.add(Customer(full_name="Rollback Fictional", email="rollback@example.test"))
        await session.flush()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Customer)) == 0
