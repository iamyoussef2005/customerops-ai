"""Administrator-only bounded ingestion. Authentication precedes body consumption."""

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from customerops_ai.core.auth import Administrator
from customerops_ai.core.errors import AppError
from customerops_ai.schemas.knowledge import (
    DocumentAttributes,
    DocumentRecord,
    IngestionResult,
    KnowledgeQuery,
    KnowledgeResult,
)
from customerops_ai.services.knowledge import KnowledgeService

router = APIRouter(prefix="/admin/documents", tags=["knowledge administration"])


def get_knowledge(request: Request, administrator: Administrator) -> KnowledgeService:
    service: KnowledgeService | None = getattr(request.app.state, "knowledge", None)
    if service is None:
        raise AppError("knowledge_not_configured", "Knowledge is not configured.", 503)
    return service


Knowledge = Annotated[KnowledgeService, Depends(get_knowledge)]


async def upload_body(request: Request) -> tuple[str, bytes, DocumentAttributes]:
    limit = request.app.state.settings.rag_max_upload_bytes
    body = bytearray()
    async for piece in request.stream():
        body.extend(piece)
        if len(body) > limit + 16_384:
            raise AppError("upload_too_large", "The upload exceeds the configured limit.", 413)

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": bytes(body), "more_body": False}

    bounded = Request(request.scope, receive=receive)
    try:
        async with bounded.form(max_files=1, max_fields=4, max_part_size=limit) as form:
            if len(form.multi_items()) != len(form) or set(form) - {
                "file",
                "source_key",
                "title",
                "category",
                "custom",
            }:
                raise ValueError("Invalid fields")
            file = form.get("file")
            if not isinstance(file, UploadFile) or not file.filename:
                raise ValueError("A file is required")
            if file.content_type not in {
                "application/pdf",
                "text/markdown",
                "text/plain",
                "application/octet-stream",
            }:
                raise AppError("unsupported_file", "Unsupported file type.", 415)
            raw = await file.read(limit + 1)
            attributes = DocumentAttributes.model_validate(
                {
                    "source_key": form.get("source_key", file.filename.lower()),
                    "title": form.get("title", file.filename),
                    "category": form.get("category", "general"),
                    "custom": json.loads(str(form.get("custom", "{}"))),
                }
            )
            return file.filename, raw, attributes
    except AppError:
        raise
    except (ValueError, ValidationError) as exc:
        raise AppError("invalid_upload", "Invalid document upload.", 422) from exc


@router.post("", response_model=IngestionResult)
async def upload(request: Request, service: Knowledge) -> IngestionResult:
    filename, raw, attributes = await upload_body(request)
    return await service.ingest(filename, raw, attributes)


@router.get("", response_model=list[DocumentRecord])
async def listing(service: Knowledge) -> list[DocumentRecord]:
    return await service.list_documents()


@router.put("/{document_id}", response_model=IngestionResult)
async def replace(document_id: UUID, request: Request, service: Knowledge) -> IngestionResult:
    filename, raw, attributes = await upload_body(request)
    return await service.ingest(filename, raw, attributes, document_id)


@router.post("/{document_id}/reindex", response_model=IngestionResult)
async def reindex(document_id: UUID, service: Knowledge) -> IngestionResult:
    return await service.reindex(document_id)


@router.delete("/{document_id}", status_code=204)
async def delete(document_id: UUID, service: Knowledge) -> Response:
    await service.delete(document_id)
    return Response(status_code=204)


@router.post("/search", response_model=KnowledgeResult)
async def search(body: KnowledgeQuery, service: Knowledge) -> KnowledgeResult:
    return await service.search(body)
