from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import RequestContext
from app.db.base import Base
from app.db.models import Inventory, KnowledgeDocument, Logistics, LogisticsItem, Order, OrderItem, ProductSKU, Refund, User
from app.db.models.commerce import LogisticsStatus, OrderStatus, UserRole
from app.services import catalog, inventory, orders
from app.schemas.commerce import LogisticsResult, OrderData
from scripts.seed_data import SEED_TIME, SeedResult, seed_data, seed_id

pytestmark = pytest.mark.integration
EXPECTED_COUNTS = {
    "users": 3, "products": 3, "product_skus": 12, "inventory": 12, "orders": 6,
    "order_items": 11, "logistics": 5, "logistics_items": 9, "refunds": 1,
    "knowledge_documents": 2, "knowledge_chunks": 0, "audit_logs": 0, "agent_workflows": 0,
}


def customer_context(key: str = "customer-a") -> RequestContext:
    return RequestContext(seed_id(key), frozenset({"orders:read:self"}), uuid4())


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> SeedResult:
    return await seed_data(db_session, app_env="test")


async def test_seed_repeat_and_scenarios(db_session: AsyncSession, seeded: SeedResult) -> None:
    assert seeded == SeedResult(inserted=64, existing=0)
    assert await seed_data(db_session, app_env="test") == SeedResult(inserted=0, existing=64)
    counts = {table.name: await db_session.scalar(select(func.count()).select_from(table)) for table in Base.metadata.sorted_tables}
    assert counts == EXPECTED_COUNTS
    assert set((await db_session.scalars(select(User.role))).all()) == {UserRole.CUSTOMER, UserRole.OPERATOR}
    assert set((await db_session.scalars(select(Order.status))).all()) == {
        OrderStatus.PENDING_PAYMENT, OrderStatus.PENDING_FULFILLMENT, OrderStatus.PARTIALLY_SHIPPED,
        OrderStatus.SHIPPED, OrderStatus.COMPLETED, OrderStatus.CANCELLED,
    }
    assert len(set((await db_session.scalars(select(Order.user_id))).all())) == 2
    assert set((await db_session.scalars(select(KnowledgeDocument.status))).all()) == {"draft"}

    packages = {row.id: row for row in (await db_session.scalars(select(Logistics))).all()}
    line_items = {row.id: row for row in (await db_session.scalars(select(OrderItem))).all()}
    shipped: dict[UUID, int] = {}
    for allocation in (await db_session.scalars(select(LogisticsItem))).all():
        package = packages[allocation.logistics_id]
        assert package.order_id == line_items[allocation.order_item_id].order_id
        if package.status != LogisticsStatus.PENDING:
            shipped[allocation.order_item_id] = shipped.get(allocation.order_item_id, 0) + allocation.quantity
        if package.shipped_at:
            assert package.created_at <= package.shipped_at <= package.latest_event_at <= package.synced_at
    remaining: dict[UUID, int] = {}
    for order in (await db_session.scalars(select(Order))).all():
        items = [item for item in line_items.values() if item.order_id == order.id]
        assert sum((item.unit_price * item.quantity for item in items), Decimal("0")) == order.subtotal_amount
        assert sum((item.discount_amount for item in items), Decimal("0")) == order.discount_amount
        for item in items:
            assert 0 <= shipped.get(item.id, 0) <= item.quantity
            if order.status in {OrderStatus.SHIPPED, OrderStatus.COMPLETED}:
                assert shipped[item.id] == item.quantity
            if order.status in {OrderStatus.PENDING_FULFILLMENT, OrderStatus.PARTIALLY_SHIPPED}:
                remaining[item.sku_id] = remaining.get(item.sku_id, 0) + item.quantity - shipped.get(item.id, 0)
    for stock in (await db_session.scalars(select(Inventory))).all():
        assert stock.reserved == remaining.get(stock.sku_id, 0)
    refund = (await db_session.scalars(select(Refund))).one()
    assert refund.quantity <= line_items[refund.order_item_id].quantity
    assert refund.amount <= line_items[refund.order_item_id].line_amount
    assert refund.requested_at <= refund.processed_at <= refund.refunded_at


