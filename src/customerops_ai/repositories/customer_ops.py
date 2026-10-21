"""Bounded SQL queries and persistence; authorization policies live in services."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from customerops_ai.models import Conversation, Customer, Order, Product, SupportTicket
from customerops_ai.models.statuses import TicketStatus
from customerops_ai.schemas.products import ProductFilters


class CustomerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock(self, customer_id: UUID) -> Customer | None:
        return await self.session.scalar(
            select(Customer).where(Customer.id == customer_id).with_for_update(nowait=True)
        )


class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(self, query: str, filters: ProductFilters | None) -> list[Product]:
        escaped = query.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        pattern = f"%{escaped}%"
        statement = select(Product).where(
            Product.is_active.is_(True),
            Product.name.ilike(pattern, escape="\\")
            | Product.sku.ilike(pattern, escape="\\")
            | Product.description.ilike(pattern, escape="\\"),
        )
        if filters is not None:
            if filters.category is not None:
                statement = statement.where(Product.category == filters.category)
            if filters.min_price is not None:
                statement = statement.where(Product.price >= Decimal(str(filters.min_price)))
            if filters.max_price is not None:
                statement = statement.where(Product.price <= Decimal(str(filters.max_price)))
            if filters.currency is not None:
                statement = statement.where(Product.currency == filters.currency)
            if filters.in_stock is True:
                statement = statement.where(Product.stock_quantity > 0)
            elif filters.in_stock is False:
                statement = statement.where(Product.stock_quantity == 0)
        return list(
            await self.session.scalars(statement.order_by(Product.name, Product.id).limit(10))
        )

    async def get_active(self, product_id: UUID) -> Product | None:
        return await self.session.scalar(
            select(Product).where(Product.id == product_id, Product.is_active.is_(True))
        )


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_owned(self, order_id: UUID, customer_id: UUID) -> Order | None:
        return await self.session.scalar(
            select(Order).where(Order.id == order_id, Order.customer_id == customer_id)
        )


class TicketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def existing(self, conversation_id: UUID) -> SupportTicket | None:
        return await self.session.scalar(
            select(SupportTicket)
            .where(
                SupportTicket.conversation_id == conversation_id,
                SupportTicket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS]),
            )
            .order_by(SupportTicket.created_at.desc())
            .limit(1)
        )

    async def count_since(self, customer_id: UUID, since: datetime) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(SupportTicket)
                .join(Conversation)
                .where(Conversation.customer_id == customer_id, SupportTicket.created_at >= since)
            )
            or 0
        )
