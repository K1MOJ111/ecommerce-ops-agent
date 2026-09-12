from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.db.base import Base
from app.db.models import Inventory, KnowledgeChunk, KnowledgeDocument, Order, OrderItem, Product, ProductSKU, User
from app.db.models.knowledge import ScopeType
from app.db.session import check_database, create_session_factory
from app.main import create_app

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def commerce_rows(db_session: AsyncSession) -> tuple[User, ProductSKU, Order, OrderItem]:
    user = User(display_name="test user")
    product = Product(product_code="test-product", name="original name", description="test", brand="test", category_code="test")
    db_session.add_all([user, product])
    await db_session.flush()
    sku = ProductSKU(product_id=product.id, sku_code="test-sku", specs={"size": "M"}, spec_key="size=M", price=Decimal("10.00"))
    order = Order(user=user, order_no="test-order", subtotal_amount=Decimal("20.00"), payable_amount=Decimal("20.00"), shipping_address_snapshot={"city": "test city"})
    db_session.add_all([sku, order])
    await db_session.flush()
    item = OrderItem(order=order, line_no=1, sku_id=sku.id, product_name_snapshot=product.name, sku_code_snapshot=sku.sku_code, specs_snapshot=sku.specs.copy(), quantity=2, unit_price=sku.price, line_amount=Decimal("20.00"))
    db_session.add_all([item, Inventory(sku_id=sku.id, warehouse_code="test", on_hand=5, reserved=2)])
    await db_session.flush()
    return user, sku, order, item


async def test_connection_schema_and_revision(db_engine: AsyncEngine, db_session: AsyncSession) -> None:
    await check_database(db_session)
    assert await db_session.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
    async with db_engine.connect() as connection:
        tables = await connection.run_sync(lambda conn: inspect(conn).get_table_names())
    assert set(tables) == set(Base.metadata.tables) | {"alembic_version"}
    extensions = set((await db_session.scalars(text("SELECT extname FROM pg_extension"))).all())
    assert {"vector", "pg_trgm"} <= extensions
    assert await db_session.scalar(text("SHOW timezone")) == "UTC"


async def test_real_health(migrated_database: str) -> None:
    app = create_app(Settings(_env_file=None, database_url=SecretStr(migrated_database)))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"api": "ok", "database": "ok"}


async def test_independent_sessions(db_engine: AsyncEngine) -> None:
    factory = create_session_factory(db_engine)
    async with factory() as first, factory() as second:
        assert first is not second
        await check_database(first)
        await check_database(second)


async def test_user_order_decimal_and_snapshots(
    db_session: AsyncSession, commerce_rows: tuple[User, ProductSKU, Order, OrderItem],
) -> None:
    user, sku, order, item = commerce_rows
    sku.price = Decimal("99.00")
    sku.specs = {"size": "L"}
    await db_session.flush()
    db_session.expire_all()
    loaded = (await db_session.scalars(select(Order).options(selectinload(Order.user), selectinload(Order.items)))).one()
    assert loaded.user.display_name == "test user"
    assert loaded.items[0].unit_price == Decimal("10.00")
    assert isinstance(loaded.payable_amount, Decimal)
    assert loaded.items[0].specs_snapshot == {"size": "M"}
    assert loaded.shipping_address_snapshot == {"city": "test city"}
    assert loaded.created_at.utcoffset().total_seconds() == 0


async def test_sku_code_unique(
    db_session: AsyncSession, commerce_rows: tuple[User, ProductSKU, Order, OrderItem],
) -> None:
    sku = commerce_rows[1]
    duplicate = ProductSKU(product_id=sku.product_id, sku_code=sku.sku_code, specs={}, spec_key="different", price=Decimal("1"))
    with pytest.raises(IntegrityError, match="uq_product_skus_sku_code"):
        async with db_session.begin_nested():
            db_session.add(duplicate)
            await db_session.flush()


