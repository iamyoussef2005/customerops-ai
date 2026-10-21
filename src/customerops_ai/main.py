"""Application composition root and ASGI entry point."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
from starlette.exceptions import HTTPException
from starlette.responses import Response

from customerops_ai.api.v1.router import api_router
from customerops_ai.core.config import Settings
from customerops_ai.core.errors import AppError
from customerops_ai.infrastructure.database import Database
from customerops_ai.integrations.openai_provider import OpenAIProvider
from customerops_ai.rag.embeddings import OpenAIEmbeddings
from customerops_ai.rag.store import VectorStore
from customerops_ai.services.knowledge import KnowledgeService

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an application without opening external connections."""
    config = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        database = Database(config) if config.database_password is not None else None
        application.state.database = database
        client = (
            AsyncOpenAI(
                api_key=config.openai_api_key.get_secret_value(),
                timeout=config.agent_provider_timeout,
                max_retries=0,
            )
            if config.openai_api_key is not None and config.agent_model is not None
            else None
        )
        application.state.llm_provider = (
            OpenAIProvider(client, config) if client is not None else None
        )
        embedding_client = (
            AsyncOpenAI(
                api_key=config.openai_api_key.get_secret_value(),
                timeout=config.rag_embedding_timeout,
                max_retries=0,
            )
            if config.rag_enabled and config.openai_api_key is not None
            else None
        )
        application.state.knowledge = None
        store: VectorStore | None = None
        try:
            if embedding_client is not None:
                store = await asyncio.to_thread(VectorStore, config.rag_storage_path)
                application.state.knowledge = KnowledgeService(
                    store,
                    OpenAIEmbeddings(
                        embedding_client,
                        config.rag_embedding_model,
                        config.rag_embedding_dimensions,
                        config.rag_embedding_batch_size,
                    ),
                    config,
                )
            yield
        finally:
            if store is not None:
                await asyncio.to_thread(store.close)
            if embedding_client is not None:
                await embedding_client.close()
            if client is not None:
                await client.close()
            if database is not None:
                await database.close()

    application = FastAPI(title=config.app_name, version="0.1.0", lifespan=lifespan)
    application.state.settings = config

    @application.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(
            status_code=exc.status_code,
            headers=headers,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("request_failed", extra={"error_type": type(exc).__name__})
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "This operation is temporarily unavailable.",
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> Response:
        if request.url.path == "/api/v1/chat" or request.url.path.startswith(
            ("/api/v1/admin/", "/api/v1/conversations")
        ):
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "invalid_request",
                        "message": "The request is invalid.",
                    }
                },
            )
        return await request_validation_exception_handler(request, exc)

    @application.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> Response:
        if request.url.path == "/api/v1/chat" or request.url.path.startswith(
            ("/api/v1/admin/", "/api/v1/conversations")
        ):
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "error": {
                        "code": "service_unavailable",
                        "message": "Customer support is unavailable.",
                    }
                },
            )
        return await http_exception_handler(request, exc)

    application.include_router(api_router, prefix="/api/v1")
    return application


app = create_app()
