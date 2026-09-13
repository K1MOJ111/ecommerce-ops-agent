"""Small Chat Completions adapter; no business rules or database access."""

import asyncio
import json
from typing import Literal, NotRequired, Protocol, TypedDict

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.config import Settings


class FunctionCall(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    name: str = Field(min_length=1, max_length=200)
    arguments: str = Field(max_length=20000)

    def parsed_arguments(self) -> object:
        try:
            return json.loads(self.arguments)
        except (ValueError, RecursionError):
            return None  # Registry will produce invalid_argument, with no input echo.


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    id: str = Field(min_length=1, max_length=200)
    type: Literal["function"] = "function"
    function: FunctionCall


class Message(TypedDict):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None
    tool_calls: NotRequired[list[dict]]
    tool_call_id: NotRequired[str]


class ModelReply(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    content: str | None = Field(default=None, max_length=20000)
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def unique_calls(self) -> "ModelReply":
        ids = [call.id for call in self.tool_calls]
        if len(ids) != len(set(ids)) or (not ids and not self.content):
            raise ValueError("invalid_model_reply")
        return self

    def message(self) -> Message:
        message: Message = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            message["tool_calls"] = [call.model_dump() for call in self.tool_calls]
        return message


class LLMError(Exception):
    """Only safe codes cross the model boundary; never provider response bodies."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Model(Protocol):
    async def complete(self, messages: list[Message], tools: list[dict]) -> ModelReply: ...


class OpenAICompatibleModel:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport

    async def complete(self, messages: list[Message], tools: list[dict]) -> ModelReply:
        settings = self.settings
        if not (settings.llm_base_url and settings.llm_model and settings.llm_api_key
                and settings.llm_api_key.get_secret_value().strip()):
            raise LLMError("llm_not_configured")
        try:
            url = httpx.URL(settings.llm_base_url)
            if url.scheme not in {"https", "http"} or not url.host or url.userinfo or url.query or url.fragment:
                raise ValueError("invalid_url")
        except (ValueError, httpx.InvalidURL):
            raise LLMError("llm_configuration_error") from None
        body = {"model": settings.llm_model, "messages": messages}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        try:
            # No implicit retries or redirects; the graph owns the total request budget.
            async with asyncio.timeout(settings.llm_timeout_seconds):
                async with httpx.AsyncClient(transport=self.transport, timeout=settings.llm_timeout_seconds) as client:
                    response = await client.post(
                        str(url).rstrip("/") + "/chat/completions", json=body,
                        headers={"Authorization": "Bearer " + settings.llm_api_key.get_secret_value()},
                    )
                    response.raise_for_status()
        except (TimeoutError, httpx.TimeoutException):
            raise LLMError("llm_timeout") from None
        except httpx.HTTPStatusError as exc:
            code = "llm_unavailable" if exc.response.status_code == 429 or exc.response.status_code >= 500 else "llm_api_error"
            raise LLMError(code) from None
        except httpx.RequestError:
            raise LLMError("llm_unavailable") from None
        try:
            choice = response.json()["choices"][0]
            if choice["finish_reason"] not in {"stop", "tool_calls"}:
                raise ValueError("incomplete_reply")
            message = choice["message"]
            if message.get("role") != "assistant":
                raise ValueError("invalid_role")
            return ModelReply(content=message.get("content"), tool_calls=message.get("tool_calls") or [])
        except (KeyError, IndexError, TypeError, AttributeError, ValueError, ValidationError, RecursionError):
            raise LLMError("llm_invalid_response") from None
