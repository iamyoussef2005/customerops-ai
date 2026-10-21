"""Administrator ingestion and public company-knowledge retrieval business service."""

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from customerops_ai.core.config import Settings
from customerops_ai.core.errors import AppError
from customerops_ai.rag.embeddings import EmbeddingProvider, validate_vectors
from customerops_ai.rag.processing import chunk_document, extract_document
from customerops_ai.rag.store import VectorStore
from customerops_ai.schemas.knowledge import (
    DocumentAttributes,
    DocumentRecord,
    IngestionResult,
    KnowledgeQuery,
    KnowledgeResult,
)

logger = logging.getLogger(__name__)


class KnowledgeService:
    def __init__(
        self, store: VectorStore, embeddings: EmbeddingProvider, settings: Settings
    ) -> None:
        self.store = store
        self.embeddings = embeddings
        self.settings = settings

    async def list_documents(self) -> list[DocumentRecord]:
        return await asyncio.to_thread(self.store.list_documents)

    async def ingest(
        self,
        filename: str,
        raw: bytes,
        attributes: DocumentAttributes,
        document_id: UUID | None = None,
        *,
        force: bool = False,
        expected_generation: str | None = None,
    ) -> IngestionResult:
        try:
            extracted = await asyncio.to_thread(extract_document, filename, raw, self.settings)
            identifier = uuid5(NAMESPACE_URL, "customerops:knowledge:" + attributes.source_key)
            if document_id is not None and document_id != identifier:
                raise AppError("document_conflict", "The source key cannot change.", 409)
            records = await self.list_documents()
            old = next((record for record in records if record.document_id == identifier), None)
            if expected_generation is not None and (
                old is None or old.generation != expected_generation
            ):
                raise AppError("document_conflict", "Document changed; retry the operation.", 409)
            if document_id is not None and old is None:
                raise AppError("document_not_found", "Document not found.", 404)
            fingerprint = hashlib.sha256(
                json.dumps(
                    [
                        "v1",
                        extracted.content_hash,
                        filename,
                        attributes.model_dump(),
                        self.settings.rag_chunk_size,
                        self.settings.rag_chunk_overlap,
                        self.embeddings.model,
                        self.embeddings.dimensions,
                    ],
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            for record in records:
                if (
                    record.content_hash == extracted.content_hash
                    and record.document_id != identifier
                ):
                    if old is not None:
                        raise AppError(
                            "document_conflict", "Another document already has this content.", 409
                        )
                    return IngestionResult(document=record, duplicate=True)
            if old and old.fingerprint == fingerprint and not force:
                return IngestionResult(document=old, duplicate=True)
            chunks = chunk_document(extracted, self.settings)
            async with asyncio.timeout(self.settings.rag_embedding_timeout):
                vectors = await self.embeddings.embed([chunk.text for chunk in chunks])
            validate_vectors(vectors, len(chunks), self.embeddings.dimensions)
            now = datetime.now(UTC)
            record = DocumentRecord(
                document_id=identifier,
                attributes=attributes,
                filename=filename,
                content_hash=extracted.content_hash,
                fingerprint=fingerprint,
                generation="kb-" + uuid4().hex,
                embedding_model=self.embeddings.model,
                embedding_dimensions=self.embeddings.dimensions,
                chunk_count=len(chunks),
                page_count=len(extracted.pages),
                extracted_metadata=extracted.metadata,
                created_at=old.created_at if old else now,
                updated_at=now,
            )
            published = await asyncio.to_thread(
                self.store.publish, record, raw, chunks, vectors, old.generation if old else None
            )
            return IngestionResult(document=published)
        except AppError:
            raise
        except TimeoutError as exc:
            raise AppError("embedding_timeout", "Knowledge processing timed out.", 504) from exc
        except Exception as exc:
            logger.error("knowledge_ingestion_failed", extra={"error_type": type(exc).__name__})
            raise AppError(
                "knowledge_unavailable", "Knowledge processing is unavailable.", 503
            ) from exc

    async def reindex(self, document_id: UUID) -> IngestionResult:
        record, raw = await asyncio.to_thread(self.store.read, document_id)
        return await self.ingest(
            record.filename,
            raw,
            record.attributes,
            document_id,
            force=True,
            expected_generation=record.generation,
        )

    async def delete(self, document_id: UUID) -> None:
        await asyncio.to_thread(self.store.delete, document_id)

    async def search(self, query: KnowledgeQuery) -> KnowledgeResult:
        try:
            if not await self.list_documents():
                return KnowledgeResult()
            async with asyncio.timeout(self.settings.rag_embedding_timeout):
                vectors = await self.embeddings.embed([query.query])
            validate_vectors(vectors, 1, self.embeddings.dimensions)
            return await asyncio.to_thread(
                self.store.search,
                query,
                vectors[0],
                self.embeddings.model,
                self.embeddings.dimensions,
                query.top_k or self.settings.rag_top_k,
                self.settings.rag_max_distance,
            )
        except AppError:
            raise
        except TimeoutError as exc:
            raise AppError("embedding_timeout", "Knowledge search timed out.", 504) from exc
        except Exception as exc:
            logger.error("knowledge_search_failed", extra={"error_type": type(exc).__name__})
            raise AppError(
                "knowledge_unavailable", "Knowledge search is unavailable.", 503
            ) from exc
