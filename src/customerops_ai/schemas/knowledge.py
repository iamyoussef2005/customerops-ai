"""Public document metadata and retrieval/source contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentAttributes(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,119}$")
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(default="general", pattern=r"^[a-z0-9][a-z0-9_-]{0,59}$")
    custom: dict[str, str] = Field(default_factory=dict, max_length=10)

    @field_validator("custom")
    @classmethod
    def bounded_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not 1 <= len(key) <= 40 or not 1 <= len(item) <= 200 for key, item in value.items()):
            raise ValueError("Metadata keys/values exceed their limits")
        return value


class DocumentRecord(BaseModel):
    document_id: UUID
    attributes: DocumentAttributes
    filename: str
    content_hash: str
    fingerprint: str
    generation: str
    embedding_model: str
    embedding_dimensions: int
    chunk_count: int
    page_count: int
    extracted_metadata: dict[str, str]
    created_at: datetime
    updated_at: datetime


class IngestionResult(BaseModel):
    document: DocumentRecord
    duplicate: bool = False


class KnowledgeFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID | None = None
    category: str | None = Field(default=None, max_length=60)
    source_key: str | None = Field(default=None, max_length=120)


class KnowledgeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=500)
    top_k: int | None = Field(default=None, ge=1, le=8)
    filters: KnowledgeFilters | None = None


class SourceReference(BaseModel):
    citation_id: str
    document_id: UUID
    chunk_id: str
    source_key: str
    title: str
    filename: str
    page: int
    chunk_index: int
    start_char: int
    end_char: int


class KnowledgeHit(BaseModel):
    text: str
    distance: float
    source: SourceReference


class KnowledgeResult(BaseModel):
    hits: list[KnowledgeHit] = Field(default_factory=list)
    evidence_available: bool = False
