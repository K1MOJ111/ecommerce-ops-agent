import json
from datetime import timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.security import RequestContext
from app.tools.registry import invoke_tool
from scripts.seed_data import SEED_TIME, seed_data, seed_id

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seeded_session(db_session: AsyncSession) -> AsyncSession:
    await seed_data(db_session, app_env="test")
    return db_session


def context(actor: str = "customer-a", permission: str | None = "orders:read:self") -> RequestContext:
    return RequestContext(seed_id(actor), frozenset({permission}) if permission else frozenset(), uuid4())


async def test_catalog_tools(seeded_session: AsyncSession) -> None:
    async def call(name: str, arguments: dict):
        return await invoke_tool(name, arguments, session=seeded_session, context=context())

    search = await call("search_products", {"query": " 短袖 ", "category": "clothing", "limit": 1})
    assert search.status == "success" and [row.product_code for row in search.data] == ["SEED-P001"]
    product_id = str(search.data[0].id)
    detail = await call("get_product", {"product_id": product_id})
    assert detail.status == "success" and detail.data.name == "纯棉短袖" and detail.data.description
    skus = await call("list_product_skus", {"product_id": product_id, "specs": {"color": "白色", "size": "L"}})
    assert skus.status == "success" and [sku.sku_code for sku in skus.data] == ["SEED-SKU002"]
    assert json.loads(skus.model_dump_json())["data"][0]["price"] == "59.00"
    for query in ("not-present", "%", "' OR 1=1 --", "旧款"):
        assert (await call("search_products", {"query": query})).status == "not_found"
    assert (await call("search_products", {"query": "短袖", "category": "missing"})).status == "not_found"
    for product in (str(uuid4()), str(seed_id("product-3"))):
        assert (await call("get_product", {"product_id": product})).status == "not_found"
        assert (await call("list_product_skus", {"product_id": product})).status == "not_found"
    assert (await call("list_product_skus", {"product_id": product_id, "specs": {"size": "XXL"}})).status == "not_found"
    assert (await call("search_products", {"query": "短袖", "limit": 0})).status == "invalid_argument"


@pytest.mark.parametrize(("sku", "available"), [(1, 17), (3, 0), (7, 0)])
async def test_inventory_tools(seeded_session: AsyncSession, sku: int, available: int) -> None:
    result = await invoke_tool("get_inventory", {"sku_id": str(seed_id(f"sku-{sku}"))}, session=seeded_session, context=context())
    assert result.status == "success" and result.data.stocks[0].available == available
    assert result.queried_at == result.data.queried_at and result.queried_at.tzinfo is not None


async def test_missing_inventory(seeded_session: AsyncSession) -> None:
    for sku in (uuid4(), seed_id("sku-4"), seed_id("sku-9")):
        result = await invoke_tool("get_inventory", {"sku_id": str(sku)}, session=seeded_session, context=context())
        assert result.status == "not_found" and result.data is None
    result = await invoke_tool("get_inventory", {"sku_id": str(seed_id("sku-1")), "warehouse_code": "missing"}, session=seeded_session, context=context())
    assert result.status == "success" and result.data.stocks == []


@pytest.mark.parametrize("name", ["get_order", "get_logistics"])
@pytest.mark.parametrize(("actor", "permission", "order_no", "status"), [
    ("customer-a", "orders:read:self", "SEED-O001", "success"),
    ("customer-a", "orders:read:self", "SEED-O002", "forbidden"),
    ("customer-a", "orders:read:self", "missing", "forbidden"),
    ("customer-a", None, "SEED-O001", "forbidden"),
    ("operator", "orders:read:any", "SEED-O002", "success"),
    ("operator", "orders:read:any", "missing", "not_found"),
    ("operator", None, "SEED-O002", "forbidden"),
    ("operator", "orders:read:self", "SEED-O002", "forbidden"),
    ("operator", "products:read:any", "SEED-O002", "forbidden"),
])
async def test_order_permission_matrix(seeded_session: AsyncSession, name: str, actor: str, permission: str | None, order_no: str, status: str) -> None:
    trusted = context(actor, permission)
    result = await invoke_tool(name, {"order_no": order_no}, session=seeded_session, context=trusted)
    assert result.status == status and result.source == name and result.request_id == trusted.request_id
    serialized = result.model_dump_json()
    assert "shipping_address_snapshot" not in serialized and "user_id" not in serialized and "actor_id" not in serialized
    if status == "success" and name == "get_order":
        assert result.data.order_no == order_no and result.data.items
    if status != "success":
        assert result.data is None and result.error is not None


