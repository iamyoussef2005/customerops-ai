"""Real PostgreSQL isolation: a random schema per test, always in a separate test database."""

import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from customerops_ai.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def migration_config(connection: Connection) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


def test_database_url(value: str, development: Settings) -> URL:
    """Reject development targets before issuing any schema-changing statements."""
    url = make_url(value)
    if url.drivername != "postgresql+asyncpg":
        raise ValueError("Integration tests require postgresql+asyncpg")
    if not url.database or not url.database.endswith("_test"):
        raise ValueError("Integration database name must end with _test")
    if url.database == development.database_name:
        raise ValueError(
            "Integration database must differ from the configured development database"
        )
    return url


@pytest_asyncio.fixture
async def schema_engine(request: pytest.FixtureRequest) -> AsyncIterator[AsyncEngine]:
    configured = os.environ.get("CUSTOMEROPS_TEST_DATABASE_URL")
    if not configured:
        message = (
            "Set CUSTOMEROPS_TEST_DATABASE_URL to a separate PostgreSQL database ending in _test"
        )
        if request.config.getoption("--require-database"):
            pytest.fail(message)
        pytest.skip(message)
    url = test_database_url(configured, Settings())
    schema = f"test_{uuid4().hex}"
    admin = create_async_engine(url, poolclass=NullPool, hide_parameters=True)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"server_settings": {"search_path": schema, "timezone": "UTC"}, "timeout": 5},
    )
    created = False
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        yield engine
    finally:
        await engine.dispose()
        if created:
            async with admin.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@pytest_asyncio.fixture
async def db_engine(schema_engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    async with schema_engine.begin() as connection:
        await connection.run_sync(lambda sync: command.upgrade(migration_config(sync), "head"))
    yield schema_engine


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