async def test_seed_preserves_changes_and_unrelated_rows(db_session: AsyncSession, seeded: SeedResult) -> None:
    sku = await db_session.get(ProductSKU, seed_id("sku-1"))
    assert sku is not None
    sku.price = Decimal("88.00")
    unrelated = User(display_name="unrelated", external_subject="not-seed")
    db_session.add(unrelated)
    await db_session.flush()
    assert await seed_data(db_session, app_env="test") == SeedResult(0, 64)
    await db_session.refresh(sku)
    assert sku.price == Decimal("88.00")
    assert await db_session.get(User, unrelated.id) is unrelated
    order = await orders.get_order(db_session, customer_context(), order_no="SEED-O001")
    assert order.items[0].unit_price == Decimal("59.00")


async def test_seed_rejects_production(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="seed_requires_development_or_test"):
        await seed_data(db_session, app_env="production")
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


async def test_catalog_queries(db_session: AsyncSession, seeded: SeedResult) -> None:
    results = await catalog.search_products(db_session, "短袖", category_code="clothing")
    assert [result.product_code for result in results] == ["SEED-P001"]
    detail = await catalog.get_product(db_session, results[0].id)
    assert detail is not None and detail.name == "纯棉短袖"
    assert await catalog.get_product(db_session, uuid4()) is None
    assert await catalog.get_product(db_session, seed_id("product-3")) is None
    assert await catalog.search_products(db_session, "旧款") == []
    assert await catalog.search_products(db_session, "%") == []
    assert await catalog.search_products(db_session, "' OR 1=1 --") == []
    skus = await catalog.list_product_skus(db_session, detail.id, specs={"color": "白色", "size": "L"})
    assert [sku.sku_code for sku in skus] == ["SEED-SKU002"]
    assert skus[0].price == Decimal("59.00")
    assert len(await catalog.list_product_skus(db_session, detail.id)) == 3
    assert await catalog.list_product_skus(db_session, detail.id, specs={"size": "XXL"}) == []
    assert await catalog.list_product_skus(db_session, seed_id("product-3")) == []
    assert await catalog.list_product_skus(db_session, uuid4()) == []


@pytest.mark.parametrize("limit", [0, -1, 101, True])
async def test_catalog_rejects_bad_limits(db_session: AsyncSession, limit: int) -> None:
    with pytest.raises(ValueError):
        await catalog.search_products(db_session, "短袖", limit=limit)
    with pytest.raises(ValueError):
        await catalog.list_product_skus(db_session, uuid4(), limit=limit)


@pytest.mark.parametrize("query", ["", "   ", "x" * 201])
async def test_catalog_rejects_bad_query(db_session: AsyncSession, query: str) -> None:
    with pytest.raises(ValueError):
        await catalog.search_products(db_session, query)


@pytest.mark.parametrize(("number", "on_hand", "reserved", "available"), [(1, 20, 3, 17), (2, 2, 0, 2), (3, 5, 5, 0), (7, 0, 0, 0)])
async def test_inventory_states(db_session: AsyncSession, seeded: SeedResult, number: int, on_hand: int, reserved: int, available: int) -> None:
    result = await inventory.get_inventory(db_session, seed_id(f"sku-{number}"), warehouse_code="SEED-WH01")
    assert result is not None
    assert len(result.stocks) == 1
    stock = result.stocks[0]
    assert (stock.on_hand, stock.reserved, stock.available) == (on_hand, reserved, available)
    assert result.queried_at.tzinfo is not None and stock.updated_at.tzinfo is not None


async def test_inventory_missing_and_inactive(db_session: AsyncSession, seeded: SeedResult) -> None:
    for sku_id in (uuid4(), seed_id("sku-4"), seed_id("sku-9")):
        assert await inventory.get_inventory(db_session, sku_id) is None
    result = await inventory.get_inventory(db_session, seed_id("sku-1"), warehouse_code="missing")
    assert result is not None and result.stocks == []


