"""Real Responses function-call round trip; tool result is a labeled synthetic fixture.

This verifies the live provider contract, not the database or order/ticket business workflows.
Requires explicit opt-in, OPENAI_API_KEY, and CUSTOMEROPS_AGENT_MODEL. Makes two paid requests.
"""

import os

import pytest
from openai import AsyncOpenAI

from customerops_ai.agents.registry import tool_schemas
from customerops_ai.core.config import Settings
from customerops_ai.integrations.openai_provider import OpenAIProvider

pytestmark = [
    pytest.mark.live,
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("CUSTOMEROPS_RUN_LIVE_SMOKE") != "1",
        reason="Paid live smoke requires explicit opt-in",
    ),
]


async def test_live_responses_tool_round_trip() -> None:
    settings = Settings()
    if not os.environ.get("OPENAI_API_KEY") or settings.openai_api_key is None:
        pytest.fail("Set OPENAI_API_KEY for the explicitly requested live smoke")
    if settings.agent_model is None:
        pytest.fail(
            "Set CUSTOMEROPS_AGENT_MODEL to a Responses function-calling model "
            "available to your account"
        )
    async with AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=settings.agent_provider_timeout,
        max_retries=0,
    ) as client:
        provider = OpenAIProvider(client, settings)
        first = await provider.complete(
            [
                {
                    "role": "user",
                    "content": "Check stock using check_product_stock for product UUID "
                    "f78cb256-9215-4442-844d-78d11bac0191.",
                }
            ],
            tool_schemas(),
        )
        assert len(first.calls) == 1 and first.calls[0].name == "check_product_stock"
        items = list(first.output_items)
        items.append(
            {
                "type": "function_call_output",
                "call_id": first.calls[0].call_id,
                "output": '{"status":"ok","data":{"stock_quantity":7,"in_stock":true,'
                '"fixture":"synthetic smoke data"}}',
            }
        )
        answer = await provider.complete(items, tool_schemas())
        assert answer.text.strip() and not answer.calls