@pytest.mark.parametrize("name", ["get_order", "get_logistics"])
async def test_order_existence_not_leaked(seeded_session: AsyncSession, name: str) -> None:
    results = [await invoke_tool(name, {"order_no": order}, session=seeded_session, context=context()) for order in ("SEED-O002", "missing")]
    assert results[0].status == results[1].status == "forbidden"
    assert results[0].error == results[1].error


@pytest.mark.parametrize("name", ["get_order", "get_logistics"])
@pytest.mark.parametrize("forgery", [
    {"actor_id": str(seed_id("customer-b"))}, {"permissions": ["orders:read:any"]},
    {"role": "operator"}, {"context": {"actor_id": str(seed_id("customer-b")), "permissions": ["orders:read:any"]}},
    {"request_id": str(uuid4())},
])
async def test_cannot_forge_context(seeded_session: AsyncSession, name: str, forgery: dict) -> None:
    trusted = context()
    result = await invoke_tool(name, {"order_no": "SEED-O002", **forgery}, session=seeded_session, context=trusted)
    assert result.status == "invalid_argument" and result.data is None
    assert result.request_id == trusted.request_id and trusted.actor_id == seed_id("customer-a")
    assert (await invoke_tool(name, {"order_no": "SEED-O002"}, session=seeded_session, context=trusted)).status == "forbidden"


@pytest.mark.parametrize(("number", "actor", "count"), [(1, "customer-a", 0), (2, "customer-b", 1), (4, "customer-b", 2), (5, "customer-a", 1)])
async def test_logistics_shapes(seeded_session: AsyncSession, number: int, actor: str, count: int) -> None:
    result = await invoke_tool("get_logistics", {"order_no": f"SEED-O{number:03}"}, session=seeded_session, context=context(actor))
    assert result.status == "success" and len(result.data.packages) == count
    assert result.queried_at == result.data.queried_at
    if number == 4:
        assert sum(len(package.items) for package in result.data.packages) == 2
    if number == 5:
        assert result.data.packages[0].synced_at == SEED_TIME + timedelta(days=4, hours=1)
        assert "synced_at" in json.loads(result.model_dump_json())["data"]["packages"][0]


async def test_tools_execute_only_selects(seeded_session: AsyncSession, db_engine: AsyncEngine) -> None:
    statements = []

    def record(connection, cursor, statement, parameters, execution_context, executemany):
        statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", record)
    try:
        for name, arguments in (
            ("search_products", {"query": "短袖"}), ("get_product", {"product_id": str(seed_id("product-1"))}),
            ("list_product_skus", {"product_id": str(seed_id("product-1"))}), ("get_inventory", {"sku_id": str(seed_id("sku-1"))}),
            ("get_order", {"order_no": "SEED-O005"}), ("get_logistics", {"order_no": "SEED-O005"}),
        ):
            result = await invoke_tool(name, arguments, session=seeded_session, context=context())
            assert result.status == "success"
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", record)
    assert statements and all(statement.lstrip().upper().startswith("SELECT ") for statement in statements)
    assert not seeded_session.new and not seeded_session.dirty and not seeded_session.deleted


async def test_postgres_lock_timeout_is_temporary(db_session: AsyncSession, db_engine: AsyncEngine) -> None:
    # Use the isolated test database and a rolled-back lock; do not stop the shared DB server.
    async with db_engine.connect() as blocker:
        async with blocker.begin():
            await blocker.execute(text("LOCK TABLE products IN ACCESS EXCLUSIVE MODE"))
            await db_session.execute(text("SET LOCAL lock_timeout = '50ms'"))
            result = await invoke_tool("search_products", {"query": "短袖"}, session=db_session, context=context())
            assert result.status == "temporarily_unavailable" and result.data is None
            assert result.error.code == "temporarily_unavailable"
            assert "products" not in result.error.message and "SELECT" not in result.model_dump_json()
