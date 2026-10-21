"""Deterministic, insert-only FICTIONAL development fixtures. Never real customer data."""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from customerops_ai.core.config import Settings
from customerops_ai.infrastructure.database import Database
from customerops_ai.models import Customer, Order, OrderItem, Product
from customerops_ai.models.statuses import OrderStatus

SEED_NAMESPACE = UUID("0e5ab7b3-f19d-4c8b-9c71-83ef41030b13")
SEED_TIME = datetime(2026, 1, 15, 12, tzinfo=UTC)

PRODUCTS: tuple[tuple[str, str, str, str, int], ...] = (
    ("DESK-001", "Maple Desk Organizer", "Office", "24.90", 48),
    ("DESK-002", "Adjustable Laptop Stand", "Office", "49.00", 32),
    ("DESK-003", "Warm LED Desk Lamp", "Office", "39.50", 0),
    ("TECH-001", "Braided USB-C Cable", "Electronics", "12.00", 150),
    ("TECH-002", "Compact Wireless Mouse", "Electronics", "29.90", 62),
    ("TECH-003", "65W USB-C Charger", "Electronics", "44.00", 25),
    ("HOME-001", "Stoneware Coffee Mug", "Home", "16.50", 84),
    ("HOME-002", "Insulated Water Bottle", "Home", "27.00", 53),
    ("HOME-003", "Woven Storage Basket", "Home", "22.00", 18),
    ("TRAVEL-001", "Everyday Canvas Tote", "Travel", "19.00", 71),
    ("TRAVEL-002", "Packing Cube Set", "Travel", "34.00", 30),
    ("TRAVEL-003", "Travel Document Wallet", "Travel", "21.50", 12),
    ("CARE-001", "Reusable Cleaning Cloth Set", "Care", "11.00", 96),
    ("CARE-002", "Cedar Shoe Care Kit", "Care", "32.00", 9),
    ("CARE-003", "Natural Cork Yoga Block", "Care", "18.00", 40),
)
CUSTOMERS = ("Maya Reed", "Omar Vale", "Lina Brooks", "Theo Morgan", "Nora Ellis")
ORDER_STATUSES = (
    OrderStatus.PENDING,
    OrderStatus.PAID,
    OrderStatus.PROCESSING,
    OrderStatus.SHIPPED,
    OrderStatus.DELIVERED,
    OrderStatus.CANCELLED,
    OrderStatus.REFUNDED,
    OrderStatus.DELIVERED,
    OrderStatus.PROCESSING,
    OrderStatus.SHIPPED,
)


def seed_id(key: str) -> UUID:
    return uuid5(SEED_NAMESPACE, key)


async def seed_data(session: AsyncSession) -> None:
    """Insert stable IDs in the caller's transaction; leave existing rows untouched."""
    await session.execute(text("SELECT pg_advisory_xact_lock(750010)"))
    for index, name in enumerate(CUSTOMERS):
        await session.execute(
            insert(Customer)
            .values(
                id=seed_id(f"customer:{index}"),
                full_name=name,
                email=f"{name.lower().replace(' ', '.')}@customers.example",
                created_at=SEED_TIME,
                updated_at=SEED_TIME,
            )
            .on_conflict_do_nothing(index_elements=[Customer.id])
        )
    for sku, name, category, price, stock in PRODUCTS:
        await session.execute(
            insert(Product)
            .values(
                id=seed_id(sku),
                sku=sku,
                name=name,
                description=f"FICTIONAL demo product: {name} from Northstar Goods.",
                category=category,
                price=Decimal(price),
                stock_quantity=stock,
                currency="USD",
                created_at=SEED_TIME,
                updated_at=SEED_TIME,
            )
            .on_conflict_do_nothing(index_elements=[Product.id])
        )
    for index, status in enumerate(ORDER_STATUSES):
        order_id = seed_id(f"order:{index}")
        placed_at = SEED_TIME + timedelta(days=index)
        await session.execute(
            insert(Order)
            .values(
                id=order_id,
                order_number=f"DEMO-2026-{index + 1:04d}",
                customer_id=seed_id(f"customer:{index % len(CUSTOMERS)}"),
                status=status,
                shipping_address=f"FICTIONAL: {100 + index} Example Lane, Demo City, Exampleland",
                tracking_number=f"DEMO-TRACK-{index + 1:04d}"
                if status in {OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.REFUNDED}
                else None,
                created_at=placed_at,
                updated_at=placed_at,
            )
            .on_conflict_do_nothing(index_elements=[Order.id])
        )
        for offset in range(2):
            sku, name, _, price, _ = PRODUCTS[(index + offset) % len(PRODUCTS)]
            await session.execute(
                insert(OrderItem)
                .values(
                    id=seed_id(f"item:{index}:{offset}"),
                    order_id=order_id,
                    product_id=seed_id(sku),
                    product_name=name,
                    quantity=offset + 1,
                    unit_price=Decimal(price),
                    created_at=placed_at,
                    updated_at=placed_at,
                )
                .on_conflict_do_nothing(index_elements=[OrderItem.id])
            )


async def run_seed() -> None:
    settings = Settings()
    if settings.environment == "production":
        raise ValueError("Fictional seed data is prohibited in the production environment")
    database = Database(settings)
    try:
        async with database.sessions.begin() as session:
            await seed_data(session)
    finally:
        await database.close()
    print(
        "Fictional fixtures inserted: 15 products, 5 customers, 10 orders, "
        "20 items (existing IDs retained)."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-fictional-data", action="store_true", required=True)
    parser.parse_args()
    asyncio.run(run_seed())


if __name__ == "__main__":
    main()
