"""Initial customer operations tables and timestamp triggers.

This revision is deliberately independent of mutable application model definitions.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def common_columns() -> tuple[sa.Column[UUID], sa.Column[datetime], sa.Column[datetime]]:
    return (
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def enum_type(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    op.create_table(
        "customers",
        *common_columns(),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(32)),
        sa.CheckConstraint(
            "email = lower(email) AND position('@' in email) > 1", name="email_format"
        ),
        sa.CheckConstraint("length(trim(full_name)) > 0", name="name_not_blank"),
    )
    op.create_table(
        "products",
        *common_columns(),
        sa.Column("sku", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("stock_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.CheckConstraint("price >= 0", name="price_nonnegative"),
        sa.CheckConstraint("stock_quantity >= 0", name="stock_nonnegative"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        sa.CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        sa.CheckConstraint("length(trim(sku)) > 0", name="sku_not_blank"),
    )
    op.create_index("ix_products_name", "products", ["name"])
    op.create_index("ix_products_category", "products", ["category"])
    op.create_table(
        "orders",
        *common_columns(),
        sa.Column("order_number", sa.String(40), nullable=False, unique=True),
        sa.Column(
            "customer_id",
            sa.Uuid(),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            enum_type(
                "order_status",
                "pending",
                "paid",
                "processing",
                "shipped",
                "delivered",
                "cancelled",
                "refunded",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("shipping_address", sa.Text(), nullable=False),
        sa.Column("tracking_number", sa.String(100)),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        sa.CheckConstraint("length(trim(shipping_address)) > 0", name="address_not_blank"),
    )
    op.create_index("ix_orders_customer_created", "orders", ["customer_id", "created_at"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_tracking_number", "orders", ["tracking_number"])
    op.create_table(
        "order_items",
        *common_columns(),
        sa.Column(
            "order_id", sa.Uuid(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "product_id",
            sa.Uuid(),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("product_name", sa.String(200), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.UniqueConstraint("order_id", "product_id", name="uq_order_items_order_product"),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="price_nonnegative"),
    )
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"])
    op.create_table(
        "conversations",
        *common_columns(),
        sa.Column(
            "customer_id",
            sa.Uuid(),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "channel", enum_type("conversation_channel", "rest", "web", "whatsapp"), nullable=False
        ),
        sa.Column(
            "status",
            enum_type("conversation_status", "open", "waiting_human", "closed"),
            nullable=False,
            server_default="open",
        ),
    )
    op.create_index(
        "ix_conversations_customer_created", "conversations", ["customer_id", "created_at"]
    )
    op.create_index("ix_conversations_status", "conversations", ["status"])
    op.create_table(
        "messages",
        *common_columns(),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            enum_type("message_role", "user", "assistant", "human", "system", "tool"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.CheckConstraint("length(trim(content)) > 0", name="content_not_blank"),
    )
    op.create_index(
        "ix_messages_conversation_created", "messages", ["conversation_id", "created_at", "id"]
    )
    op.create_table(
        "support_tickets",
        *common_columns(),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            enum_type("ticket_status", "open", "in_progress", "resolved", "closed"),
            nullable=False,
            server_default="open",
        ),
        sa.Column(
            "priority",
            enum_type("ticket_priority", "low", "normal", "high", "urgent"),
            nullable=False,
            server_default="normal",
        ),
        sa.Column("assigned_to", sa.String(200)),
        sa.CheckConstraint("length(trim(subject)) > 0", name="subject_not_blank"),
    )
    op.create_index("ix_support_tickets_conversation_id", "support_tickets", ["conversation_id"])
    op.create_index(
        "ix_support_tickets_status_created", "support_tickets", ["status", "created_at"]
    )

    op.execute("""
        CREATE FUNCTION customerops_set_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END;
        $$
    """)
    for table in (
        "customers",
        "products",
        "orders",
        "order_items",
        "conversations",
        "messages",
        "support_tickets",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION customerops_set_updated_at()"
        )


def downgrade() -> None:
    for table in (
        "support_tickets",
        "messages",
        "conversations",
        "order_items",
        "orders",
        "products",
        "customers",
    ):
        op.drop_table(table)
    op.execute("DROP FUNCTION customerops_set_updated_at()")
