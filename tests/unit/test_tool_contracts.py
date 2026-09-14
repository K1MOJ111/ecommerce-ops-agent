import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError, TimeoutError as PoolTimeoutError

from app.core.security import RequestContext
from app.schemas.commerce import ProductDetail
from app.schemas.tools import ToolError, ToolResult
from app.services.orders import OrderNotAccessible
from app.tools.registry import TOOLS, get_tool, invoke_tool, tool_schemas


@pytest.fixture
def context() -> RequestContext:
    return RequestContext(uuid4(), frozenset({"orders:read:self"}), uuid4())


def test_registry_and_schemas() -> None:
    assert set(TOOLS) == {"search_products", "get_product", "list_product_skus", "get_inventory", "get_order", "get_logistics", "search_after_sales_policy"}
    assert get_tool("get_product").name == "get_product"
    with pytest.raises(KeyError):
        get_tool("cancel_order")
    with pytest.raises(TypeError):
        TOOLS["cancel_order"] = get_tool("get_order")
    with pytest.raises(FrozenInstanceError):
        get_tool("get_order").requires_context = False
    schemas = tool_schemas()
    assert len(schemas) == 7
    for schema in schemas:
        params = schema["parameters"]
        assert params["additionalProperties"] is False
        assert not {"actor_id", "permissions", "request_id", "role", "sql", "context"} & params["properties"].keys()
        assert set(schema["result"]["properties"]) == {"status", "data", "source", "queried_at", "request_id", "error"}
        alternatives = schema["result"]["properties"]["data"]["anyOf"]
        assert all("$ref" in item or item.get("type") in {"array", "null"} for item in alternatives)
    search = schemas[0]["parameters"]["properties"]
    assert "category" in search and "category_code" not in search
    assert search["limit"]["minimum"] == 1 and search["limit"]["maximum"] == 100
    json.dumps(schemas)
    schemas[0]["parameters"]["properties"].clear()
    assert get_tool("search_products").schema()["parameters"]["properties"]


@pytest.mark.parametrize("name", ["cancel_order", "refund", "ingest_knowledge", "app.services.orders.get_order", "__import__", "", None, []])
async def test_unregistered_tool(name: object, context: RequestContext) -> None:
    session = AsyncMock()
    result = await invoke_tool(name, {}, session=session, context=context)
    assert result.status == "invalid_argument" and result.error.code == "unknown_tool"
    assert result.source == "registry" and result.request_id == context.request_id
    assert session.mock_calls == []


@pytest.mark.parametrize(("name", "arguments"), [
    ("search_products", {}), ("search_products", {"query": " "}),
    ("search_products", {"query": "x" * 201}), ("search_products", {"query": 123}),
    *[("search_products", {"query": "shirt", "limit": limit}) for limit in (0, 101, True, "2", 1.5)],
    *[("search_products", {"query": "shirt", "category": value}) for value in (" ", "x" * 101, 1)],
    ("get_product", {"product_id": "invalid"}), ("get_product", {}),
    ("get_inventory", {"sku_id": "invalid"}),
    ("get_inventory", {"sku_id": str(uuid4()), "warehouse_code": " "}),
    ("get_inventory", {"sku_id": str(uuid4()), "warehouse_code": "x" * 101}),
    ("list_product_skus", {"product_id": "bad"}),
    *[("list_product_skus", {"product_id": str(uuid4()), "specs": specs}) for specs in (
        {"": "M"}, {"x" * 65: "M"}, {"size": "x" * 101}, {"size": " "}, {"size": 1},
        {"size": {"$ne": "M"}}, {str(i): "M" for i in range(9)}, [],
    )],
    ("list_product_skus", {"product_id": str(uuid4()), "limit": True}),
    *[(name, {"order_no": value}) for name in ("get_order", "get_logistics") for value in ("", " ", "x" * 101, 1, None)],
    ("get_order", {"order_id": str(uuid4())}),
    ("get_order", []), ("get_order", '{"order_no":"SEED-O001"}'),
])
async def test_invalid_arguments_never_reach_service(name: str, arguments: object, context: RequestContext) -> None:
    service = AsyncMock()
    result = await replace(get_tool(name), service=service).invoke(arguments, session=AsyncMock(), context=context)
    assert result.status == "invalid_argument" and result.data is None
    assert result.error.model_dump() == {
        "code": "invalid_argument", "message": "Invalid tool arguments; check the input schema.",
    }
    service.assert_not_awaited()


