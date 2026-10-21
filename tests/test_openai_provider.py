"""Mock the SDK HTTP transport; exercise the real Responses adapter without paid calls."""

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from openai import AsyncOpenAI

from customerops_ai.agents.registry import tool_schemas
from customerops_ai.core.config import Settings
from customerops_ai.core.errors import AppError
from customerops_ai.integrations.openai_provider import OpenAIProvider

pytestmark = pytest.mark.asyncio


def response_payload(output: list[dict[str, Any]], status: str = "completed") -> dict[str, Any]:
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "model": "test-model",
        "status": status,
        "output": output,
        "parallel_tool_calls": False,
        "tools": [],
        "tool_choice": "auto",
    }


def make_client(handler: Callable[[httpx2.Request], httpx2.Response]) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key="fictional-offline-test-key",
        max_retries=0,
        timeout=1,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )


async def test_real_sdk_responses_request_and_text_parsing() -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/responses"
        requests.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json=response_payload(
                [
                    {
                        "type": "message",
                        "id": "msg_test",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": "How can I help?", "annotations": []}
                        ],
                    }
                ]
            ),
        )

    async with make_client(handler) as client:
        reply = await OpenAIProvider(client, Settings(agent_model="test-model")).complete(
            [{"role": "user", "content": "Hello"}],
            tool_schemas(),
        )
    assert reply.text == "How can I help?" and reply.calls == ()
    sent = requests[0]
    assert sent["store"] is False and sent["parallel_tool_calls"] is False
    assert sent["model"] == "test-model" and len(sent["tools"]) == 6
    assert "untrusted data" in sent["instructions"]
    assert sent["include"] == ["reasoning.encrypted_content"]


async def test_function_call_parsing_preserves_reasoning_items() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json=response_payload(
                [
                    {
                        "type": "reasoning",
                        "id": "rs_test",
                        "summary": [],
                        "encrypted_content": "encrypted-fixture",
                    },
                    {
                        "type": "function_call",
                        "id": "fc_test",
                        "call_id": "call_1",
                        "name": "get_product_details",
                        "arguments": "{}",
                        "status": "completed",
                    },
                ]
            ),
        )

    async with make_client(handler) as client:
        reply = await OpenAIProvider(client, Settings(agent_model="test-model")).complete(
            [], tool_schemas()
        )
    assert reply.calls[0].name == "get_product_details"
    assert reply.calls[0].call_id == "call_1"
    assert reply.output_items[0]["encrypted_content"] == "encrypted-fixture"


async def test_provider_timeout_is_sanitized(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("sensitive-provider-content", request=request)

    async with make_client(handler) as client:
        with pytest.raises(AppError) as caught:
            await OpenAIProvider(client, Settings(agent_model="test-model")).complete([], [])
    assert caught.value.code == "provider_timeout" and caught.value.status_code == 504
    assert "sensitive-provider" not in caught.value.message + caplog.text


@pytest.mark.parametrize("status, public_status", [(401, 502), (429, 503), (500, 502)])
async def test_provider_errors_are_not_retried_or_exposed(status: int, public_status: int) -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(status, json={"error": {"message": "sensitive-upstream-message"}})

    async with make_client(handler) as client:
        with pytest.raises(AppError) as caught:
            await OpenAIProvider(client, Settings(agent_model="test-model")).complete([], [])
    assert calls == 1 and caught.value.status_code == public_status
    assert "sensitive" not in caught.value.message


async def test_incomplete_response_is_rejected() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=response_payload([], "incomplete"))

    async with make_client(handler) as client:
        with pytest.raises(AppError, match="provider_incomplete"):
            await OpenAIProvider(client, Settings(agent_model="test-model")).complete([], [])
