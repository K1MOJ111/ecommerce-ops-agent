"""Committed, isolated fixtures: real Postgres locks, checkpoints, and independent connections."""
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.checkpoint import checkpoint_session, setup_checkpoints
from app.agent.graph import AgentContext
from app.api.dependencies import get_request_context
from app.core.config import Settings
from app.core.security import RequestContext
from app.db.models import AgentWorkflow, AuditLog, Logistics, Order, OrderItem, Product, ProductSKU, Refund, User
from app.db.session import create_db_engine, create_session_factory
from app.main import create_app
from app.schemas.operations import ResumeRequest, StartRequest
from app.services import operations
from app.services.operations import OperationError, finish_operation
from app.services.workflows import get_workflow, resume_workflow, start_workflow

pytestmark = pytest.mark.integration
CANCEL = "request_order_cancellation"
REFUND = "create_refund_request"
PERMISSIONS = frozenset({"orders:read:self", "orders:cancel:self", "refunds:request:self"})


@pytest_asyncio.fixture
async def hitl_env(migrated_database, fake_model):
    from scripts.eval_support import workflow_fixture
    async with workflow_fixture(migrated_database, fake_model) as env:
        yield env


async def counts(env):
    async with env.sessions() as session:
        return (await session.scalar(select(Order.status).where(Order.id == env.orders[0])),
                await session.scalar(select(func.count()).select_from(Refund).where(Refund.order_item_id.in_(env.items))),
                await session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.actor_id.in_(env.users))))


@pytest.mark.parametrize("kind", [CANCEL, REFUND])
async def test_draft_interrupt_no_business_write(hitl_env, kind):
    env = hitl_env
    row = await env.start(kind)
    assert row.status == "waiting_for_confirmation"
    assert row.draft.operation_id == row.operation_id and row.draft.actor == env.users[0]
    assert row.draft.parameters == env.args(kind)
    assert "must-not-leak" not in row.model_dump_json()
    assert await counts(env) == ("pending_payment", 0, 0)
    async with env.sessions() as session:
        assert await session.scalar(text("SELECT count(*) FROM agent_checkpoints.checkpoints WHERE thread_id=:thread"), {"thread": str(row.thread_id)}) > 0


@pytest.mark.parametrize("kind", [CANCEL, REFUND])
async def test_confirm_and_repeat_are_stable(hitl_env, kind):
    env = hitl_env
    row = await env.start(kind)
    done = await env.resume(row)
    assert done.status == "succeeded"
    assert await env.resume(row) == done
    assert await counts(env) == ("cancelled" if kind == CANCEL else "pending_payment", int(kind == REFUND), 1)
    async with env.sessions() as session:
        assert await session.scalar(select(Order.payment_status).where(Order.id == env.orders[1])) == "paid"
        log = await session.scalar(select(AuditLog).where(AuditLog.actor_id == env.users[0]))
        assert log.details["operation_id"] == str(row.operation_id)
        assert "test reason" not in str(log.details)


@pytest.mark.parametrize("kind", [CANCEL, REFUND])
async def test_reject_writes_only_receipt_and_audit(hitl_env, kind):
    env = hitl_env
    row = await env.start(kind)
    done = await env.resume(row, "reject")
    assert done.status == "rejected" and await env.resume(row, "reject") == done
    assert await counts(env) == ("pending_payment", 0, 1)
    with pytest.raises(OperationError, match="confirmation_mismatch"):
        await env.resume(row)


@pytest.mark.parametrize("kind", [CANCEL, REFUND])
async def test_other_actor_cannot_draft_read_or_resume(hitl_env, kind):
    env = hitl_env
    denied = await env.start(kind, actor=env.users[1])
    assert denied.operation_id is None and denied.result["evidence"][0]["result"]["status"] == "forbidden"
    row = await env.start(kind)
    with pytest.raises(OperationError, match="not_accessible"):
        await get_workflow(row.thread_id, context=env.context(actor=env.users[1]))
    with pytest.raises(OperationError, match="not_accessible"):
        await env.resume(row, actor=env.users[1])
    assert await counts(env) == ("pending_payment", 0, 0)


@pytest.mark.parametrize("kind", [CANCEL, REFUND])
async def test_permissions_rechecked_on_resume(hitl_env, kind):
    row = await hitl_env.start(kind)
    with pytest.raises(OperationError, match="not_accessible"):
        await hitl_env.resume(row, permissions=frozenset({"orders:read:any"}))
    assert await counts(hitl_env) == ("pending_payment", 0, 0)


