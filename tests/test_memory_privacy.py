"""Deterministic minimization and configuration bounds without network or database access."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from customerops_ai.agents.audit import audit_record
from customerops_ai.agents.contracts import ToolCall
from customerops_ai.core.config import Settings
from customerops_ai.core.privacy import redact_sensitive
from customerops_ai.schemas.chat import ToolExecution


@pytest.mark.parametrize(
    "value,secret",
    [
        ("Email PRIVATE@example.test", "PRIVATE@example.test"),
        ("password=fictional-password", "fictional-password"),
        ("API_KEY: fictional-key", "fictional-key"),
        ("Bearer fictional-bearer-value", "fictional-bearer-value"),
        ("sk-fictional-offline-key-value", "sk-fictional-offline-key-value"),
        ("Call +1 202 555 0123", "+1 202 555 0123"),
        ("Call (202) 555-0123", "555-0123"),
        ("Card 4111 1111 1111 1111", "4111 1111 1111 1111"),
    ],
)
def test_common_sensitive_patterns_are_redacted(value: str, secret: str) -> None:
    assert secret not in redact_sensitive(value)


def test_redaction_preserves_operational_ids_and_is_idempotent() -> None:
    text = "Order f78cb256-9215-4442-844d-78d11bac0191 costs USD 24.90"
    assert redact_sensitive(text) == text
    text = "Email private@example.test password=fictional-value"
    assert redact_sensitive(redact_sensitive(text)) == redact_sensitive(text)


@pytest.mark.parametrize(
    "field,value",
    [
        ("memory_message_retention_days", 0),
        ("memory_tool_retention_days", -1),
        ("memory_conversation_retention_days", 0),
        ("memory_history_max_characters", 100),
        ("memory_summary_max_excerpts", 1000),
    ],
)
def test_memory_configuration_bounds(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({field: value})


def test_memory_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUSTOMEROPS_MEMORY_MESSAGE_RETENTION_DAYS", "14")
    monkeypatch.setenv("CUSTOMEROPS_MEMORY_SUMMARY_ENABLED", "false")
    settings = Settings(_env_file=None)
    assert settings.memory_message_retention_days == 14 and not settings.memory_summary_enabled


def test_audit_projects_source_ids_without_document_text_or_query() -> None:
    identifier = "a" * 64
    audit = audit_record(
        ToolCall("call_1", "search_knowledge_base", '{"query":"private question"}'),
        {
            "data": {
                "hits": [
                    {
                        "text": "UNTRUSTED_PRIVATE_EXCERPT",
                        "source": {
                            "citation_id": "KB:" + identifier,
                            "chunk_id": identifier,
                            "document_id": "f78cb256-9215-4442-844d-78d11bac0191",
                            "filename": "PRIVATE_FILENAME",
                        },
                    }
                ]
            }
        },
        ToolExecution(name="search_knowledge_base", status="ok", duration_ms=1.0),
        datetime.now(UTC),
    )
    encoded = str(audit.metadata)
    assert "KB:" + identifier in encoded
    for omitted in ("UNTRUSTED_PRIVATE_EXCERPT", "private question", "PRIVATE_FILENAME"):
        assert omitted not in encoded
