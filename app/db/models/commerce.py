from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CHAR, CheckConstraint, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class UserRole(StrEnum):
    CUSTOMER = "customer"
    OPERATOR = "operator"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ProductStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"


class SKUStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class OrderStatus(StrEnum):
    PENDING_PAYMENT = "pending_payment"
    PENDING_FULFILLMENT = "pending_fulfillment"
    PARTIALLY_SHIPPED = "partially_shipped"
    SHIPPED = "shipped"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    CLOSED = "closed"


class PaymentStatus(StrEnum):
    UNPAID = "unpaid"
    PAID = "paid"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"


class LogisticsStatus(StrEnum):
    PENDING = "pending"
    SHIPPED = "shipped"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    EXCEPTION = "exception"
    RETURNED = "returned"


class RefundStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


def status_type(enum: type[StrEnum]) -> Enum:
    return Enum(enum, native_enum=False, create_constraint=True,
                values_callable=lambda members: [member.value for member in members])


class User(TimestampMixin, Base):
    __tablename__ = "users"

    external_subject: Mapped[str | None] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[UserRole] = mapped_column(status_type(UserRole), default=UserRole.CUSTOMER)
    status: Mapped[UserStatus] = mapped_column(status_type(UserStatus), default=UserStatus.ACTIVE)
    orders: Mapped[list[Order]] = relationship(back_populates="user", lazy="raise", passive_deletes="all")


class Product(TimestampMixin, Base):
    __tablename__ = "products"

    product_code: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    brand: Mapped[str] = mapped_column(String(100))
    category_code: Mapped[str] = mapped_column(String(100))
    status: Mapped[ProductStatus] = mapped_column(status_type(ProductStatus), default=ProductStatus.DRAFT)


class ProductSKU(TimestampMixin, Base):
    __tablename__ = "product_skus"
    __table_args__ = (
        UniqueConstraint("product_id", "spec_key"),
        CheckConstraint("price >= 0 AND price < 'Infinity'::numeric", name="price_range"),
        CheckConstraint("currency = 'CNY'", name="currency"),
        CheckConstraint("jsonb_typeof(specs) = 'object'", name="specs_object"),
    )

    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    sku_code: Mapped[str] = mapped_column(String(100), unique=True)
    specs: Mapped[dict[str, object]] = mapped_column(JSONB)
    spec_key: Mapped[str] = mapped_column(String(255))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(CHAR(3), default="CNY")
    status: Mapped[SKUStatus] = mapped_column(status_type(SKUStatus), default=SKUStatus.ACTIVE)


class Inventory(TimestampMixin, Base):
    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("sku_id", "warehouse_code"),
        CheckConstraint("on_hand >= 0 AND reserved >= 0 AND reserved <= on_hand", name="stock_range"),
    )

    sku_id: Mapped[UUID] = mapped_column(ForeignKey("product_skus.id", ondelete="RESTRICT"))
    warehouse_code: Mapped[str] = mapped_column(String(100))
    on_hand: Mapped[int] = mapped_column(default=0)
    reserved: Mapped[int] = mapped_column(default=0)


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_user_id_created_at", "user_id", "created_at"),
        CheckConstraint(
            "subtotal_amount >= 0 AND subtotal_amount < 'Infinity'::numeric "
            "AND discount_amount >= 0 AND discount_amount <= subtotal_amount "
            "AND shipping_fee >= 0 AND shipping_fee < 'Infinity'::numeric "
            "AND payable_amount >= 0 AND payable_amount < 'Infinity'::numeric "
            "AND paid_amount >= 0 AND paid_amount <= payable_amount", name="amount_range",
        ),
        CheckConstraint("payable_amount = subtotal_amount - discount_amount + shipping_fee", name="payable_total"),
        CheckConstraint("currency = 'CNY'", name="currency"),
        CheckConstraint("jsonb_typeof(shipping_address_snapshot) = 'object'", name="address_object"),
    )

    order_no: Mapped[str] = mapped_column(String(100), unique=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    status: Mapped[OrderStatus] = mapped_column(status_type(OrderStatus), default=OrderStatus.PENDING_PAYMENT)
    payment_status: Mapped[PaymentStatus] = mapped_column(status_type(PaymentStatus), default=PaymentStatus.UNPAID)
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    shipping_fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    payable_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(CHAR(3), default="CNY")
    shipping_address_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="orders", lazy="raise")
    items: Mapped[list[OrderItem]] = relationship(back_populates="order", lazy="raise", passive_deletes="all")


class OrderItem(TimestampMixin, Base):
    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "line_no"),
        CheckConstraint("quantity > 0 AND line_no > 0", name="quantity_line_positive"),
        CheckConstraint(
            "unit_price >= 0 AND unit_price < 'Infinity'::numeric "
            "AND discount_amount >= 0 AND discount_amount <= unit_price * quantity "
            "AND line_amount >= 0 AND line_amount < 'Infinity'::numeric", name="amount_range",
        ),
        CheckConstraint("line_amount = unit_price * quantity - discount_amount", name="line_total"),
        CheckConstraint("jsonb_typeof(specs_snapshot) = 'object'", name="specs_object"),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    line_no: Mapped[int]
    sku_id: Mapped[UUID] = mapped_column(ForeignKey("product_skus.id", ondelete="RESTRICT"), index=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(255))
    sku_code_snapshot: Mapped[str] = mapped_column(String(100))
    specs_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    quantity: Mapped[int]
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    line_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    order: Mapped[Order] = relationship(back_populates="items", lazy="raise")


class Logistics(TimestampMixin, Base):
    __tablename__ = "logistics"
    __table_args__ = (
        UniqueConstraint("carrier_code", "tracking_no"),
        CheckConstraint(
            "tracking_no IS NULL OR (length(trim(tracking_no)) > 0 "
            "AND carrier_code IS NOT NULL AND length(trim(carrier_code)) > 0)", name="tracking_carrier",
        ),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), index=True)
    carrier_code: Mapped[str | None] = mapped_column(String(100))
    tracking_no: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[LogisticsStatus] = mapped_column(status_type(LogisticsStatus), default=LogisticsStatus.PENDING)
    latest_event: Mapped[str | None] = mapped_column(Text)
    latest_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LogisticsItem(TimestampMixin, Base):
    __tablename__ = "logistics_items"
    __table_args__ = (
        UniqueConstraint("logistics_id", "order_item_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    logistics_id: Mapped[UUID] = mapped_column(ForeignKey("logistics.id", ondelete="RESTRICT"))
    order_item_id: Mapped[UUID] = mapped_column(ForeignKey("order_items.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[int]


class Refund(TimestampMixin, Base):
    __tablename__ = "refunds"
    __table_args__ = (
        Index("ix_refunds_order_item_id_status", "order_item_id", "status"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("amount > 0 AND amount < 'Infinity'::numeric", name="amount_range"),
    )

    refund_no: Mapped[str] = mapped_column(String(100), unique=True)
    order_item_id: Mapped[UUID] = mapped_column(ForeignKey("order_items.id", ondelete="RESTRICT"))
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[int]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[RefundStatus] = mapped_column(status_type(RefundStatus), default=RefundStatus.REQUESTED)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
