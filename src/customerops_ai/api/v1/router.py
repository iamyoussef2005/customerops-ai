"""Versioned route composition."""

from fastapi import APIRouter

from customerops_ai.api.v1.routes.chat import router as chat_router
from customerops_ai.api.v1.routes.conversations import router as conversations_router
from customerops_ai.api.v1.routes.documents import router as documents_router
from customerops_ai.api.v1.routes.health import router as health_router
from customerops_ai.api.v1.routes.readiness import router as readiness_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(readiness_router)
api_router.include_router(chat_router)
api_router.include_router(documents_router)
api_router.include_router(conversations_router)
