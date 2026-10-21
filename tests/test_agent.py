"""Offline deterministic agent state-machine tests; no SDK requests or database mocks hidden."""

import asyncio
import json

import pytest

from customerops_ai.agents.contracts import JsonObject, ProviderReply, ToolCall
from customerops_ai.agents.execution import ToolExecutor
from customerops_ai.agents.orchestrator import AgentOrchestrator
from customerops_ai.agents.registry import tool_schemas
from customerops_ai.core.config import Settings
from customerops_ai.core.errors import AppError
from tests.agent_helpers import PRODUCT_ID, FakeOperations, FakeProvider, tool_reply

pytestmark = pytest.mark.asyncio


def agent(
    provider: FakeProvider,
    operations: FakeOperations,
    agent_max_iterations: int = 6,
    agent_max_tool_calls: int = 12,
) -> AgentOrchestrator:
    return AgentOrchestrator(
        provider,
        ToolExecutor(operations, 1),
        Settings(
            agent_max_iterations=agent_max_iterations,
            agent_max_tool_calls=agent_max_tool_calls,
        ),
    )


async def test_normal_conversation() -> None:
    provider = FakeProvider(ProviderReply(text="How can I help with your order?"))
    operations = FakeOperations()
    answer, trace = await agent(provider, operations).run([{"role": "user", "content": "Hello"}])
    assert answer == "How can I help with your order?"
    assert trace == [] and operations.calls == []


async def test_single_tool_call() -> None:
    provider = FakeProvider(
        tool_reply("check_product_stock", json.dumps({"product_id": PRODUCT_ID})),
        ProviderReply(text="There are 7 available."),
    )
    answer, traces = await agent(provider, FakeOperations()).run([])
    assert answer == "There are 7 available."
    result = json.loads(str(provider.inputs[1][-1]["output"]))
    assert result["data"]["stock_quantity"] == 7
    assert provider.inputs[1][-1]["call_id"] == "call_1"
    assert traces[0].status == "ok" and traces[0].duration_ms >= 0


async def test_multiple_sequential_tool_calls_preserve_outputs_and_reasoning() -> None:
    first = tool_reply("search_products", '{"query":"lamp","filters":null}')
    reasoning: JsonObject = {"type": "reasoning", "encrypted_content": "encrypted-test-fixture"}
    first.output_items.insert(0, reasoning)
    provider = FakeProvider(
        first,
        tool_reply("get_product_details", json.dumps({"product_id": PRODUCT_ID}), "call_2"),
        tool_reply("check_product_stock", json.dumps({"product_id": PRODUCT_ID}), "call_3"),
        ProviderReply(text="The lamp is available."),
    )
    operations = FakeOperations()
    _, traces = await agent(provider, operations).run([])
    assert operations.calls == ["search_products", "get_product_details", "check_product_stock"]
    assert len(traces) == 3
    assert reasoning in provider.inputs[1]
    assert sum(item.get("type") == "function_call_output" for item in provider.inputs[-1]) == 3


async def test_multiple_calls_in_one_reply_are_executed_sequentially() -> None:
    one = tool_reply("get_product_details", json.dumps({"product_id": PRODUCT_ID}), "one")
    two = tool_reply("check_product_stock", json.dumps({"product_id": PRODUCT_ID}), "two")
    provider = FakeProvider(
        ProviderReply(
            calls=(*one.calls, *two.calls), output_items=one.output_items + two.output_items
        ),
        ProviderReply(text="Available."),
    )
    operations = FakeOperations()
    await agent(provider, operations).run([])
    assert operations.calls == ["get_product_details", "check_product_stock"]


@pytest.mark.parametrize(
    "arguments",
    [
        "",
        "not json",
        "{}",
        "null",
        "[]",
        '{"product_id":"not-a-uuid"}',
        json.dumps({"product_id": PRODUCT_ID, "customer_id": PRODUCT_ID}),
        '{"product_id":"' + PRODUCT_ID + '","product_id":"' + PRODUCT_ID + '"}',
        "x" * 8200,
    ],
)
async def test_invalid_tool_arguments_never_execute(arguments: str) -> None:
    operations = FakeOperations()
    result, trace = await ToolExecutor(operations, 1).execute(
        ToolCall("one", "get_product_details", arguments)
    )
    assert result.error_code == "invalid_arguments"
    assert trace.status == "error" and operations.calls == []


