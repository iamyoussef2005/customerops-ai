"""A small provider boundary used by the orchestrator and offline test doubles."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from customerops_ai.core.types import JsonObject as JsonObject


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ProviderReply:
    text: str = ""
    calls: tuple[ToolCall, ...] = ()
    output_items: list[JsonObject] = field(default_factory=list)


class LLMProvider(Protocol):
    async def complete(
        self,
        items: Sequence[JsonObject],
        tools: Sequence[JsonObject],
    ) -> ProviderReply: ...