@pytest.mark.parametrize("status", ["pending_fulfillment", "partially_shipped", "shipped", "completed", "cancelled", "closed"])
async def test_cancel_invalid_status(hitl_env, status):
    env = hitl_env
    async with env.sessions() as session, session.begin():
        await session.execute(update(Order).where(Order.id == env.orders[0]).values(status=status))
    row = await env.start()
    assert row.operation_id is None
    assert row.result["evidence"][0]["result"]["error"]["code"] == "cancellation_not_allowed"


@pytest.mark.parametrize("kind", [CANCEL, REFUND])
async def test_state_changed_during_interrupt(hitl_env, kind):
    env = hitl_env
    row = await env.start(kind)
    async with env.sessions() as session, session.begin():
        await session.execute(update(Order).where(Order.id == env.orders[0 if kind == CANCEL else 1]).values(status="closed"))
    done = await env.resume(row)
    assert done.status == "conflict"
    assert await env.resume(row) == done
    assert (await counts(env))[1:] == (0, 1)


@pytest.mark.parametrize(("overrides", "code"), [
    ({"quantity": 3}, "refund_quantity_exceeded"),
    ({"amount": "10.01"}, "refund_amount_exceeded"),
    ({"quantity": 2, "amount": "20.01"}, "refund_amount_exceeded"),
])
async def test_refund_limits(hitl_env, overrides, code):
    row = await hitl_env.start(REFUND, arguments=hitl_env.args(REFUND, **overrides))
    assert row.operation_id is None and row.result["evidence"][0]["result"]["error"]["code"] == code


async def test_item_must_belong_to_order(hitl_env):
    row = await hitl_env.start(REFUND, arguments=hitl_env.args(REFUND, order_item_id=str(hitl_env.items[0])))
    assert row.operation_id is None and row.result["evidence"][0]["result"]["status"] == "forbidden"


async def test_existing_refund_reserves_quantity_and_amount(hitl_env):
    env = hitl_env
    first = await env.start(REFUND, arguments=env.args(REFUND, quantity=2, amount="20.00"))
    await env.resume(first)
    denied = await env.start(REFUND)
    assert denied.operation_id is None
    assert (await counts(env))[1] == 1


@pytest.mark.parametrize("kind", [CANCEL, REFUND])
async def test_concurrent_confirm_independent_connections(hitl_env, kind):
    env = hitl_env
    row = await env.start(kind)
    results = await asyncio.gather(env.resume(row), env.resume(row))
    assert results[0] == results[1] and results[0].status == "succeeded"
    assert await counts(env) == ("cancelled" if kind == CANCEL else "pending_payment", int(kind == REFUND), 1)


async def test_concurrent_different_operations_cannot_over_refund(hitl_env):
    env = hitl_env
    a, b = await asyncio.gather(env.start(REFUND, arguments=env.args(REFUND, quantity=2, amount="20.00")),
                                env.start(REFUND, arguments=env.args(REFUND, quantity=2, amount="20.00")))
    done = await asyncio.gather(env.resume(a), env.resume(b))
    assert sorted(row.status for row in done) == ["conflict", "succeeded"]
    assert (await counts(env))[1:] == (1, 2)


async def test_restart_new_engine_and_model_without_memory(hitl_env):
    env = hitl_env
    row = await env.start(REFUND)
    engine = create_db_engine(env.settings.database_url.get_secret_value())
    try:
        done = await env.resume(row, factory=create_session_factory(engine))
        assert done.status == "succeeded"
    finally:
        await engine.dispose()


