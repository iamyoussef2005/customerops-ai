"""Business operations available to the agent, bound to a server-authenticated identity."""

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from customerops_ai.core.errors import AppError
from customerops_ai.core.types import JsonObject
from customerops_ai.models import Conversation, Product, SupportTicket
from customerops_ai.models.statuses import ConversationStatus
from customerops_ai.repositories.customer_ops import (
    CustomerRepository,
    OrderRepository,
    ProductRepository,
    TicketRepository,
)
from customerops_ai.schemas.products import ProductFilters


class ToolOperations(Protocol):
    async def search_products(self, query: str, filters: ProductFilters | None) -> JsonObject: ...
    async def get_product_details(self, product_id: UUID) -> JsonObject: ...
    async def check_product_stock(self, product_id: UUID) -> JsonObject: ...
    async def get_order_status(self, order_id: UUID) -> JsonObject: ...
    async def create_support_ticket(self, subject: str, description: str) -> JsonObject: ...


def product_summary(product: Product) -> JsonObject:
    return {
        "product_id": str(product.id),
        "name": product.name,
        "sku": product.sku,
        "price": str(product.price),
        "currency": product.currency,
        "category": product.category,
    }


class CustomerToolService:
    def __init__(
        self,
        session: AsyncSession,
        customer_id: UUID,
        conversation: Conversation,
        tickets_per_hour: int,
    ) -> None:
        self.session = session
        self.customer_id = customer_id
        self.conversation = conversation
        self.conversation_id = conversation.id
        self.conversation_customer_id = conversation.customer_id
        self.tickets_per_hour = tickets_per_hour
        self.products = ProductRepository(session)
        self.orders = OrderRepository(session)
        self.tickets = TicketRepository(session)

    async def search_products(self, query: str, filters: ProductFilters | None) -> JsonObject:
        async with self.session.begin_nested():
            products = await self.products.search(query, filters)
            return {"products": [product_summary(product) for product in products]}

    async def get_product_details(self, product_id: UUID) -> JsonObject:
        async with self.session.begin_nested():
            product = await self.products.get_active(product_id)
            if product is None:
                raise AppError("not_found", "Product not found.", 404)
            return {**product_summary(product), "description": product.description[:4000]}

    async def check_product_stock(self, product_id: UUID) -> JsonObject:
        async with self.session.begin_nested():
            product = await self.products.get_active(product_id)
            if product is None:
                raise AppError("not_found", "Product not found.", 404)
            return {
                "product_id": str(product.id),
                "in_stock": product.stock_quantity > 0,
                "stock_quantity": product.stock_quantity,
            }

    async def get_order_status(self, order_id: UUID) -> JsonObject:
        async with self.session.begin_nested():
            order = await self.orders.get_owned(order_id, self.customer_id)
            if order is None:
                # Missing and foreign orders are deliberately indistinguishable.
                raise AppError("not_found", "Order not found.", 404)
            return {
                "order_id": str(order.id),
                "order_number": order.order_number,
                "status": order.status.value,
                "tracking_number": order.tracking_number,
            }

    async def create_support_ticket(self, subject: str, description: str) -> JsonObject:
        subject, description = subject.strip(), description.strip()
        if not 3 <= len(subject) <= 120 or not 10 <= len(description) <= 2000:
            raise AppError("invalid_arguments", "Ticket subject or description is invalid.")
        async with self.session.begin_nested():
            if self.conversation_customer_id != self.customer_id:
                raise AppError("not_found", "Conversation not found.", 404)
            # Also protect quota enforcement when this service is called outside the chat facade.
            if await CustomerRepository(self.session).lock(self.customer_id) is None:
                raise AppError("unauthorized", "A valid customer bearer token is required.", 401)
            existing = await self.tickets.existing(self.conversation_id)
            if existing is not None:
                return {
                    "ticket_id": str(existing.id),
                    "status": existing.status.value,
                    "already_exists": True,
                }
            since = datetime.now(UTC) - timedelta(hours=1)
            if await self.tickets.count_since(self.customer_id, since) >= self.tickets_per_hour:
                raise AppError(
                    "ticket_limit", "Support ticket limit reached. Please try later.", 429
                )
            ticket = SupportTicket(
                conversation_id=self.conversation_id,
                subject=subject,
                description=description,
            )
            self.session.add(ticket)
            self.conversation.status = ConversationStatus.WAITING_HUMAN
            await self.session.flush()
            return {
                "ticket_id": str(ticket.id),
                "status": ticket.status.value,
                "already_exists": False,
                "human_connected": False,
            }
