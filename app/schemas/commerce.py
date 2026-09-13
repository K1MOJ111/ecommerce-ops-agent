from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.db.models.commerce import LogisticsStatus, OrderStatus, PaymentStatus


class ProductSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_code: str
    name: str
    brand: str
    category_code: str


class ProductDetail(ProductSummary):
    description: str


class SKUData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    sku_code: str
    specs: dict[str, object]
    price: Decimal
    currency: str


class StockData(BaseModel):
    warehouse_code: str
    on_hand: int
    reserved: int
    available: int
    updated_at: datetime


class InventoryResult(BaseModel):
    sku_id: UUID
    stocks: list[StockData]
    queried_at: datetime


class OrderItemData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_no: int
    sku_id: UUID
    product_name_snapshot: str
    sku_code_snapshot: str
    specs_snapshot: dict[str, object]
    quantity: int
    unit_price: Decimal
    discount_amount: Decimal
    line_amount: Decimal


class OrderData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_no: str
    status: OrderStatus
    payment_status: PaymentStatus
    subtotal_amount: Decimal
    discount_amount: Decimal
    shipping_fee: Decimal
    payable_amount: Decimal
    paid_amount: Decimal
    currency: str
    created_at: datetime
    paid_at: datetime | None
    cancelled_at: datetime | None
    completed_at: datetime | None
    items: list[OrderItemData]


class PackageItemData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_item_id: UUID
    quantity: int


class PackageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    carrier_code: str | None
    tracking_no: str | None
    status: LogisticsStatus
    latest_event: str | None
    latest_event_at: datetime | None
    synced_at: datetime | None
    shipped_at: datetime | None
    delivered_at: datetime | None
    items: list[PackageItemData]


class LogisticsResult(BaseModel):
    order_id: UUID
    packages: list[PackageData]
    queried_at: datetime