async def test_restart_resume_in_separate_process(hitl_env):
    env = hitl_env
    row = await env.start(REFUND)
    child = '''
import asyncio, sys
from uuid import UUID, uuid4
from app.agent.graph import AgentContext
from app.agent.llm import OpenAICompatibleModel
from app.core.config import Settings
from app.core.security import RequestContext
from app.db.session import create_db_engine, create_session_factory
from app.schemas.operations import ResumeRequest
from app.services.workflows import resume_workflow
async def main():
    settings = Settings()
    engine = create_db_engine(settings.database_url.get_secret_value())
    try:
        context = AgentContext(RequestContext(UUID(sys.argv[3]), frozenset({'refunds:request:self'}), uuid4()),
                               OpenAICompatibleModel(settings), create_session_factory(engine), settings)
        result = await resume_workflow(UUID(sys.argv[1]), ResumeRequest(operation_id=UUID(sys.argv[2]), decision='confirm'), context=context)
        assert result.status == 'succeeded'
        print('separate_process_resume_passed')
    finally:
        await engine.dispose()
asyncio.run(main())
'''
    result = await asyncio.to_thread(subprocess.run,
        [sys.executable, "-c", child, str(row.thread_id), str(row.operation_id), str(env.users[0])],
        env={**os.environ, "DATABASE_URL": env.settings.database_url.get_secret_value(), "APP_ENV": "test"},
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, "Separate process resume failed; no credential-bearing subprocess output is echoed"
    assert result.stdout.strip() == "separate_process_resume_passed"
    assert (await env.resume(row)).status == "succeeded" and (await counts(env))[1:] == (1, 1)


async def test_wrong_operation_and_nonwaiting(hitl_env, fake_model):
    env = hitl_env
    row = await env.start()
    with pytest.raises(OperationError, match="operation_mismatch"):
        await resume_workflow(row.thread_id, ResumeRequest(operation_id=uuid4(), decision="confirm"), context=env.context())
    async with env.sessions() as session, session.begin():
        await session.execute(update(AgentWorkflow).where(AgentWorkflow.id == row.thread_id).values(status="running"))
    with pytest.raises(OperationError, match="not_waiting_for_confirmation"):
        await env.resume(row)


@pytest.mark.parametrize("decision", [True, False, "yes", "确认", "Confirm", " confirm ", "", None])
async def test_ambiguous_confirmation_rejected(hitl_env, decision):
    with pytest.raises(ValidationError):
        ResumeRequest(operation_id=uuid4(), decision=decision)
    assert await counts(hitl_env) == ("pending_payment", 0, 0)


@pytest.mark.parametrize("kind", [CANCEL, REFUND])
@pytest.mark.parametrize("field", ["actor_id", "permissions", "operation_id", "thread_id", "sql"])
async def test_model_cannot_supply_trusted_fields(hitl_env, kind, field):
    row = await hitl_env.start(kind, arguments={**hitl_env.args(kind), field: str(uuid4())})
    assert row.operation_id is None
    assert row.result["evidence"][0]["result"]["status"] == "invalid_argument"


async def test_unregistered_write_tool_rejected(hitl_env):
    row = await hitl_env.start("insert_refund", arguments={})
    assert row.operation_id is None and row.result["kind"] == "reject"


@pytest.mark.parametrize("kind", [CANCEL, REFUND])
async def test_audit_failure_rolls_back_business_and_can_retry(hitl_env, monkeypatch, kind):
    env = hitl_env
    row = await env.start(kind)
    original = operations.append_audit

    async def fail(*args):
        raise OperationalError("fixture", {}, Exception("private-database-error"))

    monkeypatch.setattr(operations, "append_audit", fail)
    with pytest.raises(OperationalError):
        await env.resume(row)
    assert await counts(env) == ("pending_payment", 0, 0)
    assert (await get_workflow(row.thread_id, context=env.context())).status == "waiting_for_confirmation"
    monkeypatch.setattr(operations, "append_audit", original)
    assert (await env.resume(row)).status == "succeeded"
    assert await counts(env) == ("cancelled" if kind == CANCEL else "pending_payment", int(kind == REFUND), 1)


async def test_business_failure_records_failed_without_partial_rows(hitl_env):
    env = hitl_env
    row = await env.start(REFUND)

    def break_refund(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO refunds"):
            raise IntegrityError("fixture", {}, Exception("private-error"))

    event.listen(env.engine.sync_engine, "before_cursor_execute", break_refund)
    try:
        done = await env.resume(row)
    finally:
        event.remove(env.engine.sync_engine, "before_cursor_execute", break_refund)
    assert done.status == "failed"
    assert await counts(env) == ("pending_payment", 0, 1)
    assert "private-error" not in done.model_dump_json()


async def test_business_commit_before_checkpoint_failure_is_idempotent(hitl_env, monkeypatch):
    from app.agent.checkpoint import PostgresCheckpointer
    env = hitl_env
    row = await env.start(REFUND)
    original = PostgresCheckpointer.aput

    async def fail_after_commit(self, config, checkpoint, metadata, versions):
        if checkpoint["channel_values"].get("operation_result"):
            raise RuntimeError("simulated process exit after business commit")
        return await original(self, config, checkpoint, metadata, versions)

    monkeypatch.setattr(PostgresCheckpointer, "aput", fail_after_commit)
    with pytest.raises(RuntimeError):
        await env.resume(row)
    monkeypatch.setattr(PostgresCheckpointer, "aput", original)
    done = await env.resume(row)
    assert done.status == "succeeded" and (await counts(env))[1:] == (1, 1)


async def test_start_http_retry_preserves_identity(hitl_env):
    key = uuid4()
    a, b = await asyncio.gather(hitl_env.start(request_key=key), hitl_env.start(request_key=key))
    assert a == b
    with pytest.raises(OperationError, match="request_key_reused"):
        await start_workflow(StartRequest(request_key=key, message="different"), context=hitl_env.context())


async def test_business_row_lock_idempotency_without_graph_lock(hitl_env):
    env = hitl_env
    row = await env.start(REFUND)
    async with env.sessions() as session, session.begin():
        await session.execute(update(AgentWorkflow).where(AgentWorkflow.id == row.thread_id).values(confirmation="confirm"))

    async def execute():
        async with env.sessions() as session, session.begin():
            return await finish_operation(session, env.context().request, thread_id=row.thread_id,
                                          operation_id=row.operation_id, decision="confirm")

    a, b = await asyncio.gather(execute(), execute())
    assert a == b and (await counts(env))[1:] == (1, 1)


async def test_api_restart_and_security(hitl_env, fake_model):
    env = hitl_env
    app = create_app(env.settings)
    key = str(uuid4())
    async with app.router.lifespan_context(app):
        app.state.agent_model = fake_model([(REFUND, env.args(REFUND))])
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            assert (await client.post("/agent/requests", json={"request_key": key, "message": "退款"}, headers={"actor_id": str(env.users[0])})).status_code == 401
            app.dependency_overrides[get_request_context] = lambda: env.context().request
            started = await client.post("/agent/requests", json={"request_key": key, "message": "退款"})
            assert started.status_code == 200
            row = started.json()
    del app
    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        app.state.agent_model = fake_model()
        app.dependency_overrides[get_request_context] = lambda: env.context().request
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            path = f'/agent/threads/{row["thread_id"]}'
            assert (await client.get(path)).json()["status"] == "waiting_for_confirmation"
            assert (await client.post(path + "/resume", json={"operation_id": row["operation_id"], "decision": "yes"})).status_code == 422
            assert (await client.post(path + "/resume", json={"operation_id": row["operation_id"], "decision": "confirm", "actor_id": str(env.users[0])})).status_code == 422
            done = await client.post(path + "/resume", json={"operation_id": row["operation_id"], "decision": "confirm"})
            assert done.status_code == 200 and done.json()["status"] == "succeeded"
            app.dependency_overrides[get_request_context] = lambda: env.context(actor=env.users[1]).request
            assert (await client.get(path)).status_code == 403
    assert (await counts(env))[1:] == (1, 1)


@pytest.mark.parametrize("question", ["order", "order_item", "quantity", "amount", "reason"])
async def test_missing_write_parameters_clarify(hitl_env, fake_model, question):
    env = hitl_env
    row = await start_workflow(StartRequest(request_key=uuid4(), message="我要退这个商品"),
                               context=env.context(fake_model({"action": "clarify", "question": question})))
    assert row.result["kind"] == "clarify" and row.result["question"] == question
    assert row.operation_id is None and await counts(env) == ("pending_payment", 0, 0)


async def test_disabled_actor_and_dev_identity(hitl_env, fake_model):
    env = hitl_env
    app = create_app(env.settings.model_copy(update={"dev_actor_id": env.users[0]}))
    async with app.router.lifespan_context(app):
        app.state.agent_model = fake_model([(CANCEL, env.args())])
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            created = await client.post("/agent/requests", json={"request_key": str(uuid4()), "message": "cancel"},
                                        headers={"actor_id": str(env.users[1]), "permissions": "*"})
            assert created.status_code == 200 and created.json()["draft"]["actor"] == str(env.users[0])
            async with env.sessions() as session, session.begin():
                await session.execute(update(User).where(User.id == env.users[0]).values(status="disabled"))
            assert (await client.get('/agent/threads/' + created.json()["thread_id"])).status_code == 403


async def test_schema_unique_operation_and_request_key(hitl_env):
    env = hitl_env
    row = await env.start()
    async with env.sessions() as session, session.begin():
        existing = await session.get(AgentWorkflow, row.thread_id)
        for duplicate in ({"operation_id": existing.operation_id, "draft": existing.draft, "request_key": uuid4()},
                          {"request_key": existing.request_key}):
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    session.add(AgentWorkflow(actor_id=env.users[0], request_id=uuid4(), input_hash="x" * 64,
                                              status="running", **duplicate))
                    await session.flush()


async def test_checkpoint_operation_binding(hitl_env):
    from app.agent.graph import build_graph
    env = hitl_env
    row = await env.start()
    async with checkpoint_session(env.settings.database_url.get_secret_value(), row.thread_id) as saver:
        graph = build_graph(checkpointer=saver)
        config = {"configurable": {"thread_id": str(row.thread_id)}}
        await graph.aupdate_state(config, {"draft": {**row.draft.model_dump(mode="json"), "operation_id": str(uuid4())}})
    with pytest.raises(OperationError, match="checkpoint_not_waiting"):
        await env.resume(row)
    assert await counts(env) == ("pending_payment", 0, 0)


@pytest.mark.parametrize("tool", ["get_order", "get_logistics"])
@pytest.mark.parametrize("permissions", [frozenset(), frozenset({"orders:read:self"})])
@pytest.mark.parametrize("entry", ["get", "request_key"])
async def test_replay_authorization_revocation(hitl_env, fake_model, tool, permissions, entry):
    env = hitl_env
    async with env.sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == env.users[1]).values(role="operator"))
        session.add(Logistics(order_id=env.orders[0], carrier_code="private-carrier", tracking_no=str(uuid4()),
                              latest_event="protected-logistics-evidence"))
    request = StartRequest(request_key=uuid4(), message="查询订单和物流")
    model = fake_model([(tool, {"order_no": env.args()["order_no"]})], {"action": "answer", "evidence_ids": [1]})
    row = await start_workflow(request, context=env.context(model, actor=env.users[1], permissions=frozenset({"orders:read:any"})))
    assert row.status == "completed" and row.draft is None and row.result["evidence"]
    assert row.result["evidence"][0]["result"]["status"] == "success"
    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        # Empty Fake forbids LLM calls on both rejected and restored replays.
        app.state.agent_model = fake_model()
        app.dependency_overrides[get_request_context] = lambda: env.context(actor=env.users[1], permissions=permissions).request
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            async def replay():
                if entry == "get":
                    return await client.get(f"/agent/threads/{row.thread_id}")
                return await client.post("/agent/requests", json=request.model_dump(mode="json"))
            denied = await replay()
            assert denied.status_code == 403
            assert denied.json() == {"detail": "not_accessible"}
            assert str(env.orders[0]) not in denied.text and "protected-logistics-evidence" not in denied.text
            app.dependency_overrides[get_request_context] = lambda: env.context(actor=env.users[1], permissions=frozenset({"orders:read:any"})).request
            restored = await replay()
            assert restored.status_code == 200 and restored.json()["result"] == row.result
        assert not app.state.agent_model.requests


