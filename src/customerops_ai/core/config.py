"""Environment-driven application settings."""

from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """Validated configuration; missing database credentials disable database access."""

    model_config = SettingsConfigDict(
        env_prefix="CUSTOMEROPS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = Field(default="CustomerOps AI", min_length=1)
    environment: Literal["development", "test", "production"] = "development"
    database_host: str = Field(default="localhost", min_length=1)
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = Field(default="customerops", pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    database_user: str = Field(default="customerops", min_length=1)
    database_password: SecretStr | None = Field(default=None, min_length=1)
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    database_timeout: float = Field(default=5.0, gt=0, le=60)
    openai_api_key: SecretStr | None = Field(
        default=None,
        min_length=1,
        validation_alias=AliasChoices("OPENAI_API_KEY", "CUSTOMEROPS_OPENAI_API_KEY"),
    )
    agent_model: str | None = Field(default=None, min_length=1)
    agent_provider_timeout: float = Field(default=20, gt=0, le=60)
    agent_turn_timeout: float = Field(default=45, gt=0, le=120)
    agent_tool_timeout: float = Field(default=5, gt=0, le=30)
    agent_max_iterations: int = Field(default=6, ge=1, le=12)
    agent_max_tool_calls: int = Field(default=12, ge=1, le=30)
    agent_max_output_tokens: int = Field(default=1500, ge=128, le=4096)
    agent_history_messages: int = Field(default=20, ge=0, le=50)
    memory_history_max_characters: int = Field(default=24_000, ge=1000, le=48_000)
    memory_history_message_characters: int = Field(default=4000, ge=256, le=8000)
    memory_summary_enabled: bool = True
    memory_summary_max_characters: int = Field(default=2000, ge=256, le=4000)
    memory_summary_max_excerpts: int = Field(default=8, ge=1, le=20)
    memory_summary_excerpt_characters: int = Field(default=200, ge=64, le=500)
    memory_summary_scan_messages: int = Field(default=200, ge=10, le=1000)
    memory_persist_tool_audit: bool = True
    memory_message_retention_days: int = Field(default=30, ge=1, le=3650)
    memory_tool_retention_days: int = Field(default=7, ge=1, le=3650)
    memory_conversation_retention_days: int = Field(default=90, ge=1, le=3650)
    agent_tickets_per_hour: int = Field(default=3, ge=1, le=10)
    auth_token_customers: dict[str, UUID] = Field(default_factory=dict, repr=False)
    auth_admin_token_hashes: list[str] = Field(default_factory=list, repr=False)
    rag_enabled: bool = False
    rag_storage_path: Path = Path(".local/rag")
    rag_embedding_model: str = Field(default="text-embedding-3-small", min_length=1)
    rag_embedding_dimensions: int = Field(default=1536, ge=8, le=4096)
    rag_embedding_batch_size: int = Field(default=16, ge=1, le=32)
    rag_embedding_timeout: float = Field(default=20, gt=0, le=120)
    rag_chunk_size: int = Field(default=1000, ge=128, le=2000)
    rag_chunk_overlap: int = Field(default=150, ge=0)
    rag_top_k: int = Field(default=4, ge=1, le=8)
    rag_max_distance: float = Field(default=0.35, ge=0, le=2)
    rag_max_upload_bytes: int = Field(default=5_242_880, ge=1024, le=20_971_520)
    rag_max_pages: int = Field(default=100, ge=1, le=500)
    rag_max_text_characters: int = Field(default=200_000, ge=1000, le=500_000)
    rag_max_chunks: int = Field(default=500, ge=1, le=1000)

    @field_validator("auth_admin_token_hashes")
    @classmethod
    def validate_admin_hashes(cls, value: list[str]) -> list[str]:
        if any(len(key) != 64 or any(c not in "0123456789abcdef" for c in key) for key in value):
            raise ValueError("Administrator tokens must be lowercase SHA-256 digests")
        return value

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> Self:
        if self.rag_chunk_overlap >= self.rag_chunk_size:
            raise ValueError("RAG overlap must be smaller than chunk size")
        return self

    @field_validator("openai_api_key", "agent_model", mode="before")
    @classmethod
    def empty_optional_agent_settings(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("auth_token_customers")
    @classmethod
    def validate_token_hashes(cls, value: dict[str, UUID]) -> dict[str, UUID]:
        """Only SHA-256 fingerprints belong in server configuration, never raw bearer tokens."""
        if any(len(key) != 64 or any(c not in "0123456789abcdef" for c in key) for key in value):
            raise ValueError("Authentication mapping keys must be lowercase SHA-256 hex digests")
        return value

    @property
    def database_url(self) -> URL:
        """Build a URL safely, including passwords containing reserved URL characters."""
        if self.database_password is None:
            raise ValueError("Set CUSTOMEROPS_DATABASE_PASSWORD to enable database access")
        return URL.create(
            "postgresql+asyncpg",
            username=self.database_user,
            password=self.database_password.get_secret_value(),
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        )
