"""Audit projections deliberately exclude free-form queries, ticket descriptions and excerpts."""

import json
import re
from dataclasses import dataclass
from datetime import datetime

from pydantic import JsonValue

from customerops_ai.agents.contracts import ToolCall
from customerops_ai.core.types import JsonObject
from customerops_ai.schemas.chat import ToolExecution


@dataclass(frozen=True)
class ToolAudit:
    finished_at: datetime
    metadata: JsonObject


def audit_record(
    call: ToolCall, result: JsonObject, trace: ToolExecution, finished_at: datetime
) -> ToolAudit:
    arguments: JsonObject = {}
    # Never retain raw malformed arguments. Only validated identifier-shaped values are useful.
    if (
        trace.name != "unknown"
        and trace.error_code != "invalid_arguments"
        and len(call.arguments) <= 8192
    ):
        try:
            parsed = json.loads(call.arguments)
            if isinstance(parsed, dict):
                for key in ("product_id", "order_id"):
                    value = parsed.get(key)
                    if isinstance(value, str) and re.fullmatch(r"[a-fA-F0-9-]{36}", value):
                        arguments[key] = value
        except (ValueError, RecursionError):
            pass
    projected: JsonObject = {}
    data = result.get("data")
    if isinstance(data, dict):
        for key in (
            "product_id",
            "order_id",
            "ticket_id",
            "status",
            "stock_quantity",
            "in_stock",
            "already_exists",
            "human_connected",
            "evidence_available",
        ):
            value = data.get(key)
            if isinstance(value, bool | int | float):
                projected[key] = value
            elif isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
                projected[key] = value
        for key in ("products", "hits"):
            rows = data.get(key)
            if isinstance(rows, list):
                projected[f"{key}_count"] = len(rows)
                references: list[JsonValue] = []
                for row in rows[:10]:
                    if not isinstance(row, dict):
                        continue
                    source = row.get("source") if key == "hits" else row
                    if not isinstance(source, dict):
                        continue
                    reference: JsonObject = {}
                    for field in ("product_id", "document_id", "chunk_id", "citation_id"):
                        value = source.get(field)
                        if isinstance(value, str) and re.fullmatch(
                            r"(?:KB:)?[a-fA-F0-9-]{32,64}", value
                        ):
                            reference[field] = value
                    if reference:
                        references.append(reference)
                projected[f"{key}_references"] = references
    safe_id = call.call_id if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", call.call_id) else "redacted"
    metadata: JsonObject = {
        "version": 1,
        "call_id": safe_id,
        "name": trace.name,
        "arguments": arguments,
        "result": projected,
        "status": trace.status,
        "error_code": trace.error_code,
        "duration_ms": trace.duration_ms,
    }
    return ToolAudit(finished_at, metadata)
