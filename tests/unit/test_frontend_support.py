import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.agent.development import DevelopmentModel
from app.api.dependencies import get_db_session
from app.core.config import Settings
from app.main import create_app
from app.tools.registry import tool_schemas

URL = "postgresql+asyncpg://test:example@127.0.0.1:1/frontend_test"


def settings(**kwargs):
    return Settings(_env_file=None, database_url=URL, **kwargs)


@pytest.mark.parametrize("field", ["agent_provider", "embedding_provider"])
def test_production_forbids_fake(field):
    with pytest.raises(ValidationError, match="fake_provider_forbidden"):
        settings(app_env="production", **{field: "fake"})


@pytest.mark.parametrize("origin", ["*", "https://*.example.com", "https://user:password@example.com", "https://example.com/path", "http://localhost:5173"])
def test_production_requires_explicit_https_origin(origin):
    with pytest.raises(ValidationError):
        settings(app_env="production", cors_origins=[origin])


@pytest.mark.parametrize("environment,origin,allowed", [
    ("development", "http://localhost:5173", True),
    ("development", "https://untrusted.example", False),
    ("production", "http://localhost:5173", False),
])
async def test_cors_preflight(environment, origin, allowed):
    app = create_app(settings(app_env=environment))
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.options("/agent/requests", headers={"Origin": origin,
            "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type"})
        assert response.status_code == (200 if allowed else 400)
        assert response.headers.get("access-control-allow-origin") == (origin if allowed else None)


@pytest.mark.parametrize("actor,active,expected", [(False, True, 401), (True, False, 403), (True, True, 200)])
async def test_status_identity_and_safe_projection(actor, active, expected):
    user_id = uuid4()
    app = create_app(settings(dev_actor_id=user_id if actor else None, agent_provider="fake", embedding_provider="fake"))
    async def session():
        yield SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=user_id, display_name="模拟用户", status="active" if active else "disabled")))
    app.dependency_overrides[get_db_session] = session
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.get("/status", headers={"actor_id": str(user_id), "permissions": "*"})
            assert response.status_code == expected
            if expected == 200:
                assert response.json() == {"api": "ok", "database": "ok", "agent_provider": "fake",
                    "embedding_provider": "fake", "user": {"id": str(user_id), "display_name": "模拟用户"}}
                assert response.headers["cache-control"] == "no-store"
            assert "example@" not in response.text and "permissions" not in response.text


async def test_status_database_failure_is_safe():
    app = create_app(settings(dev_actor_id=uuid4()))
    async def session():
        yield SimpleNamespace(get=AsyncMock(side_effect=OSError("private_database_details")))
    app.dependency_overrides[get_db_session] = session
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.get("/status")
            assert response.status_code == 503
            assert response.json() == {"detail": "status_unavailable"}


async def complete(message, results=()):
    schemas = [{"type": "function", "function": s} for s in tool_schemas(include_write=True)]
    return await DevelopmentModel().complete([{"role": "user", "content": message}] + [
        {"role": "tool", "content": json.dumps(r)} for r in results], schemas)


async def test_development_provider_retains_intent_across_clarification():
    messages = [{"role": "user", "content": "帮我取消这个订单，原因 不需要了"},
                {"role": "assistant", "content": '{"action":"clarify","question":"order"}'},
                {"role": "user", "content": "订单号：SEED-O001"}]
    schemas = [{"type": "function", "function": s} for s in tool_schemas(include_write=True)]
    reply = await DevelopmentModel().complete(messages, schemas)
    assert reply.tool_calls[0].function.name == "request_order_cancellation"


@pytest.mark.parametrize("message,tool", [
    ("查询商品 纯棉短袖", "search_products"), ("查询订单 SEED-O003", "get_order"),
    ("查询物流 SEED-O003", "get_logistics"), ("查询七天无理由退货政策", "search_after_sales_policy"),
    ("取消我的订单 SEED-O001，原因 不需要了", "request_order_cancellation"),
])
async def test_development_provider_plans_only_tools(message, tool):
    reply = await complete(message)
    assert reply.tool_calls[0].function.name == tool
    assert reply.content is None


async def test_missing_write_parameters_clarify_and_refund_is_explicit():
    assert json.loads((await complete("取消我的订单 SEED-O001")).content)["question"] == "reason"
    item = uuid4()
    text = f"申请退款 订单 SEED-O003，明细 {item}，数量 1，金额 59.00，原因 尺码不合适"
    reply = await complete(text)
    assert reply.tool_calls[0].function.parsed_arguments() == {"order_no": "SEED-O003", "order_item_id": str(item),
        "quantity": 1, "amount": "59.00", "reason": "尺码不合适"}
    assert json.loads((await complete(text.replace("数量 1", "数量 1.5"))).content)["question"] == "quantity"


async def test_inventory_uses_actual_returned_ids_and_provider_has_no_shared_state():
    message = "查询库存 纯棉短袖 白色 M"
    product, sku = str(uuid4()), str(uuid4())
    results = [{"evidence_id": 1, "status": "success", "source": "search_products", "data": [{"id": product}]}]
    reply = await complete(message, results)
    assert reply.tool_calls[0].function.parsed_arguments() == {"product_id": product, "specs": {"color": "白色", "size": "M"}}
    results.append({"evidence_id": 2, "status": "success", "source": "list_product_skus", "data": [{"id": sku}]})
    assert (await complete(message, results)).tool_calls[0].function.parsed_arguments() == {"sku_id": sku}
    results.append({"evidence_id": 3, "status": "success", "source": "get_inventory", "data": {"stocks": []}})
    assert json.loads((await complete(message, results)).content)["evidence_ids"] == [1, 2, 3]
    assert (await complete("查询订单 SEED-O003")).tool_calls[0].function.name == "get_order"
    failed = [{"evidence_id": 1, "status": "forbidden", "source": "get_order", "data": None}]
    assert json.loads((await complete("查询订单 SEED-O003", failed)).content)["evidence_ids"] == []
