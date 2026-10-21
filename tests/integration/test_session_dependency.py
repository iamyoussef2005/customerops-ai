"""Exercise the actual request dependency against migrated, isolated PostgreSQL."""

from contextlib import aclosing
from typing import cast

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.requests import Request

from customerops_ai.core.config import Settings
from customerops_ai.infrastructure.database import Database, get_session
from customerops_ai.main import create_app
from customerops_ai.models import Customer

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.mark.parametrize("commit", [True, False])
async def test_request_dependency_commits_only_explicitly(
    db_engine: AsyncEngine,
    commit: bool,
) -> None:
    url = db_engine.url
    settings = Settings(
        environment="test",
        database_host=url.host or "localhost",
        database_port=url.port or 5432,
        database_name=url.database or "customerops_test",
        database_user=url.username or "",
        database_password=SecretStr(url.password or ""),
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        database = cast(Database, app.state.database)
        # Inject a real schema-isolated factory; no database operations are mocked.
        database.sessions = async_sessionmaker(db_engine, expire_on_commit=False, autoflush=False)
        request = Request({"type": "http", "app": app})
        async with aclosing(get_session(request)) as dependency:
            session = await anext(dependency)
            session.add(Customer(full_name="Dependency Fictional", email="dependency@example.test"))
            await session.flush()
            if commit:
                await session.commit()
        async with database.sessions() as another_session:
            count = await another_session.scalar(select(func.count()).select_from(Customer))
            assert count == (1 if commit else 0)
