"""Customer operations schema. No business workflows or API behavior are implemented here."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from customerops_ai.models.base import Base, IdentityTimestamps
from customerops_ai.models.statuses import (
    Channel,
    ConversationStatus,
    MessageRole,
    OrderStatus,
    TicketPriority,
    TicketStatus,
)


def status_type(enum: type[StrEnum], name: str) -> Enum:
    """Store public enum values rather than Python member names; avoid native enum DDL."""
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


class Customer(IdentityTimestamps, Base):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint("email = lower(email) AND position('@' in email) > 1", name="email_format"),
        CheckConstraint("length(trim(full_name)) > 0", name="name_not_blank"),
    )

    email: Mapped[str] = mapped_column(String(254), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(32))
    orders: Mapped[list[Order]] = relationship(
        back_populates="customer", lazy="raise", passive_deletes="all"
    )
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="customer", lazy="raise", passive_deletes="all"
    )


class Product(IdentityTimestamps, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="price_nonnegative"),
        CheckConstraint("stock_quantity >= 0", name="stock_nonnegative"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        CheckConstraint("length(trim(sku)) > 0", name="sku_not_blank"),
    )

    sku: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")
    stock_quantity: Mapped[int] = mapped_column(default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    order_items: Mapped[list[OrderItem]] = relationship(
        back_populates="product", lazy="raise", passive_deletes="all"
    )


class Order(IdentityTimestamps, Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_customer_created", "customer_id", "created_at"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("length(trim(shipping_address)) > 0", name="address_not_blank"),
    )

    order_number: Mapped[str] = mapped_column(String(40), unique=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"))
    status: Mapped[OrderStatus] = mapped_column(
        status_type(OrderStatus, "order_status"),
        default=OrderStatus.PENDING,
        server_default=OrderStatus.PENDING.value,
        index=True,
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")
    shipping_address: Mapped[str] = mapped_column(Text)
    tracking_number: Mapped[str | None] = mapped_column(String(100), index=True)
    customer: Mapped[Customer] = relationship(back_populates="orders", lazy="raise")
    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", lazy="raise", cascade="all, delete-orphan", passive_deletes=True
    )


class OrderItem(IdentityTimestamps, Base):
    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "product_id", name="uq_order_items_order_product"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="price_nonnegative"),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True
    )
    product_name: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int]
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    order: Mapped[Order] = relationship(back_populates="items", lazy="raise")
    product: Mapped[Product] = relationship(back_populates="order_items", lazy="raise")


class Conversation(IdentityTimestamps, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_customer_created", "customer_id", "created_at"),
        Index("ix_conversations_customer_activity", "customer_id", "last_activity_at", "id"),
        CheckConstraint("summary_through_sequence >= 0", name="summary_cursor_nonnegative"),
    )

    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    memory_summary: Mapped[dict[str, JsonValue]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    summary_through_sequence: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"))
    channel: Mapped[Channel] = mapped_column(status_type(Channel, "conversation_channel"))
    status: Mapped[ConversationStatus] = mapped_column(
        status_type(ConversationStatus, "conversation_status"),
        default=ConversationStatus.OPEN,
        server_default=ConversationStatus.OPEN.value,
        index=True,
    )
    customer: Mapped[Customer] = relationship(back_populates="conversations", lazy="raise")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    tickets: Mapped[list[SupportTicket]] = relationship(
        back_populates="conversation", lazy="raise", passive_deletes="all"
    )


class Message(IdentityTimestamps, Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at", "id"),
        Index("ix_messages_conversation_sequence", "conversation_id", "sequence", unique=True),
        Index("ix_messages_created_at", "created_at"),
        CheckConstraint("length(trim(content)) > 0", name="content_not_blank"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[MessageRole] = mapped_column(status_type(MessageRole, "message_role"))
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    metadata_json: Mapped[dict[str, JsonValue]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    content: Mapped[str] = mapped_column(Text)
    conversation: Mapped[Conversation] = relationship(back_populates="messages", lazy="raise")


class SupportTicket(IdentityTimestamps, Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        Index("ix_support_tickets_status_created", "status", "created_at"),
        CheckConstraint("length(trim(subject)) > 0", name="subject_not_blank"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), index=True
    )
    subject: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[TicketStatus] = mapped_column(
        status_type(TicketStatus, "ticket_status"),
        default=TicketStatus.OPEN,
        server_default=TicketStatus.OPEN.value,
    )
    priority: Mapped[TicketPriority] = mapped_column(
        status_type(TicketPriority, "ticket_priority"),
        default=TicketPriority.NORMAL,
        server_default=TicketPriority.NORMAL.value,
    )
    assigned_to: Mapped[str | None] = mapped_column(String(200))
    conversation: Mapped[Conversation] = relationship(back_populates="tickets", lazy="raise")