@pytest.mark.parametrize("tool", ["get_order", "get_logistics", "search_products"])
async def test_replay_authorization_own_order_and_public_data(hitl_env, fake_model, tool):
    env = hitl_env
    async with env.sessions() as session, session.begin():
        await session.execute(update(Product).where(Product.id == env.product_id).values(status="active"))
    params = {"query": "HITL item"} if tool == "search_products" else {"order_no": env.args()["order_no"]}
    request = StartRequest(request_key=uuid4(), message="查询")
    model = fake_model([(tool, params)], {"action": "answer", "evidence_ids": [1]})
    context = env.context(model, permissions=frozenset() if tool == "search_products" else frozenset({"orders:read:self"}))
    row = await start_workflow(request, context=context)
    assert row.result["evidence"][0]["result"]["status"] == "success"
    for replay in (await get_workflow(row.thread_id, context=context), await start_workflow(request, context=context)):
        assert replay.result == row.result
    assert len(model.requests) == 2


async def test_replay_authorization_uses_current_order_owner(hitl_env, fake_model):
    env = hitl_env
    row = await start_workflow(StartRequest(request_key=uuid4(), message="我的订单"), context=env.context(
        fake_model([("get_order", {"order_no": env.args()["order_no"]})], {"action": "answer", "evidence_ids": [1]})))
    async with env.sessions() as session, session.begin():
        await session.execute(update(Order).where(Order.id == env.orders[0]).values(user_id=env.users[1]))
    with pytest.raises(OperationError, match="not_accessible"):
        await get_workflow(row.thread_id, context=env.context())


