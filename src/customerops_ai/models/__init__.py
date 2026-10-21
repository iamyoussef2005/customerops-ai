"""Public model registry; importing this module registers all Alembic metadata."""

from customerops_ai.models.base import Base
from customerops_ai.models.entities import (
    Conversation,
    Customer,
    Message,
    Order,
    OrderItem,
    Product,
    SupportTicket,
)

__all__ = [
    "Base",
    "Conversation",
    "Customer",
    "Message",
    "Order",
    "OrderItem",
    "Product",
    "SupportTicket",
]
