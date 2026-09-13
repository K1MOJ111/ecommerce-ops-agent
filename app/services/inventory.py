from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.commerce import Inventory, Product, ProductSKU, ProductStatus, SKUStatus
from app.schemas.commerce import InventoryResult, StockData


async def get_inventory(
    session: AsyncSession, sku_id: UUID, *, warehouse_code: str | None = None,
) -> InventoryResult | None:
    if warehouse_code is not None and not 1 <= len(warehouse_code.strip()) <= 100:
        raise ValueError("invalid_warehouse_code")
    sku = await session.scalar(select(ProductSKU.id).join(Product).where(
        ProductSKU.id == sku_id, ProductSKU.status == SKUStatus.ACTIVE, Product.status == ProductStatus.ACTIVE,
    ))
    if sku is None:
        return None
    statement = select(Inventory).where(Inventory.sku_id == sku_id)
    if warehouse_code is not None:
        statement = statement.where(Inventory.warehouse_code == warehouse_code.strip())
    rows = await session.scalars(statement.order_by(Inventory.warehouse_code))
    return InventoryResult(sku_id=sku_id, queried_at=datetime.now(UTC), stocks=[
        StockData(warehouse_code=row.warehouse_code, on_hand=row.on_hand, reserved=row.reserved,
                  available=row.on_hand - row.reserved, updated_at=row.updated_at)
        for row in rows
    ])
