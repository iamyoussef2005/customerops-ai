"""Async database lifecycle and a reusable request-scoped session dependency."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from customerops_ai.core.config import Settings


class Database:
    """One connection pool per application lifespan, never one session shared by tasks."""

    def __init__(self, settings: Settings) -> None:
        self.engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_timeout,
            hide_parameters=True,
            connect_args={
                "timeout": settings.database_timeout,
                "command_timeout": settings.database_timeout,
            },
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, autoflush=False)

    async def close(self) -> None:
        await self.engine.dispose()


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield one session; callers explicitly commit, uncommitted work rolls back on close."""
    database: Database | None = request.app.state.database
    if database is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database is not configured")
    async with database.sessions() as session:
        yield session


DatabaseSession = Annotated[AsyncSession, Depends(get_session)]
