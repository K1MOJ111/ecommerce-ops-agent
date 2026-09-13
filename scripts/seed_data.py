"""Explicit local command: python -m scripts.seed_data. Never called at API startup."""

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.base import Base, TimestampMixin
from app.db.models import Inventory, KnowledgeDocument, Logistics, LogisticsItem, Order, OrderItem, Product, ProductSKU, Refund, User
from app.db.models.commerce import LogisticsStatus, OrderStatus, PaymentStatus, ProductStatus, RefundStatus, SKUStatus, UserRole
from app.db.models.knowledge import DocumentStatus, ScopeType
from app.db.session import create_db_engine, create_session_factory

SEED_TIME = datetime(2026, 9, 1, 8, tzinfo=UTC)


def seed_id(key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"ecommerce-ops-agent/seed/v1/{key}")


@dataclass(frozen=True)
class SeedResult:
    inserted: int
    existing: int


def seed_rows() -> list[Base]:
    rows: list[Base] = []

    def add(row: Base, key: str, updated_at: datetime = SEED_TIME) -> None:
        row.id = seed_id(key)
        row.created_at = SEED_TIME
        if isinstance(row, TimestampMixin):
            row.updated_at = updated_at
        rows.append(row)

    for key, name, role in (
        ("customer-a", "模拟消费者甲", UserRole.CUSTOMER),
        ("customer-b", "模拟消费者乙", UserRole.CUSTOMER),
        ("operator", "模拟运营员", UserRole.OPERATOR),
    ):
        add(User(external_subject=f"seed:{key}", display_name=name, role=role), key)

    skus: list[ProductSKU] = []
    for index, (name, colors, price, status) in enumerate((
        ("纯棉短袖", ("白色", "黑色"), "59.00", ProductStatus.ACTIVE),
        ("连帽卫衣", ("蓝色", "灰色"), "129.00", ProductStatus.ACTIVE),
        ("旧款外套", ("黑色", "蓝色"), "199.00", ProductStatus.INACTIVE),
    ), start=1):
        product_key = f"product-{index}"
        add(Product(product_code=f"SEED-P{index:03}", name=name, description=f"仅用于开发测试的{name}，不是真实商品。", brand="模拟品牌", category_code="clothing", status=status), product_key)
        for color in colors:
            for size in ("M", "L"):
                number = len(skus) + 1
                sku = ProductSKU(product_id=seed_id(product_key), sku_code=f"SEED-SKU{number:03}", specs={"color": color, "size": size}, spec_key=f"color={color}|size={size}", price=Decimal(price), currency="CNY", status=SKUStatus.INACTIVE if number == 4 else SKUStatus.ACTIVE)
                sku.id = seed_id(f"sku-{number}")
                skus.append(sku)
    for number, sku in enumerate(skus, start=1):
        add(sku, f"sku-{number}")

    stocks = [(20, 3), (2, 0), (5, 5), (0, 0), (10, 1), (2, 1), (0, 0), (10, 0), (0, 0), (0, 0), (0, 0), (0, 0)]
    for number, (on_hand, reserved) in enumerate(stocks, start=1):
        add(Inventory(sku_id=seed_id(f"sku-{number}"), warehouse_code="SEED-WH01", on_hand=on_hand, reserved=reserved), f"stock-{number}", SEED_TIME + timedelta(days=3))

    # (SKU number, quantity); reserved stock corresponds to unshipped paid items.
    lines = [[(1, 1)], [(1, 3), (3, 5), (6, 1)], [(2, 1), (5, 2)], [(2, 1), (8, 1)], [(1, 2), (5, 1)], [(4, 1)]]
    statuses = [OrderStatus.PENDING_PAYMENT, OrderStatus.PENDING_FULFILLMENT, OrderStatus.PARTIALLY_SHIPPED, OrderStatus.SHIPPED, OrderStatus.COMPLETED, OrderStatus.CANCELLED]
    items: list[OrderItem] = []
    for number, (status, order_lines) in enumerate(zip(statuses, lines), start=1):
        subtotal = sum((skus[sku - 1].price * quantity for sku, quantity in order_lines), Decimal("0"))
        discount = Decimal("10.00") if number == 2 else Decimal("0")
        shipping = Decimal("6.00") if number == 2 else Decimal("0")
        payable = subtotal - discount + shipping
        paid = status not in (OrderStatus.PENDING_PAYMENT, OrderStatus.CANCELLED)
        user_key = "customer-a" if number % 2 else "customer-b"
        add(Order(
            order_no=f"SEED-O{number:03}", user_id=seed_id(user_key), status=status,
            payment_status=PaymentStatus.PARTIALLY_REFUNDED if number == 5 else PaymentStatus.PAID if paid else PaymentStatus.UNPAID,
            subtotal_amount=subtotal, discount_amount=discount, shipping_fee=shipping,
            payable_amount=payable, paid_amount=payable if paid else Decimal("0"), currency="CNY",
            shipping_address_snapshot={"recipient": "模拟收件人", "city": "模拟城市", "address": "开发测试地址，非真实地址"},
            paid_at=SEED_TIME + timedelta(hours=2) if paid else None,
            cancelled_at=SEED_TIME + timedelta(days=1) if status == OrderStatus.CANCELLED else None,
            completed_at=SEED_TIME + timedelta(days=5) if status == OrderStatus.COMPLETED else None,
        ), f"order-{number}", SEED_TIME + timedelta(days=8 if number == 5 else 3 if paid else 1))
        for line, (sku_number, quantity) in enumerate(order_lines, start=1):
            sku = skus[sku_number - 1]
            item_discount = discount if line == 1 else Decimal("0")
            item = OrderItem(order_id=seed_id(f"order-{number}"), line_no=line, sku_id=sku.id,
                product_name_snapshot="纯棉短袖" if sku_number <= 4 else "连帽卫衣", sku_code_snapshot=sku.sku_code,
                specs_snapshot=sku.specs.copy(), quantity=quantity, unit_price=sku.price,
                discount_amount=item_discount, line_amount=sku.price * quantity - item_discount)
            item.id = seed_id(f"order-{number}-line-{line}")
            items.append(item)
    for item in items:
        item.created_at = item.updated_at = SEED_TIME
        rows.append(item)

    allocations: list[LogisticsItem] = []
    for key, order_number, status, contents in (
        ("pending", 2, LogisticsStatus.PENDING, [(1, 3), (2, 5), (3, 1)]),
        ("partial", 3, LogisticsStatus.IN_TRANSIT, [(1, 1), (2, 1)]),
        ("split-a", 4, LogisticsStatus.IN_TRANSIT, [(1, 1)]),
        ("split-b", 4, LogisticsStatus.IN_TRANSIT, [(2, 1)]),
        ("delivered", 5, LogisticsStatus.DELIVERED, [(1, 2), (2, 1)]),
    ):
        sent = status != LogisticsStatus.PENDING
        event_time = SEED_TIME + timedelta(days=4 if status == LogisticsStatus.DELIVERED else 2)
        add(Logistics(order_id=seed_id(f"order-{order_number}"), carrier_code="SEED-CARRIER" if sent else None,
            tracking_no=f"SEED-TRACK-{key}" if sent else None, status=status,
            latest_event="模拟已签收" if status == LogisticsStatus.DELIVERED else "模拟运输中" if sent else None,
            latest_event_at=event_time if sent else None, synced_at=event_time + timedelta(hours=1),
            shipped_at=SEED_TIME + timedelta(days=1) if sent else None,
            delivered_at=event_time if status == LogisticsStatus.DELIVERED else None), f"package-{key}", event_time + timedelta(hours=1))
        for line, quantity in contents:
            item = LogisticsItem(logistics_id=seed_id(f"package-{key}"), order_item_id=seed_id(f"order-{order_number}-line-{line}"), quantity=quantity)
            item.id = seed_id(f"package-{key}-line-{line}")
            item.created_at = item.updated_at = SEED_TIME
            allocations.append(item)
    rows.extend(allocations)

    add(Refund(refund_no="SEED-R001", order_item_id=seed_id("order-5-line-1"), requested_by=seed_id("customer-a"),
        quantity=1, amount=Decimal("59.00"), reason="仅用于测试的历史部分退款", status=RefundStatus.SUCCEEDED,
        requested_at=SEED_TIME + timedelta(days=6), processed_at=SEED_TIME + timedelta(days=7), refunded_at=SEED_TIME + timedelta(days=8)), "refund-1", SEED_TIME + timedelta(days=8))
    for index, (scope, title, content) in enumerate((
        (ScopeType.GLOBAL, "模拟售后规则", "仅为开发测试文本，不构成真实商家承诺；售后需核实订单与适用规则。"),
        (ScopeType.CATEGORY, "模拟服装说明", "仅为开发测试文本；服装规格以订单快照为准。"),
    ), start=1):
        add(KnowledgeDocument(document_key=f"SEED-POLICY{index:03}", version=1, title=title,
            source_uri=f"seed://policy/{index}", content=content, content_hash=sha256(content.encode()).hexdigest(),
            status=DocumentStatus.DRAFT, scope_type=scope, category_code="clothing" if scope == ScopeType.CATEGORY else None,
            valid_from=SEED_TIME), f"policy-{index}")
    return rows


async def seed_data(session: AsyncSession, *, app_env: str) -> SeedResult:
    if app_env not in {"development", "test"}:
        raise ValueError("seed_requires_development_or_test")
    inserted = existing = 0
    # ponytail: small fixed dataset; per-row ORM checks keep this seed explicit and non-destructive.
    for row in seed_rows():
        if await session.get(type(row), row.id) is not None:
            existing += 1
            continue
        session.add(row)
        await session.flush()
        inserted += 1
    return SeedResult(inserted=inserted, existing=existing)


async def main() -> None:
    settings = Settings()
    if settings.app_env not in {"development", "test"}:
        raise SystemExit("Seed is only available in development/test")
    engine = create_db_engine(settings.database_url.get_secret_value())
    try:
        async with create_session_factory(engine)() as session, session.begin():
            result = await seed_data(session, app_env=settings.app_env)
        print(json.dumps(asdict(result)))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
