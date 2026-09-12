"""initial_schema

Revision ID: 0001
Revises: 
Create Date: 2026-09-12 19:38:04.112337

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
    op.create_table('products',
    sa.Column('product_code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('brand', sa.String(length=100), nullable=False),
    sa.Column('category_code', sa.String(length=100), nullable=False),
    sa.Column('status', sa.Enum('draft', 'active', 'inactive', name='productstatus', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_products')),
    sa.UniqueConstraint('product_code', name=op.f('uq_products_product_code'))
    )
    op.create_table('users',
    sa.Column('external_subject', sa.String(length=255), nullable=True),
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('role', sa.Enum('customer', 'operator', name='userrole', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('status', sa.Enum('active', 'disabled', name='userstatus', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('external_subject', name=op.f('uq_users_external_subject'))
    )
    op.create_table('audit_logs',
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('request_id', sa.Uuid(), nullable=False),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('resource_type', sa.String(length=100), nullable=False),
    sa.Column('resource_id', sa.Uuid(), nullable=True),
    sa.Column('result', sa.String(length=100), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("jsonb_typeof(details) = 'object'", name=op.f('ck_audit_logs_details_object')),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_audit_logs_actor_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index(op.f('ix_audit_logs_actor_id'), 'audit_logs', ['actor_id'], unique=False)
    op.create_table('knowledge_documents',
    sa.Column('document_key', sa.String(length=150), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('source_uri', sa.Text(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('content_hash', sa.String(length=128), nullable=False),
    sa.Column('status', sa.Enum('draft', 'published', 'archived', name='documentstatus', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('scope_type', sa.Enum('global', 'category', 'product', name='scopetype', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('category_code', sa.String(length=100), nullable=True),
    sa.Column('product_id', sa.Uuid(), nullable=True),
    sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(scope_type = 'global' AND category_code IS NULL AND product_id IS NULL) OR (scope_type = 'category' AND category_code IS NOT NULL AND length(trim(category_code)) > 0 AND product_id IS NULL) OR (scope_type = 'product' AND product_id IS NOT NULL AND category_code IS NULL)", name=op.f('ck_knowledge_documents_scope_fields')),
    sa.CheckConstraint('valid_to IS NULL OR valid_to > valid_from', name=op.f('ck_knowledge_documents_valid_period')),
    sa.CheckConstraint('version > 0', name=op.f('ck_knowledge_documents_version_positive')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_knowledge_documents_product_id_products'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_documents')),
    sa.UniqueConstraint('document_key', 'version', name=op.f('uq_knowledge_documents_document_key'))
    )
    op.create_index(op.f('ix_knowledge_documents_product_id'), 'knowledge_documents', ['product_id'], unique=False)
    op.create_table('orders',
    sa.Column('order_no', sa.String(length=100), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('pending_payment', 'pending_fulfillment', 'partially_shipped', 'shipped', 'completed', 'cancelled', 'closed', name='orderstatus', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('payment_status', sa.Enum('unpaid', 'paid', 'partially_refunded', 'refunded', name='paymentstatus', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('subtotal_amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('discount_amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('shipping_fee', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('payable_amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('paid_amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('currency', sa.CHAR(length=3), nullable=False),
    sa.Column('shipping_address_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("currency = 'CNY'", name=op.f('ck_orders_currency')),
    sa.CheckConstraint("jsonb_typeof(shipping_address_snapshot) = 'object'", name=op.f('ck_orders_address_object')),
    sa.CheckConstraint("subtotal_amount >= 0 AND subtotal_amount < 'Infinity'::numeric AND discount_amount >= 0 AND discount_amount <= subtotal_amount AND shipping_fee >= 0 AND shipping_fee < 'Infinity'::numeric AND payable_amount >= 0 AND payable_amount < 'Infinity'::numeric AND paid_amount >= 0 AND paid_amount <= payable_amount", name=op.f('ck_orders_amount_range')),
    sa.CheckConstraint('payable_amount = subtotal_amount - discount_amount + shipping_fee', name=op.f('ck_orders_payable_total')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_orders_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_orders')),
    sa.UniqueConstraint('order_no', name=op.f('uq_orders_order_no'))
    )
    op.create_index('ix_orders_user_id_created_at', 'orders', ['user_id', 'created_at'], unique=False)
    op.create_table('product_skus',
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('sku_code', sa.String(length=100), nullable=False),
    sa.Column('specs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('spec_key', sa.String(length=255), nullable=False),
    sa.Column('price', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('currency', sa.CHAR(length=3), nullable=False),
    sa.Column('status', sa.Enum('active', 'inactive', name='skustatus', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("currency = 'CNY'", name=op.f('ck_product_skus_currency')),
    sa.CheckConstraint("jsonb_typeof(specs) = 'object'", name=op.f('ck_product_skus_specs_object')),
    sa.CheckConstraint("price >= 0 AND price < 'Infinity'::numeric", name=op.f('ck_product_skus_price_range')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_product_skus_product_id_products'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_product_skus')),
    sa.UniqueConstraint('product_id', 'spec_key', name=op.f('uq_product_skus_product_id')),
    sa.UniqueConstraint('sku_code', name=op.f('uq_product_skus_sku_code'))
    )
    op.create_table('inventory',
    sa.Column('sku_id', sa.Uuid(), nullable=False),
    sa.Column('warehouse_code', sa.String(length=100), nullable=False),
    sa.Column('on_hand', sa.Integer(), nullable=False),
    sa.Column('reserved', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('on_hand >= 0 AND reserved >= 0 AND reserved <= on_hand', name=op.f('ck_inventory_stock_range')),
    sa.ForeignKeyConstraint(['sku_id'], ['product_skus.id'], name=op.f('fk_inventory_sku_id_product_skus'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory')),
    sa.UniqueConstraint('sku_id', 'warehouse_code', name=op.f('uq_inventory_sku_id'))
    )
    op.create_table('knowledge_chunks',
    sa.Column('document_id', sa.Uuid(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('locator', sa.String(length=500), nullable=False),
    sa.Column('embedding', Vector(), nullable=True),
    sa.Column('embedding_model', sa.String(length=255), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('(embedding IS NULL AND embedding_model IS NULL) OR (embedding IS NOT NULL AND embedding_model IS NOT NULL AND length(trim(embedding_model)) > 0)', name=op.f('ck_knowledge_chunks_embedding_pair')),
    sa.CheckConstraint('chunk_index >= 0', name=op.f('ck_knowledge_chunks_chunk_index_nonnegative')),
    sa.ForeignKeyConstraint(['document_id'], ['knowledge_documents.id'], name=op.f('fk_knowledge_chunks_document_id_knowledge_documents'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_chunks')),
    sa.UniqueConstraint('document_id', 'chunk_index', name=op.f('uq_knowledge_chunks_document_id'))
    )
    op.create_table('logistics',
    sa.Column('order_id', sa.Uuid(), nullable=False),
    sa.Column('carrier_code', sa.String(length=100), nullable=True),
    sa.Column('tracking_no', sa.String(length=100), nullable=True),
    sa.Column('status', sa.Enum('pending', 'shipped', 'in_transit', 'delivered', 'exception', 'returned', name='logisticsstatus', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('latest_event', sa.Text(), nullable=True),
    sa.Column('latest_event_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('tracking_no IS NULL OR (length(trim(tracking_no)) > 0 AND carrier_code IS NOT NULL AND length(trim(carrier_code)) > 0)', name=op.f('ck_logistics_tracking_carrier')),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_logistics_order_id_orders'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_logistics')),
    sa.UniqueConstraint('carrier_code', 'tracking_no', name=op.f('uq_logistics_carrier_code'))
    )
    op.create_index(op.f('ix_logistics_order_id'), 'logistics', ['order_id'], unique=False)
    op.create_table('order_items',
    sa.Column('order_id', sa.Uuid(), nullable=False),
    sa.Column('line_no', sa.Integer(), nullable=False),
    sa.Column('sku_id', sa.Uuid(), nullable=False),
    sa.Column('product_name_snapshot', sa.String(length=255), nullable=False),
    sa.Column('sku_code_snapshot', sa.String(length=100), nullable=False),
    sa.Column('specs_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('discount_amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('line_amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("jsonb_typeof(specs_snapshot) = 'object'", name=op.f('ck_order_items_specs_object')),
    sa.CheckConstraint("unit_price >= 0 AND unit_price < 'Infinity'::numeric AND discount_amount >= 0 AND discount_amount <= unit_price * quantity AND line_amount >= 0 AND line_amount < 'Infinity'::numeric", name=op.f('ck_order_items_amount_range')),
    sa.CheckConstraint('line_amount = unit_price * quantity - discount_amount', name=op.f('ck_order_items_line_total')),
    sa.CheckConstraint('quantity > 0 AND line_no > 0', name=op.f('ck_order_items_quantity_line_positive')),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_order_items_order_id_orders'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['sku_id'], ['product_skus.id'], name=op.f('fk_order_items_sku_id_product_skus'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order_items')),
    sa.UniqueConstraint('order_id', 'line_no', name=op.f('uq_order_items_order_id'))
    )
    op.create_index(op.f('ix_order_items_sku_id'), 'order_items', ['sku_id'], unique=False)
    op.create_table('logistics_items',
    sa.Column('logistics_id', sa.Uuid(), nullable=False),
    sa.Column('order_item_id', sa.Uuid(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_logistics_items_quantity_positive')),
    sa.ForeignKeyConstraint(['logistics_id'], ['logistics.id'], name=op.f('fk_logistics_items_logistics_id_logistics'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['order_item_id'], ['order_items.id'], name=op.f('fk_logistics_items_order_item_id_order_items'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_logistics_items')),
    sa.UniqueConstraint('logistics_id', 'order_item_id', name=op.f('uq_logistics_items_logistics_id'))
    )
    op.create_index(op.f('ix_logistics_items_order_item_id'), 'logistics_items', ['order_item_id'], unique=False)
    op.create_table('refunds',
    sa.Column('refund_no', sa.String(length=100), nullable=False),
    sa.Column('order_item_id', sa.Uuid(), nullable=False),
    sa.Column('requested_by', sa.Uuid(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('status', sa.Enum('requested', 'approved', 'rejected', 'processing', 'succeeded', 'failed', 'cancelled', name='refundstatus', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('refunded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("amount > 0 AND amount < 'Infinity'::numeric", name=op.f('ck_refunds_amount_range')),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_refunds_quantity_positive')),
    sa.ForeignKeyConstraint(['order_item_id'], ['order_items.id'], name=op.f('fk_refunds_order_item_id_order_items'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_refunds_requested_by_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refunds')),
    sa.UniqueConstraint('refund_no', name=op.f('uq_refunds_refund_no'))
    )
    op.create_index('ix_refunds_order_item_id_status', 'refunds', ['order_item_id', 'status'], unique=False)
    op.create_index(op.f('ix_refunds_requested_by'), 'refunds', ['requested_by'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Extensions may predate this revision or be shared; preserve them on downgrade.
    op.drop_index(op.f('ix_refunds_requested_by'), table_name='refunds')
    op.drop_index('ix_refunds_order_item_id_status', table_name='refunds')
    op.drop_table('refunds')
    op.drop_index(op.f('ix_logistics_items_order_item_id'), table_name='logistics_items')
    op.drop_table('logistics_items')
    op.drop_index(op.f('ix_order_items_sku_id'), table_name='order_items')
    op.drop_table('order_items')
    op.drop_index(op.f('ix_logistics_order_id'), table_name='logistics')
    op.drop_table('logistics')
    op.drop_table('knowledge_chunks')
    op.drop_table('inventory')
    op.drop_table('product_skus')
    op.drop_index('ix_orders_user_id_created_at', table_name='orders')
    op.drop_table('orders')
    op.drop_index(op.f('ix_knowledge_documents_product_id'), table_name='knowledge_documents')
    op.drop_table('knowledge_documents')
    op.drop_index(op.f('ix_audit_logs_actor_id'), table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_table('users')
    op.drop_table('products')
