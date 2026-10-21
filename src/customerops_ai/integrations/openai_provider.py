"""Official asynchronous Responses SDK adapter; this is the only provider-specific boundary."""

import logging
from collections.abc import Sequence
from typing import cast

from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError
from openai.types.responses import ResponseInputItemParam, ToolParam

from customerops_ai.agents.contracts import JsonObject, ProviderReply, ToolCall
from customerops_ai.agents.orchestrator import INSTRUCTIONS
from customerops_ai.core.config import Settings
from customerops_ai.core.errors import AppError

logger = logging.getLogger(__name__)


class OpenAIProvider:
    def __init__(self, client: AsyncOpenAI, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    async def complete(
        self,
        items: Sequence[JsonObject],
        tools: Sequence[JsonObject],
    ) -> ProviderReply:
        if self.settings.agent_model is None:
            raise AppError("agent_not_configured", "The assistant is not configured.", 503)
        try:
            response = await self.client.responses.create(
                model=self.settings.agent_model,
                instructions=INSTRUCTIONS,
                input=cast(list[ResponseInputItemParam], list(items)),
                tools=cast(list[ToolParam], list(tools)),
                store=False,
                include=["reasoning.encrypted_content"],
                parallel_tool_calls=False,
                max_output_tokens=self.settings.agent_max_output_tokens,
            )
        except APITimeoutError as exc:
            logger.warning("provider_timeout")
            raise AppError(
                "provider_timeout", "The assistant timed out. Please try again.", 504
            ) from exc
        except RateLimitError as exc:
            logger.warning("provider_rate_limit")
            raise AppError(
                "provider_unavailable", "The assistant is temporarily unavailable.", 503
            ) from exc
        except APIError as exc:
            logger.warning("provider_error", extra={"error_type": type(exc).__name__})
            raise AppError(
                "provider_unavailable", "The assistant is temporarily unavailable.", 502
            ) from exc
        if response.status != "completed":
            raise AppError(
                "provider_incomplete", "The assistant could not complete this request.", 502
            )
        calls = tuple(
            ToolCall(item.call_id, item.name, item.arguments)
            for item in response.output
            if item.type == "function_call"
        )
        text = response.output_text
        if not text and not calls:
            refusals = [
                part.refusal
                for item in response.output
                if item.type == "message"
                for part in item.content
                if part.type == "refusal"
            ]
            text = " ".join(refusals)
        return ProviderReply(
            text=text,
            calls=calls,
            output_items=[
                cast(JsonObject, item.model_dump(mode="json", exclude_none=True))
                for item in response.output
            ],
        )
