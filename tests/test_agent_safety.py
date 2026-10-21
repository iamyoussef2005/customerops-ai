"""Additional bounded tool execution and recovery cases."""

import json

import pytest

from customerops_ai.agents.contracts import ProviderReply, ToolCall
from customerops_ai.agents.execution import ToolExecutor
from tests.agent_helpers import PRODUCT_ID, FakeOperations, FakeProvider, tool_reply
from tests.test_agent import agent

pytestmark = pytest.mark.asyncio


async def test_failed_tool_result_reaches_provider_for_honest_fallback() -> None:
    operations = FakeOperations()
    operations.failure = RuntimeError("private-internal-message")
    provider = FakeProvider(
        tool_reply("check_product_stock", json.dumps({"product_id": PRODUCT_ID})),
        ProviderReply(text="Stock lookup is temporarily unavailable."),
    )
    answer, traces = await agent(provider, operations).run([])
    assert "unavailable" in answer and traces[0].error_code == "tool_failure"
    output = json.loads(str(provider.inputs[1][-1]["output"]))
    assert output["error_code"] == "tool_failure"
    assert "private-internal" not in str(provider.inputs)


@pytest.mark.parametrize(
    "name, arguments",
    [
        ("search_products", '{"query":"lamp","filters":{"min_price":100.0,"max_price":1.0}}'),
        ("search_products", '{"query":"lamp","filters":{"in_stock":"yes"}}'),
        ("create_support_ticket", '{"subject":" ","description":"enough description text"}'),
        ("create_support_ticket", json.dumps({"subject": "Demo", "description": "x" * 2001})),
    ],
)
async def test_filter_and_ticket_abuse_validation(name: str, arguments: str) -> None:
    operations = FakeOperations()
    result, _ = await ToolExecutor(operations, 1).execute(ToolCall("one", name, arguments))
    assert result.error_code == "invalid_arguments" and operations.calls == []