@pytest.mark.parametrize("name", list(TOOLS))
@pytest.mark.parametrize("field", ["actor_id", "permissions", "request_id", "role", "context", "sql"])
async def test_untrusted_extra_fields_rejected(name: str, field: str, context: RequestContext) -> None:
    arguments = {
        "search_products": {"query": "shirt"}, "get_product": {"product_id": str(uuid4())},
        "list_product_skus": {"product_id": str(uuid4())}, "get_inventory": {"sku_id": str(uuid4())},
        "get_order": {"order_no": "SEED-O001"}, "get_logistics": {"order_no": "SEED-O001"},
        "search_after_sales_policy": {"query": "退货"},
    }[name]
    service = AsyncMock()
    result = await replace(get_tool(name), service=service).invoke(
        {**arguments, field: "private-input"}, session=AsyncMock(), context=context,
    )
    assert result.status == "invalid_argument" and "private-input" not in result.model_dump_json()
    service.assert_not_awaited()


async def test_service_adapter_and_serialization(context: RequestContext) -> None:
    product = ProductDetail(id=uuid4(), product_code="P001", name="shirt", brand="brand", category_code="clothing", description="cotton")
    service = AsyncMock(return_value=[product])
    session = AsyncMock()
    result = await replace(get_tool("search_products"), service=service).invoke(
        {"query": " shirt ", "category": " clothing ", "limit": 1}, session=session, context=context,
    )
    service.assert_awaited_once_with(session, query="shirt", category_code="clothing", limit=1)
    assert result.status == "success" and result.queried_at.tzinfo is not None
    assert result.request_id == context.request_id
    payload = json.loads(result.model_dump_json())
    assert payload["data"][0]["id"] == str(product.id)


@pytest.mark.parametrize("name", ["get_order", "get_logistics"])
async def test_trusted_context_passed_unchanged(name: str, context: RequestContext) -> None:
    service = AsyncMock(side_effect=OrderNotAccessible())
    session = AsyncMock()
    result = await replace(get_tool(name), service=service).invoke({"order_no": " O001 "}, session=session, context=context)
    service.assert_awaited_once_with(session, context, order_no="O001")
    assert result.status == "forbidden"
    assert result.request_id == context.request_id
    with pytest.raises(TypeError, match="server_request_context_required"):
        await invoke_tool(name, {"order_no": "O001"}, session=session, context={"actor_id": str(context.actor_id)})


@pytest.mark.parametrize(("error", "expected"), [
    (ValueError("private-input"), "invalid_argument"),
    (OrderNotAccessible(), "forbidden"),
    (OperationalError("private-sql", {"password": "private-input"}, Exception("private-db")), "temporarily_unavailable"),
    (TimeoutError("private-timeout"), "temporarily_unavailable"),
    (ConnectionError("private-connection"), "temporarily_unavailable"),
    (PoolTimeoutError("private-pool"), "temporarily_unavailable"),
    (DBAPIError("private-sql", {}, Exception("private-db"), connection_invalidated=True), "temporarily_unavailable"),
])
async def test_safe_error_conversion(error: Exception, expected: str, context: RequestContext) -> None:
    tool = replace(get_tool("get_order"), service=AsyncMock(side_effect=error))
    result = await tool.invoke({"order_no": "O001"}, session=AsyncMock(), context=context)
    assert result.status == expected and result.error.code == expected and result.data is None
    assert "private" not in result.model_dump_json()


@pytest.mark.parametrize("error", [RuntimeError("bug"), ProgrammingError("bad SQL", {}, Exception("bug"))])
async def test_programming_errors_are_not_temporary(error: Exception, context: RequestContext) -> None:
    tool = replace(get_tool("get_product"), service=AsyncMock(side_effect=error))
    with pytest.raises(type(error)):
        await tool.invoke({"product_id": str(uuid4())}, session=AsyncMock(), context=context)


async def test_invalid_service_output_is_not_input_failure(context: RequestContext) -> None:
    tool = replace(get_tool("get_product"), service=AsyncMock(return_value={"unexpected": "value"}))
    with pytest.raises(ValidationError):
        await tool.invoke({"product_id": str(uuid4())}, session=AsyncMock(), context=context)


@pytest.mark.parametrize(("status", "data", "error"), [
    ("success", None, None), ("success", "value", ToolError(code="bad", message="bad")),
    ("not_found", None, None), ("forbidden", "value", ToolError(code="bad", message="bad")),
])
def test_result_invariants(status: str, data: object, error: object, context: RequestContext) -> None:
    with pytest.raises(ValidationError):
        ToolResult[str](status=status, data=data, error=error, source="test", queried_at=datetime.now(UTC), request_id=context.request_id)