@pytest_asyncio.fixture
async def refund_order(hitl_env):
    """Two distinct items on the same paid order; all rows remain fixture-owned."""
    env = hitl_env
    async with env.sessions() as session, session.begin():
        await session.execute(update(OrderItem).where(OrderItem.id == env.items[0]).values(order_id=env.orders[1], line_no=2))
        await session.execute(update(OrderItem).where(OrderItem.id.in_(env.items)).values(quantity=4, line_amount=Decimal("40")))
        await session.execute(update(Order).where(Order.id == env.orders[1]).values(
            subtotal_amount=Decimal("80"), payable_amount=Decimal("80"), paid_amount=Decimal("80")))
    return env


async def add_refund_history(env, rows):
    async with env.sessions() as session, session.begin():
        for item_index, status, quantity, amount in rows:
            session.add(Refund(refund_no=str(uuid4()), order_item_id=env.items[item_index], requested_by=env.users[0],
                               status=status, quantity=quantity, amount=Decimal(amount), reason="historical fixture",
                               requested_at=datetime.now(UTC)))


async def unallocated_order_discount(env, payable):
    # Deliberate legacy inconsistency: header discount not allocated to items. Current DB permits it.
    # Without this, fully-paid orders whose item totals reconcile cannot hit the independent order cap.
    async with env.sessions() as session, session.begin():
        await session.execute(update(Order).where(Order.id == env.orders[1]).values(
            discount_amount=Decimal("80") - Decimal(payable), payable_amount=Decimal(payable), paid_amount=Decimal(payable)))


