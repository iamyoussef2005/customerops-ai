"""Validate and execute allowlisted business operations with bounded time and safe results."""

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from time import perf_counter
from typing import Literal, cast

from pydantic import BaseModel, JsonValue, ValidationError

from customerops_ai.agents.audit import ToolAudit, audit_record
from customerops_ai.agents.contracts import ToolCall
from customerops_ai.agents.registry import TOOLS
from customerops_ai.agents.tool_schemas import (
    CreateSupportTicket,
    OrderLookup,
    ProductLookup,
    SearchKnowledge,
    SearchProducts,
)
from customerops_ai.core.errors import AppError
from customerops_ai.schemas.chat import ToolExecution
from customerops_ai.schemas.knowledge import KnowledgeQuery, SourceReference
from customerops_ai.services.customer_tools import ToolOperations
from customerops_ai.services.knowledge import KnowledgeService

logger = logging.getLogger(__name__)


class ToolResult(BaseModel):
    status: Literal["ok", "error"]
    data: JsonValue = None
    error_code: str | None = None
    message: str | None = None


def no_duplicate_keys(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate argument key")
        result[key] = value
    return result


class ToolExecutor:
    def __init__(
        self, operations: ToolOperations, timeout: float, knowledge: KnowledgeService | None = None
    ) -> None:
        self.operations = operations
        self.timeout = timeout
        self.knowledge = knowledge
        self.sources: dict[str, SourceReference] = {}
        self.knowledge_requested = False
        self.ticket_authorized = False
        self.audits: list[ToolAudit] = []

    def cited_sources(self, text: str) -> list[SourceReference]:
        identifiers = list(dict.fromkeys(re.findall(r"\[(KB:[^\]]+)\]", text)))
        return [self.sources[key] for key in identifiers if key in self.sources]

    def grounded_answer(self, text: str, required: bool) -> str:
        if required or self.knowledge_requested:
            citations = re.findall(r"\[(KB:[^\]]+)\]", text)
            if not citations or any(key not in self.sources for key in citations):
                return (
                    "I don't know the applicable company policy from the available documents. "
                    "Please request human support for clarification."
                )
        return text

    async def execute(self, call: ToolCall) -> tuple[ToolResult, ToolExecution]:
        started = perf_counter()
        name = call.name if call.name in TOOLS else "unknown"
        try:
            if name == "unknown":
                raise AppError("unsupported_tool", "This operation is not supported.")
            if len(call.arguments.encode("utf-8")) > 8192:
                raise ValueError("Arguments exceed limit")
            json.loads(call.arguments, object_pairs_hook=no_duplicate_keys)
            arguments = TOOLS[name].arguments.model_validate_json(call.arguments)
            async with asyncio.timeout(self.timeout):
                if isinstance(arguments, SearchKnowledge):
                    self.knowledge_requested = True
                    if self.knowledge is None:
                        raise AppError(
                            "knowledge_unavailable",
                            "Company policy information is unavailable.",
                            503,
                        )
                    evidence = await self.knowledge.search(KnowledgeQuery(query=arguments.query))
                    for hit in evidence.hits:
                        self.sources[hit.source.citation_id] = hit.source
                    data = cast(JsonValue, evidence.model_dump(mode="json"))
                elif isinstance(arguments, SearchProducts):
                    data = await self.operations.search_products(arguments.query, arguments.filters)
                elif isinstance(arguments, OrderLookup):
                    data = await self.operations.get_order_status(arguments.order_id)
                elif isinstance(arguments, CreateSupportTicket):
                    if not self.ticket_authorized:
                        raise AppError(
                            "customer_request_required",
                            "Please explicitly request a support ticket or human assistance first.",
                            403,
                        )
                    data = await self.operations.create_support_ticket(
                        arguments.subject, arguments.description
                    )
                elif isinstance(arguments, ProductLookup) and name == "get_product_details":
                    data = await self.operations.get_product_details(arguments.product_id)
                elif isinstance(arguments, ProductLookup):
                    data = await self.operations.check_product_stock(arguments.product_id)
                else:
                    raise AppError("unsupported_tool", "This operation is not supported.")
            result = ToolResult(status="ok", data=data)
            if len(result.model_dump_json()) > (
                32_000 if name == "search_knowledge_base" else 16_000
            ):
                result = ToolResult(
                    status="error",
                    error_code="result_too_large",
                    message="Please narrow your request.",
                )
        except (ValueError, ValidationError, RecursionError):
            result = ToolResult(
                status="error",
                error_code="invalid_arguments",
                message="Tool arguments are missing or invalid.",
            )
        except AppError as exc:
            result = ToolResult(status="error", error_code=exc.code, message=exc.message)
        except TimeoutError:
            result = ToolResult(
                status="error",
                error_code="tool_timeout",
                message="This operation timed out. Please try again.",
            )
        except Exception:
            result = ToolResult(
                status="error",
                error_code="tool_failure",
                message="This operation is temporarily unavailable.",
            )
        trace = ToolExecution(
            name=name,
            status="ok" if result.status == "ok" else "error",
            duration_ms=round((perf_counter() - started) * 1000, 3),
            error_code=result.error_code,
        )
        self.audits.append(
            audit_record(
                call,
                cast(dict[str, JsonValue], result.model_dump(mode="json")),
                trace,
                datetime.now(UTC),
            )
        )
        logger.info(
            "tool_execution",
            extra={
                "tool": name,
                "duration_ms": trace.duration_ms,
                "outcome": trace.status,
                "error_code": trace.error_code,
            },
        )
        if trace.status == "error":
            logger.warning("tool_failed", extra={"tool": name, "error_code": trace.error_code})
        return result, trace