@pytest.mark.parametrize(("statement", "constraint"), [
    ("UPDATE inventory SET reserved=on_hand+1", "ck_inventory_stock_range"),
    ("UPDATE inventory SET reserved=-1", "ck_inventory_stock_range"),
    ("UPDATE inventory SET on_hand=-1", "ck_inventory_stock_range"),
    ("UPDATE order_items SET quantity=0, line_amount=0", "ck_order_items_quantity_line_positive"),
    ("UPDATE product_skus SET price=-1", "ck_product_skus_price_range"),
    ("UPDATE product_skus SET price='NaN'::numeric", "ck_product_skus_price_range"),
    ("UPDATE orders SET paid_amount=-1", "ck_orders_amount_range"),
    ("UPDATE orders SET paid_amount=21", "ck_orders_amount_range"),
    ("UPDATE orders SET shipping_fee=-1", "ck_orders_amount_range"),
    ("UPDATE orders SET payable_amount=19", "ck_orders_payable_total"),
    ("UPDATE order_items SET discount_amount=21", "ck_order_items_amount_range"),
    ("UPDATE order_items SET line_amount=19", "ck_order_items_line_total"),
    ("UPDATE orders SET status='unknown'", "ck_orders_orderstatus"),
    ("UPDATE orders SET currency='USD'", "ck_orders_currency"),
    ("UPDATE orders SET user_id='00000000-0000-0000-0000-000000000000'", "fk_orders_user_id_users"),
    ("DELETE FROM users", "fk_orders_user_id_users"),
    ("DELETE FROM orders", "fk_order_items_order_id_orders"),
])
async def test_real_constraints(
    db_session: AsyncSession, commerce_rows: tuple[User, ProductSKU, Order, OrderItem],
    statement: str, constraint: str,
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


@pytest_asyncio.fixture
async def document(db_session: AsyncSession) -> KnowledgeDocument:
    value = KnowledgeDocument(document_key="test-policy", version=1, title="test", source_uri="test://policy", content="test policy", content_hash="test-hash", scope_type=ScopeType.GLOBAL, valid_from=datetime.now(UTC))
    db_session.add(value)
    await db_session.flush()
    return value


@pytest.mark.parametrize(("statement", "constraint"), [
    ("UPDATE knowledge_documents SET scope_type='category'", "ck_knowledge_documents_scope_fields"),
    ("UPDATE knowledge_documents SET scope_type='product'", "ck_knowledge_documents_scope_fields"),
    ("UPDATE knowledge_documents SET category_code='bad'", "ck_knowledge_documents_scope_fields"),
    ("UPDATE knowledge_documents SET valid_to=valid_from", "ck_knowledge_documents_valid_period"),
    ("UPDATE knowledge_documents SET version=0", "ck_knowledge_documents_version_positive"),
])
async def test_knowledge_constraints(
    db_session: AsyncSession, document: KnowledgeDocument, statement: str, constraint: str,
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


async def test_unbounded_vector_and_dimension_boundary(db_session: AsyncSession, document: KnowledgeDocument) -> None:
    chunks = [
        KnowledgeChunk(document_id=document.id, chunk_index=0, content="a", locator="p1", embedding=[1.0, 2.0], embedding_model="test-2d"),
        KnowledgeChunk(document_id=document.id, chunk_index=1, content="b", locator="p2", embedding=[1.0, 2.0, 3.0], embedding_model="test-3d"),
    ]
    db_session.add_all(chunks)
    await db_session.flush()
    dims = (await db_session.scalars(text("SELECT vector_dims(embedding) FROM knowledge_chunks ORDER BY chunk_index"))).all()
    assert dims == [2, 3]
    assert await db_session.scalar(text("SELECT embedding <-> '[1,2]'::vector FROM knowledge_chunks WHERE embedding_model='test-2d'")) == 0
    await db_session.refresh(chunks[0])
    assert chunks[0].embedding == [1.0, 2.0]
    with pytest.raises(DBAPIError, match="different vector dimensions"):
        async with db_session.begin_nested():
            await db_session.execute(text("SELECT '[1,2]'::vector <-> '[1,2,3]'::vector"))
    with pytest.raises(IntegrityError, match="ck_knowledge_chunks_embedding_pair"):
        async with db_session.begin_nested():
            await db_session.execute(text("UPDATE knowledge_chunks SET embedding_model=NULL"))
