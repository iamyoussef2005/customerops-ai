"""Local persistent vectors with an atomic active-generation manifest.

Only manifest-selected collections are searchable. Failed publication never replaces
the previous index. All synchronous operations run in worker threads at the service boundary.
"""

import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast
from uuid import UUID

import chromadb
from chromadb.api.client import Client
from chromadb.api.types import Embeddings
from chromadb.config import Settings as ChromaSettings
from filelock import FileLock

from customerops_ai.core.errors import AppError
from customerops_ai.rag.processing import Chunk
from customerops_ai.schemas.knowledge import (
    DocumentRecord,
    KnowledgeHit,
    KnowledgeQuery,
    KnowledgeResult,
    SourceReference,
)

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.root / "operations.lock"), timeout=30)
        self.client = chromadb.PersistentClient(
            path=str(self.root / "chroma"), settings=ChromaSettings(anonymized_telemetry=False)
        )
        with self.lock, self.connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS documents "
                "(id TEXT PRIMARY KEY, source TEXT UNIQUE, hash TEXT UNIQUE, "
                "record TEXT NOT NULL, raw BLOB NOT NULL)"
            )
            active = {
                DocumentRecord.model_validate_json(row[0]).generation
                for row in connection.execute("SELECT record FROM documents")
            }
            for collection in self.client.list_collections():
                if collection.name.startswith("kb-") and collection.name not in active:
                    self.cleanup(collection.name)

    def close(self) -> None:
        # PersistentClient returns Client; Chroma's ClientAPI annotation omits its close method.
        cast(Client, self.client).close()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.root / "manifest.sqlite3", timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def list_documents(self) -> list[DocumentRecord]:
        with self.lock, self.connection() as connection:
            return [
                DocumentRecord.model_validate_json(row[0])
                for row in connection.execute("SELECT record FROM documents ORDER BY source")
            ]

    def read(self, document_id: UUID) -> tuple[DocumentRecord, bytes]:
        with self.lock, self.connection() as connection:
            row = connection.execute(
                "SELECT record, raw FROM documents WHERE id = ?", (str(document_id),)
            ).fetchone()
            if row is None:
                raise AppError("document_not_found", "Document not found.", 404)
            return DocumentRecord.model_validate_json(row[0]), bytes(row[1])

    def publish(
        self,
        record: DocumentRecord,
        raw: bytes,
        chunks: list[Chunk],
        vectors: list[list[float]],
        expected: str | None,
    ) -> DocumentRecord:
        with self.lock, self.connection() as connection:
            row = connection.execute(
                "SELECT record FROM documents WHERE id = ?", (str(record.document_id),)
            ).fetchone()
            old = DocumentRecord.model_validate_json(row[0]) if row else None
            if (old.generation if old else None) != expected:
                raise AppError("document_conflict", "Document changed; retry the operation.", 409)
            duplicate = connection.execute(
                "SELECT id FROM documents WHERE hash = ? AND id != ?",
                (record.content_hash, str(record.document_id)),
            ).fetchone()
            if duplicate:
                raise AppError("document_conflict", "Identical content is already indexed.", 409)
            collection = self.client.create_collection(
                record.generation,
                embedding_function=None,
                configuration={"hnsw": {"space": "cosine"}},
            )
            try:
                for offset in range(0, len(chunks), 64):
                    batch = chunks[offset : offset + 64]
                    sources = [self.source(record, chunk) for chunk in batch]
                    collection.add(
                        ids=[source.chunk_id for source in sources],
                        documents=[chunk.text for chunk in batch],
                        embeddings=cast(Embeddings, vectors[offset : offset + 64]),
                        metadatas=[
                            {
                                "source_json": source.model_dump_json(),
                                "category": record.attributes.category,
                                "source_key": record.attributes.source_key,
                                "document_id": str(record.document_id),
                            }
                            for source in sources
                        ],
                    )
                connection.execute(
                    "INSERT INTO documents VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET source=excluded.source, hash=excluded.hash, "
                    "record=excluded.record, raw=excluded.raw",
                    (
                        str(record.document_id),
                        record.attributes.source_key,
                        record.content_hash,
                        record.model_dump_json(),
                        raw,
                    ),
                )
                connection.commit()
            except BaseException:
                self.cleanup(record.generation)
                raise
            if old:
                self.cleanup(old.generation)
            return record

    @staticmethod
    def source(record: DocumentRecord, chunk: Chunk) -> SourceReference:
        from hashlib import sha256

        identifier = sha256(
            f"{record.document_id}:{record.fingerprint}:{chunk.index}".encode()
        ).hexdigest()
        return SourceReference(
            citation_id=f"KB:{identifier}",
            document_id=record.document_id,
            chunk_id=identifier,
            source_key=record.attributes.source_key,
            title=record.attributes.title,
            filename=record.filename,
            page=chunk.page,
            chunk_index=chunk.index,
            start_char=chunk.start,
            end_char=chunk.end,
        )

    def cleanup(self, generation: str) -> None:
        try:
            self.client.delete_collection(generation)
        except Exception:
            # An orphan is never selected by the manifest and cannot contaminate retrieval.
            logger.warning("rag_retired_collection_cleanup_failed")

    def delete(self, document_id: UUID) -> None:
        with self.lock, self.connection() as connection:
            record, _ = self.read(document_id)
            connection.execute("DELETE FROM documents WHERE id = ?", (str(document_id),))
            connection.commit()
            self.cleanup(record.generation)

    def search(
        self,
        query: KnowledgeQuery,
        vector: list[float],
        model: str,
        dimensions: int,
        top_k: int,
        max_distance: float,
    ) -> KnowledgeResult:
        with self.lock:
            records = self.list_documents()
            hits: list[KnowledgeHit] = []
            for record in records:
                filters = query.filters
                if filters and (
                    (filters.document_id and filters.document_id != record.document_id)
                    or (filters.category and filters.category != record.attributes.category)
                    or (filters.source_key and filters.source_key != record.attributes.source_key)
                ):
                    continue
                if (record.embedding_model, record.embedding_dimensions) != (model, dimensions):
                    raise AppError("reindex_required", "Knowledge requires re-indexing.", 503)
                collection = self.client.get_collection(record.generation, embedding_function=None)
                result = collection.query(
                    query_embeddings=cast(Embeddings, [vector]),
                    n_results=min(top_k, record.chunk_count),
                    include=["documents", "metadatas", "distances"],
                )
                documents = result["documents"]
                metadata = result["metadatas"]
                distances = result["distances"]
                if documents is None or metadata is None or distances is None:
                    raise AppError("index_invalid", "Knowledge is temporarily unavailable.", 503)
                for text, attributes, distance in zip(
                    documents[0], metadata[0], distances[0], strict=True
                ):
                    if distance <= max_distance:
                        hits.append(
                            KnowledgeHit(
                                text=text,
                                distance=distance,
                                source=SourceReference.model_validate(
                                    json.loads(str(attributes["source_json"]))
                                ),
                            )
                        )
            hits.sort(key=lambda hit: (hit.distance, hit.source.chunk_id))
            return KnowledgeResult(hits=hits[:top_k], evidence_available=bool(hits))