async def test_own_order_and_redaction(db_session: AsyncSession, seeded: SeedResult) -> None:
    context = customer_context()
    result = await orders.get_order(db_session, context, order_no="SEED-O001")
    assert result.id == seed_id("order-1") and result.items[0].quantity == 1
    assert result.payable_amount == Decimal("59.00")
    assert "shipping_address_snapshot" not in result.model_dump()
    assert "user_id" not in result.model_dump()
    assert await orders.get_order(db_session, context, order_id=result.id) == result


@pytest.mark.parametrize("service", [orders.get_order, orders.get_logistics])
@pytest.mark.parametrize("order_no", ["SEED-O002", "DOES-NOT-EXIST"])
async def test_other_and_missing_orders_rejected(db_session: AsyncSession, seeded: SeedResult, service: Callable[..., Awaitable[OrderData | LogisticsResult]], order_no: str) -> None:
    with pytest.raises(orders.OrderNotAccessible, match="^order_not_accessible$"):
        await service(db_session, customer_context(), order_no=order_no)


@pytest.mark.parametrize("service", [orders.get_order, orders.get_logistics])
async def test_operator_requires_explicit_permission(db_session: AsyncSession, seeded: SeedResult, service: Callable[..., Awaitable[OrderData | LogisticsResult]]) -> None:
    for permissions in (frozenset(), frozenset({"orders:read:self"})):
        with pytest.raises(orders.OrderNotAccessible):
            await service(db_session, RequestContext(seed_id("operator"), permissions, uuid4()), order_no="SEED-O002")
    context = RequestContext(seed_id("operator"), frozenset({"orders:read:any"}), uuid4())
    result = await service(db_session, context, order_no="SEED-O002")
    assert result is not None
    with pytest.raises(orders.OrderNotAccessible):
        await service(db_session, context, order_no="missing")


async def test_no_permission_even_for_own_order(db_session: AsyncSession, seeded: SeedResult) -> None:
    with pytest.raises(orders.OrderNotAccessible):
        await orders.get_order(db_session, RequestContext(seed_id("customer-a"), frozenset(), uuid4()), order_no="SEED-O001")
    with pytest.raises(ValueError):
        await orders.get_order(db_session, customer_context())
    with pytest.raises(ValueError):
        await orders.get_order(db_session, customer_context(), order_no="SEED-O001", order_id=seed_id("order-1"))


async def test_logistics_packages_and_times(db_session: AsyncSession, seeded: SeedResult) -> None:
    pending = await orders.get_logistics(db_session, customer_context("customer-b"), order_no="SEED-O002")
    assert len(pending.packages) == 1 and pending.packages[0].tracking_no is None
    assert pending.packages[0].status == LogisticsStatus.PENDING
    partial = await orders.get_logistics(db_session, customer_context(), order_no="SEED-O003")
    assert len(partial.packages) == 1 and len(partial.packages[0].items) == 2
    split = await orders.get_logistics(db_session, customer_context("customer-b"), order_no="SEED-O004")
    assert len(split.packages) == 2
    assert sum(len(package.items) for package in split.packages) == 2
    delivered = await orders.get_logistics(db_session, customer_context(), order_id=seed_id("order-5"))
    package = delivered.packages[0]
    assert package.status == LogisticsStatus.DELIVERED
    assert package.delivered_at == SEED_TIME + timedelta(days=4)
    assert package.synced_at == SEED_TIME + timedelta(days=4, hours=1)
    assert package.shipped_at == SEED_TIME + timedelta(days=1)
    assert (await orders.get_logistics(db_session, customer_context(), order_no="SEED-O001")).packages == []


async def test_logistics_does_not_leak_cross_order_items(db_session: AsyncSession, seeded: SeedResult) -> None:
    db_session.add(LogisticsItem(logistics_id=seed_id("package-delivered"), order_item_id=seed_id("order-2-line-1"), quantity=1))
    await db_session.flush()
    result = await orders.get_logistics(db_session, customer_context(), order_no="SEED-O005")
    assert {item.order_item_id for item in result.packages[0].items} == {seed_id("order-5-line-1"), seed_id("order-5-line-2")}