@pytest.mark.parametrize(("status", "consumes"), [
    ("requested", True), ("approved", True), ("processing", True), ("succeeded", True),
    ("rejected", False), ("failed", False), ("cancelled", False),
])
async def test_refund_history_status_aggregation(refund_order, status, consumes):
    env = refund_order
    await add_refund_history(env, [(1, status, 1, "10"), (1, status, 1, "10")])
    remaining_quantity, remaining_amount = (2, Decimal("20")) if consumes else (4, Decimal("40"))
    row = await env.start(REFUND, arguments=env.args(REFUND, quantity=remaining_quantity, amount=str(remaining_amount)))
    assert row.status == "waiting_for_confirmation"
    state = row.draft.current_state
    assert state["remaining_quantity"] == remaining_quantity
    assert Decimal(state["remaining_amount"]) == remaining_amount
    assert Decimal(state["order_remaining_amount"]) == (Decimal("60") if consumes else Decimal("80"))
    for params, code in [
        ({"quantity": remaining_quantity + 1, "amount": "1"}, "refund_quantity_exceeded"),
        ({"quantity": remaining_quantity, "amount": str(remaining_amount + Decimal("0.01"))}, "refund_amount_exceeded"),
    ]:
        denied = await env.start(REFUND, arguments=env.args(REFUND, **params))
        assert denied.operation_id is None and denied.result["evidence"][0]["result"]["error"]["code"] == code
    assert (await env.resume(row)).status == "succeeded"


async def test_refund_history_mixed_status_aggregation(refund_order):
    env = refund_order
    async with env.sessions() as session, session.begin():
        await session.execute(update(OrderItem).where(OrderItem.id == env.items[1]).values(quantity=8, line_amount=Decimal("80")))
        await session.execute(update(Order).where(Order.id == env.orders[1]).values(
            subtotal_amount=Decimal("120"), payable_amount=Decimal("120"), paid_amount=Decimal("120")))
    await add_refund_history(env, [(1, "requested", 1, "6"), (1, "approved", 1, "7"),
        (1, "processing", 1, "8"), (1, "succeeded", 1, "9"), (1, "rejected", 4, "40"),
        (1, "failed", 4, "40"), (1, "cancelled", 4, "40"), (0, "requested", 1, "5")])
    row = await env.start(REFUND, arguments=env.args(REFUND, quantity=4, amount="40"))
    assert row.status == "waiting_for_confirmation"
    assert row.draft.current_state["remaining_quantity"] == 4
    assert Decimal(row.draft.current_state["remaining_amount"]) == Decimal("50")
    assert Decimal(row.draft.current_state["order_remaining_amount"]) == Decimal("85")
    denied = await env.start(REFUND, arguments=env.args(REFUND, quantity=5, amount="1"))
    assert denied.result["evidence"][0]["result"]["error"]["code"] == "refund_quantity_exceeded"
    assert (await env.resume(row)).status == "succeeded"


