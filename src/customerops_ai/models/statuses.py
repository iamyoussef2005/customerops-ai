"""Persistent status values, also enforced with database CHECK constraints."""

from enum import StrEnum


class OrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class ConversationStatus(StrEnum):
    OPEN = "open"
    WAITING_HUMAN = "waiting_human"
    CLOSED = "closed"


class Channel(StrEnum):
    REST = "rest"
    WEB = "web"
    WHATSAPP = "whatsapp"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    HUMAN = "human"
    SYSTEM = "system"
    TOOL = "tool"


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
