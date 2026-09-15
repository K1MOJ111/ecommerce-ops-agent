"""Shared committed PostgreSQL fixture, extracted unchanged from Phase 06 tests."""
import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import delete, func, select
from app.agent.checkpoint import checkpoint_session, setup_checkpoints
from app.agent.graph import AgentContext
from app.core.config import Settings
from app.core.security import RequestContext
from app.db.models import AgentWorkflow, AuditLog, Logistics, Order, OrderItem, Product, ProductSKU, Refund, User
from app.db.session import create_db_engine, create_session_factory
from app.schemas.operations import ResumeRequest, StartRequest
from app.services.workflows import resume_workflow, start_workflow

CANCEL = "request_order_cancellation"
REFUND = "create_refund_request"
PERMISSIONS = frozenset({"orders:read:self", "orders:cancel:self", "refunds:request:self"})

@asynccontextmanager
async def workflow_fixture(migrated_database, fake_model):
    await asyncio.to_thread(setup_checkpoints, migrated_database)
    engine = create_db_engine(migrated_database)
    sessions = create_session_factory(engine)
    marker = str(uuid4())
    user_ids = [uuid4(), uuid4()]
    product_id, sku_id = uuid4(), uuid4()
    order_ids, item_ids = [uuid4(), uuid4()], [uuid4(), uuid4()]
    settings = Settings(_env_file=None, database_url=migrated_database, app_env="test")
    try:
        async with sessions() as session, session.begin():
            session.add_all([User(id=i, display_name="HITL fixture") for i in user_ids])
            session.add(Product(id=product_id, product_code=marker, name="HITL item", description="simulated", brand="test", category_code="test"))
            await session.flush()
            session.add(ProductSKU(id=sku_id, product_id=product_id, sku_code=marker, specs={}, spec_key="fixture", price=Decimal("10")))
            await session.flush()
            for i in range(2):
                session.add(Order(id=order_ids[i], user_id=user_ids[0], order_no=f"HITL-{marker}-{i}",
                                  status="pending_payment" if i == 0 else "completed",
                                  payment_status="unpaid" if i == 0 else "paid",
                                  subtotal_amount=Decimal("20"), payable_amount=Decimal("20"),
                                  paid_amount=Decimal("0" if i == 0 else "20"), shipping_address_snapshot={"private": "must-not-leak"}))
            await session.flush()
            for i in range(2):
                session.add(OrderItem(id=item_ids[i], order_id=order_ids[i], line_no=1, sku_id=sku_id,
                                      product_name_snapshot="HITL item", sku_code_snapshot=marker, specs_snapshot={},
                                      quantity=2, unit_price=Decimal("10"), line_amount=Decimal("20")))

        def context(model=None, *, actor=None, permissions=PERMISSIONS, factory=None):
            return AgentContext(RequestContext(actor or user_ids[0], permissions, uuid4()),
                                model or fake_model(), factory or sessions, settings)

        def args(kind=CANCEL, **overrides):
            params = {"order_no": f"HITL-{marker}-{0 if kind == CANCEL else 1}", "reason": "test reason"}
            if kind == REFUND:
                params.update(order_item_id=str(item_ids[1]), quantity=1, amount="10.00")
            return {**params, **overrides}

        async def start(kind=CANCEL, *, arguments=None, actor=None, permissions=PERMISSIONS, request_key=None):
            model = fake_model([(kind, arguments if arguments is not None else args(kind))], {"action": "answer", "evidence_ids": []})
            return await start_workflow(StartRequest(request_key=request_key or uuid4(), message="用户请求业务操作"),
                                        context=context(model, actor=actor, permissions=permissions))

        async def resume(row, decision="confirm", **kwargs):
            return await resume_workflow(row.thread_id, ResumeRequest(operation_id=row.operation_id, decision=decision), context=context(**kwargs))

        yield SimpleNamespace(engine=engine, sessions=sessions, settings=settings, context=context, args=args,
                              start=start, resume=resume, users=user_ids, orders=order_ids, items=item_ids, product_id=product_id)
    finally:
        # Delete only UUID-scoped rows this fixture owns, never truncate a database or touch development data.
        async with sessions() as session:
            threads = list(await session.scalars(select(AgentWorkflow.id).where(AgentWorkflow.actor_id.in_(user_ids))))
        for thread_id in threads:
            async with checkpoint_session(migrated_database, thread_id) as saver:
                await asyncio.to_thread(saver.delete_thread, str(thread_id))
        async with sessions() as session, session.begin():
            await session.execute(delete(AuditLog).where(AuditLog.actor_id.in_(user_ids)))
            await session.execute(delete(AgentWorkflow).where(AgentWorkflow.actor_id.in_(user_ids)))
            await session.execute(delete(Refund).where(Refund.order_item_id.in_(item_ids)))
            await session.execute(delete(Logistics).where(Logistics.order_id.in_(order_ids)))
            await session.execute(delete(OrderItem).where(OrderItem.id.in_(item_ids)))
            await session.execute(delete(Order).where(Order.id.in_(order_ids)))
            await session.execute(delete(ProductSKU).where(ProductSKU.id == sku_id))
            await session.execute(delete(Product).where(Product.id == product_id))
            await session.execute(delete(User).where(User.id.in_(user_ids)))
        await engine.dispose()



async def counts(env):
    async with env.sessions() as session:
        return (await session.scalar(select(Order.status).where(Order.id == env.orders[0])),
                await session.scalar(select(func.count()).select_from(Refund).where(Refund.order_item_id.in_(env.items))),
                await session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.actor_id.in_(env.users))))