async def test_refund_whole_order_cap_below_item_remainder(refund_order):
    env = refund_order
    await unallocated_order_discount(env, "50")
    await add_refund_history(env, [(0, "requested", 1, "10"), (0, "approved", 1, "10")])
    # Target item still has 4 units/40 CNY, but sibling reservations leave only 30 CNY on the order.
    for amount in ("30.01", "40.00"):
        denied = await env.start(REFUND, arguments=env.args(REFUND, quantity=4, amount=amount))
        assert denied.operation_id is None
        assert denied.result["evidence"][0]["result"]["error"]["code"] == "refund_amount_exceeded"
    allowed = await env.start(REFUND, arguments=env.args(REFUND, quantity=3, amount="30"))
    assert Decimal(allowed.draft.current_state["remaining_amount"]) == Decimal("40")
    assert Decimal(allowed.draft.current_state["order_remaining_amount"]) == Decimal("30")
    assert (await env.resume(allowed)).status == "succeeded"
    async with env.sessions() as session:
        assert await session.scalar(select(func.sum(Refund.amount)).where(Refund.order_item_id.in_(env.items))) == Decimal("50")


async def test_same_order_different_item_refund_race(refund_order, monkeypatch):
    env = refund_order
    await unallocated_order_discount(env, "30")
    a = await env.start(REFUND, arguments=env.args(REFUND, order_item_id=str(env.items[0]), quantity=2, amount="20"))
    b = await env.start(REFUND, arguments=env.args(REFUND, order_item_id=str(env.items[1]), quantity=2, amount="20"))
    assert a.operation_id != b.operation_id and a.thread_id != b.thread_id
    assert a.draft.target["order_item_id"] != b.draft.target["order_item_id"]
    assert a.draft.current_state["order_remaining_amount"] == b.draft.current_state["order_remaining_amount"] == "30.00"
    async with env.sessions() as session, session.begin():
        await session.execute(update(AgentWorkflow).where(AgentWorkflow.id.in_([a.thread_id, b.thread_id])).values(confirmation="confirm"))

    barrier, release = asyncio.Barrier(2), asyncio.Event()
    first_cap_read, cap_reads, pids = asyncio.Event(), [], []
    scalar = AsyncSession.scalar

    async def pause_after_order_cap_read(session, statement, *args, **kwargs):
        value = await scalar(session, statement, *args, **kwargs)
        sql = str(statement)
        if "sum(refunds.amount)" in sql and "JOIN order_items" in sql:
            cap_reads.append(value)
            first_cap_read.set()
            await release.wait()
        return value

    monkeypatch.setattr(AsyncSession, "scalar", pause_after_order_cap_read)

    async def execute(row):
        async with env.sessions() as session, session.begin():
            pids.append(await session.scalar(text("SELECT pg_backend_pid()")))
            await barrier.wait()
            # Distinct workflows; deliberately bypass graph/advisory locks to isolate business row locking.
            return await finish_operation(session, env.context().request, thread_id=row.thread_id,
                                          operation_id=row.operation_id, decision="confirm")

    tasks = [asyncio.create_task(execute(row)) for row in (a, b)]
    observed_block = False
    try:
        async with asyncio.timeout(2):
            await first_cap_read.wait()
            async with env.sessions() as probe:
                while len(cap_reads) < 2:
                    blockers = await probe.scalar(text(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE pid IN (:a,:b) "
                        "AND pg_blocking_pids(pid) && ARRAY[:a,:b]::int[])"), {"a": pids[0], "b": pids[1]})
                    if blockers:
                        observed_block = True
                        break
                    await asyncio.sleep(0.01)
        release.set()
        results = await asyncio.gather(*tasks)
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    async with env.sessions() as session:
        total = await session.scalar(select(func.sum(Refund.amount)).where(Refund.order_item_id.in_(env.items)))
        assert total <= Decimal("30"), "whole-order refund cap exceeded"
        assert await session.scalar(select(func.count()).select_from(Refund).where(Refund.order_item_id.in_(env.items))) == 1
    assert observed_block, "second transaction must contend on the parent order, not an item/advisory lock"
    assert sorted(result["status"] for result in results) == ["conflict", "succeeded"]
