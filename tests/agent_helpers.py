"""Explicit in-memory test doubles for the provider and business-operation boundaries."""

from collections.abc import Sequence
from copy import deepcopy
from uuid import UUID

from customerops_ai.agents.contracts import JsonObject, ProviderReply, ToolCall
from customerops_ai.schemas.products import ProductFilters

PRODUCT_ID = "f78cb256-9215-4442-844d-78d11bac0191"


class FakeProvider:
    def __init__(self, *replies: ProviderReply | Exception) -> None:
        self.replies = list(replies)
        self.inputs: list[list[JsonObject]] = []
        self.tools: list[list[JsonObject]] = []

    async def complete(
        self,
        items: Sequence[JsonObject],
        tools: Sequence[JsonObject],
    ) -> ProviderReply:
        self.inputs.append(deepcopy(list(items)))
        self.tools.append(deepcopy(list(tools)))
        if not self.replies:
            raise AssertionError("Unexpected extra provider request")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def tool_reply(name: str, arguments: str, call_id: str = "call_1") -> ProviderReply:
    call = ToolCall(call_id, name, arguments)
    return ProviderReply(
        calls=(call,),
        output_items=[
            {
                "type": "function_call",
                "call_id": call.call_id,
                "name": call.name,
                "arguments": call.arguments,
            }
        ],
    )


class FakeOperations:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failure: Exception | None = None

    def record(self, name: str) -> None:
        self.calls.append(name)
        if self.failure is not None:
            raise self.failure

    async def search_products(self, query: str, filters: ProductFilters | None) -> JsonObject:
        self.record("search_products")
        return {"products": [{"product_id": PRODUCT_ID, "name": "Fictional Desk Lamp"}]}

    async def get_product_details(self, product_id: UUID) -> JsonObject:
        self.record("get_product_details")
        return {"product_id": str(product_id), "name": "Fictional Desk Lamp"}

    async def check_product_stock(self, product_id: UUID) -> JsonObject:
        self.record("check_product_stock")
        return {"product_id": str(product_id), "stock_quantity": 7, "in_stock": True}

    async def get_order_status(self, order_id: UUID) -> JsonObject:
        self.record("get_order_status")
        return {"status": "shipped"}

    async def create_support_ticket(self, subject: str, description: str) -> JsonObject:
        self.record("create_support_ticket")
        return {"ticket_id": "fictional-ticket", "status": "open", "human_connected": False}
