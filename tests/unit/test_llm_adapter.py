import asyncio
import json

import httpx
import pytest

from app.agent.llm import LLMError, OpenAICompatibleModel
from app.core.config import Settings
from app.tools.registry import tool_schemas


@pytest.fixture
def settings():
    return Settings(_env_file=None, database_url="postgresql+asyncpg://test:example@localhost/unit_test",
                    llm_base_url="https://model.invalid/v1", llm_api_key="private-key",
                    llm_model="configured-model", llm_timeout_seconds=0.1)


async def test_adapter_request_schema_and_tool_call_parsing(settings):
    schemas = [{"type": "function", "function": {k: schema[k] for k in ("name", "description", "parameters")}}
               for schema in tool_schemas()]
    def handler(request):
        assert str(request.url) == "https://model.invalid/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "configured-model" and body["tools"] == schemas
        assert request.headers["Authorization"] == "Bearer private-key"
        assert body["messages"][0]["content"] == "查订单"
        return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None, "tool_calls": [
                {"id": "call-1", "type": "function", "function": {"name": "get_order", "arguments": '{"order_no":"O1"}'}}
            ]}}]})
    model = OpenAICompatibleModel(settings, transport=httpx.MockTransport(handler))
    reply = await model.complete([{"role": "user", "content": "查订单"}], schemas)
    assert reply.tool_calls[0].function.parsed_arguments() == {"order_no": "O1"}


async def test_terminal_response_and_no_tools(settings):
    def handler(request):
        assert "tools" not in json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": '{"action":"answer"}'}}]})
    reply = await OpenAICompatibleModel(settings, transport=httpx.MockTransport(handler)).complete([], [])
    assert json.loads(reply.content)["action"] == "answer" and not reply.tool_calls


@pytest.mark.parametrize(("status", "code"), [(401, "llm_api_error"), (400, "llm_api_error"), (429, "llm_unavailable"), (503, "llm_unavailable"), (307, "llm_api_error")])
async def test_http_errors_safe_no_retry(settings, status, code):
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(status, text="private-key private-provider-error", headers={"Location": "https://other.invalid"})
    with pytest.raises(LLMError) as caught:
        await OpenAICompatibleModel(settings, transport=httpx.MockTransport(handler)).complete([], [])
    assert str(caught.value) == code and count == 1


@pytest.mark.parametrize(("error", "code"), [(httpx.ConnectError("private"), "llm_unavailable"), (httpx.ReadTimeout("private"), "llm_timeout")])
async def test_network_errors(settings, error, code):
    def handler(request):
        raise error
    with pytest.raises(LLMError, match=code):
        await OpenAICompatibleModel(settings, transport=httpx.MockTransport(handler)).complete([], [])


async def test_wall_clock_model_timeout(settings):
    async def handler(request):
        await asyncio.sleep(10)
    with pytest.raises(LLMError, match="llm_timeout"):
        await OpenAICompatibleModel(settings, transport=httpx.MockTransport(handler)).complete([], [])


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": [{"finish_reason": "length", "message": {}}]},
    {"choices": [{"finish_reason": "stop", "message": "private"}]},
    {"choices": [{"finish_reason": "stop", "message": {"role": "tool", "content": "private"}}]},
    {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": None}}]},
    {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "tool_calls": [
        {"id": "x", "function": {"name": "get_order", "arguments": "{}"}},
        {"id": "x", "function": {"name": "get_order", "arguments": "{}"}}]}}]},
])
async def test_bad_response(settings, payload):
    with pytest.raises(LLMError, match="llm_invalid_response"):
        await OpenAICompatibleModel(settings, transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))).complete([], [])


@pytest.mark.parametrize("field", ["llm_base_url", "llm_api_key", "llm_model"])
async def test_missing_configuration(settings, field):
    with pytest.raises(LLMError, match="llm_not_configured"):
        await OpenAICompatibleModel(settings.model_copy(update={field: None})).complete([], [])
