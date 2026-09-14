from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import RequestContext
from app.db.models.commerce import Logistics, LogisticsItem, Order, OrderItem
from app.schemas.commerce import LogisticsResult, OrderData, PackageData, PackageItemData


class OrderNotAccessible(LookupError):
    """Same outcome for missing permission, another customer's order, and absent order."""

    def __init__(self) -> None:
        super().__init__("order_not_accessible")


async def _authorized_order(
    session: AsyncSession, context: RequestContext, *, order_id: UUID | None, order_no: str | None,
    load_items: bool = True,
) -> Order:
    if (order_id is None) == (order_no is None):
        raise ValueError("provide_exactly_one_order_identifier")
    if order_no is not None and not 1 <= len(order_no.strip()) <= 100:
        raise ValueError("invalid_order_no")
    statement = select(Order).where(Order.id == order_id) if order_id is not None else select(Order).where(Order.order_no == order_no.strip())
    if "orders:read:any" not in context.permissions:
        if "orders:read:self" not in context.permissions:
            raise OrderNotAccessible()
        statement = statement.where(Order.user_id == context.actor_id)
    if load_items:
        statement = statement.options(selectinload(Order.items))
    row = await session.scalar(statement)
    if row is None:
        raise OrderNotAccessible()
    return row


async def authorize_order_access(session: AsyncSession, context: RequestContext, order_id: UUID) -> None:
    """Recheck current read scope and ownership without reloading historical evidence."""
    await _authorized_order(session, context, order_id=order_id, order_no=None, load_items=False)


async def get_order(
    session: AsyncSession, context: RequestContext, *, order_id: UUID | None = None, order_no: str | None = None,
) -> OrderData:
    order = await _authorized_order(session, context, order_id=order_id, order_no=order_no)
    data = OrderData.model_validate(order)
    data.items.sort(key=lambda item: item.line_no)
    return data


async def get_logistics(
    session: AsyncSession, context: RequestContext, *, order_id: UUID | None = None, order_no: str | None = None,
) -> LogisticsResult:
    order = await _authorized_order(session, context, order_id=order_id, order_no=order_no)
    packages = (await session.scalars(select(Logistics).where(Logistics.order_id == order.id).order_by(Logistics.created_at, Logistics.id))).all()
    package_items: dict[UUID, list[PackageItemData]] = {package.id: [] for package in packages}
    if packages:
        rows = await session.scalars(select(LogisticsItem).join(OrderItem).where(
            LogisticsItem.logistics_id.in_(package_items), OrderItem.order_id == order.id,
        ).order_by(OrderItem.line_no))
        for row in rows:
            # Enforce order scope on both sides, even if future bad writes link another order's item.
            package_items[row.logistics_id].append(PackageItemData.model_validate(row))
    return LogisticsResult(order_id=order.id, queried_at=datetime.now(UTC), packages=[
        PackageData.model_validate({
            **{field: getattr(package, field) for field in PackageData.model_fields if field != "items"},
            "items": package_items[package.id],
        }) for package in packages
    ])