async def test_invalid_arguments_can_be_corrected_by_next_response() -> None:
    provider = FakeProvider(
        tool_reply("check_product_stock", "{}"),
        tool_reply("check_product_stock", json.dumps({"product_id": PRODUCT_ID}), "call_2"),
        ProviderReply(text="7 available."),
    )
    operations = FakeOperations()
    _, trace = await agent(provider, operations).run([])
    assert [item.status for item in trace] == ["error", "ok"]
    assert operations.calls == ["check_product_stock"]


async def test_unauthorized_order_error_is_structured() -> None:
    operations = FakeOperations()
    operations.failure = AppError("not_found", "Order not found.", 404)
    result, _ = await ToolExecutor(operations, 1).execute(
        ToolCall("one", "get_order_status", json.dumps({"order_id": PRODUCT_ID}))
    )
    assert result.status == "error" and result.error_code == "not_found"
    assert result.data is None


async def test_maximum_iteration_limit_does_not_execute_last_batch() -> None:
    provider = FakeProvider(
        tool_reply("check_product_stock", json.dumps({"product_id": PRODUCT_ID}), "one"),
        tool_reply("check_product_stock", json.dumps({"product_id": PRODUCT_ID}), "two"),
    )
    operations = FakeOperations()
    with pytest.raises(AppError, match="agent_iteration_limit"):
        await agent(provider, operations, agent_max_iterations=2).run([])
    assert len(provider.inputs) == 2 and len(operations.calls) == 1


async def test_total_tool_limit() -> None:
    provider = FakeProvider(
        tool_reply("check_product_stock", json.dumps({"product_id": PRODUCT_ID}), "one"),
        tool_reply("check_product_stock", json.dumps({"product_id": PRODUCT_ID}), "two"),
    )
    with pytest.raises(AppError, match="agent_iteration_limit"):
        await agent(provider, FakeOperations(), agent_max_tool_calls=1).run([])


async def test_repeated_call_id_is_rejected() -> None:
    provider = FakeProvider(
        tool_reply("check_product_stock", json.dumps({"product_id": PRODUCT_ID})),
        tool_reply("check_product_stock", json.dumps({"product_id": PRODUCT_ID})),
    )
    with pytest.raises(AppError, match="provider_invalid_response"):
        await agent(provider, FakeOperations()).run([])


async def test_tool_execution_failure_is_sanitized_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    operations = FakeOperations()
    operations.failure = RuntimeError("secret-customer-data-and-database-password")
    result, trace = await ToolExecutor(operations, 1).execute(
        ToolCall("one", "check_product_stock", json.dumps({"product_id": PRODUCT_ID}))
    )
    assert result.error_code == "tool_failure" and trace.status == "error"
    assert "secret-customer" not in result.model_dump_json() + caplog.text
    assert "tool_failed" in caplog.text


async def test_tool_timeout() -> None:
    class SlowOperations(FakeOperations):
        async def check_product_stock(self, product_id: object) -> JsonObject:
            await asyncio.sleep(1)
            return {}

    result, _ = await ToolExecutor(SlowOperations(), 0.01).execute(
        ToolCall("one", "check_product_stock", json.dumps({"product_id": PRODUCT_ID}))
    )
    assert result.error_code == "tool_timeout"


async def test_unsupported_operations_are_refused_without_dispatch() -> None:
    operations = FakeOperations()
    result, _ = await ToolExecutor(operations, 1).execute(ToolCall("one", "refund_order", "{}"))
    assert result.error_code == "unsupported_tool" and operations.calls == []


async def test_strict_schemas_have_no_identity_parameters() -> None:
    def verify(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value["properties"])
                assert "customer_id" not in value["properties"]
            for child in value.values():
                verify(child)
        elif isinstance(value, list):
            for child in value:
                verify(child)

    for tool in tool_schemas():
        assert tool["strict"] is True
        verify(tool["parameters"])
