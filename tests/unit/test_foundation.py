from dataclasses import FrozenInstanceError
from typing import Annotated
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.exc import OperationalError

from app.api.dependencies import get_request_context
from app.core.config import Settings
from app.core.security import RequestContext
from app.main import create_app

TEST_URL = "postgresql+asyncpg://test:example@127.0.0.1:1/unit_test"


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LLM_API_KEY", "unit-secret")
    monkeypatch.setenv("EMBEDDING_DIM", "")
    settings = Settings(_env_file=None)
    assert settings.app_env == "test"
    assert settings.database_url.get_secret_value() == TEST_URL
    assert settings.embedding_dim is None
    assert "unit-secret" not in repr(settings)
    assert TEST_URL not in repr(settings)


@pytest.mark.parametrize("value", ["sqlite:///test.db", "postgresql://localhost/test", "bad-url"])
def test_settings_reject_non_async_postgres(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=SecretStr(value))


@pytest.mark.parametrize("field", ["rag_top_k", "agent_max_tool_calls", "llm_timeout_seconds", "embedding_dim"])
def test_settings_reject_invalid_limits(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=SecretStr(TEST_URL), **{field: 0})


@pytest.mark.parametrize("db_error", [None, OperationalError("SELECT 1", {}, Exception("private error")), TimeoutError()])
async def test_health_states(monkeypatch: pytest.MonkeyPatch, db_error: Exception | None) -> None:
    probe = AsyncMock(side_effect=db_error)
    monkeypatch.setattr("app.api.routes.health.check_database", probe)
    app = create_app(Settings(_env_file=None, database_url=SecretStr(TEST_URL)))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            assert (await client.get("/health/live")).json() == {"api": "ok"}
            probe.assert_not_called()
            response = await client.get("/health")
            assert response.status_code == (200 if db_error is None else 503)
            assert response.json() == {"api": "ok", "database": "ok" if db_error is None else "unavailable"}
            probe.assert_awaited_once()


async def test_context_requires_server_injection() -> None:
    app = create_app(Settings(_env_file=None, database_url=SecretStr(TEST_URL)))

    @app.get("/test-context")
    async def context_route(context: Annotated[RequestContext, Depends(get_request_context)]) -> dict[str, str]:
        return {"actor_id": str(context.actor_id)}

    context = RequestContext(uuid4(), frozenset({"orders:read:self"}), uuid4())
    with pytest.raises(FrozenInstanceError):
        context.actor_id = uuid4()  # type: ignore[misc]
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        assert (await client.get("/test-context", headers={"actor_id": str(uuid4()), "permissions": "*"})).status_code == 401

        async def trusted_override() -> RequestContext:
            return context

        app.dependency_overrides[get_request_context] = trusted_override
        assert (await client.get("/test-context")).json() == {"actor_id": str(context.actor_id)}
