"""Clarification uses real persisted workflows and current authorization, for either provider."""
import asyncio
import json
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from app.agent.development import DevelopmentModel
from app.agent.llm import OpenAICompatibleModel
from app.schemas.operations import StartRequest
from app.services.operations import OperationError
from app.services.workflows import get_workflow, start_workflow
from scripts.eval_support import workflow_fixture, counts

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def env(migrated_database, fake_model):
    async with workflow_fixture(migrated_database, fake_model) as value:
        yield value


async def send(env, message, parent=None, **kwargs):
    request = StartRequest(request_key=kwargs.pop("key", uuid4()), message=message,
                           clarification_thread_id=parent.thread_id if parent else None)
    return await start_workflow(request, context=env.context(DevelopmentModel(), **kwargs))


@pytest.mark.parametrize("message,source", [("查询订单", "get_order"), ("查询物流", "get_logistics")])
async def test_read_clarify_invalid_reload_and_supplement(env, message, source):
    first = await send(env, message)
    assert first.result["question"] == "order"
    invalid = await send(env, "SEED O001!", first)
    assert invalid.result["question"] == "order" and "格式错误" in invalid.result["text"]
    restored = await get_workflow(invalid.thread_id, context=env.context())
    last = await send(env, env.args()["order_no"], restored)
    assert last.result["kind"] == "answer"
    assert last.result["evidence"][0]["result"]["source"] == source
    assert last.result["evidence"][0]["result"]["status"] == "success"
    assert await counts(env) == ("pending_payment", 0, 0)


async def test_cancellation_keeps_reason_requirement_then_hitl(env):
    first = await send(env, "帮我取消这个订单")
    second = await send(env, env.args()["order_no"], first)
    assert second.result["question"] == "reason"
    restored = await get_workflow(second.thread_id, context=env.context())
    draft = await send(env, "不需要了", restored)
    assert draft.status == "waiting_for_confirmation"
    assert draft.draft.operation_type == "request_order_cancellation"
    assert draft.draft.parameters["order_no"] == env.args()["order_no"]
    assert draft.draft.parameters["reason"] == "不需要了"
    assert await counts(env) == ("pending_payment", 0, 0)


async def test_refund_collects_explicit_order_item_quantity_amount_then_hitl(env):
    row = await send(env, "申请退款，原因 尺码不合适")
    for question, reply in [("order", env.args("create_refund_request")["order_no"]),
                            ("order_item", str(env.items[1])), ("quantity", "1"), ("amount", "10.00")]:
        row = await get_workflow(row.thread_id, context=env.context())
        assert row.result["question"] == question
        row = await send(env, reply, row)
    assert row.status == "waiting_for_confirmation"
    assert row.draft.operation_type == "create_refund_request"
    assert row.draft.parameters["order_item_id"] == str(env.items[1])
    assert row.draft.parameters["amount"] == "10.00"
    assert await counts(env) == ("pending_payment", 0, 0)


async def test_clarification_ownership_permission_and_hitl_boundaries(env):
    parent = await send(env, "帮我取消订单，原因 不需要了")
    with pytest.raises(OperationError, match="not_accessible"):
        await send(env, env.args()["order_no"], parent, actor=env.users[1])
    denied = await send(env, env.args()["order_no"], parent, permissions=frozenset())
    assert denied.operation_id is None
    assert denied.result["evidence"][0]["result"]["status"] == "forbidden"
    parent = await send(env, "帮我取消订单，原因 不需要了")
    waiting = await send(env, env.args()["order_no"], parent)
    with pytest.raises(OperationError, match="not_waiting_for_clarification"):
        await send(env, "confirm", waiting)
    assert await counts(env) == ("pending_payment", 0, 0)


async def test_duplicate_lost_response_and_concurrent_followups_are_idempotent(env):
    parent = await send(env, "帮我取消订单，原因 不需要了")
    key = uuid4()
    first, retry = await asyncio.gather(*(send(env, env.args()["order_no"], parent, key=key) for _ in range(2)))
    assert first == retry and first.status == "waiting_for_confirmation"
    with pytest.raises(OperationError, match="request_key_reused_with_different_input"):
        await send(env, "different", parent, key=key)
    with pytest.raises(OperationError, match="clarification_already_answered"):
        await send(env, env.args()["order_no"], parent)
    assert await counts(env) == ("pending_payment", 0, 0)


async def test_openai_adapter_receives_same_persisted_context_and_shared_validation(env):
    bodies = []
    def respond(request):
        body = json.loads(request.content)
        bodies.append(body)
        users = [m["content"] for m in body["messages"] if m["role"] == "user"]
        if len(users) == 1:
            message = {"role": "assistant", "content": '{"action":"clarify","question":"order"}'}
        else:
            assert users == ["帮我取消订单，原因 不需要了", "订单号：" + env.args()["order_no"]]
            message = {"role": "assistant", "tool_calls": [{"id": "cancel", "type": "function", "function": {
                "name": "request_order_cancellation", "arguments": json.dumps(env.args())}}]}
        return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls" if "tool_calls" in message else "stop", "message": message}]})
    settings = env.settings.model_copy(update={"llm_base_url": "http://provider.test/v1", "llm_model": "stub"})
    from pydantic import SecretStr
    settings.llm_api_key = SecretStr("test-only")
    model = OpenAICompatibleModel(settings, transport=httpx.MockTransport(respond))
    context = replace(env.context(model), settings=settings)
    first = await start_workflow(StartRequest(request_key=uuid4(), message="帮我取消订单，原因 不需要了"), context=context)
    invalid = await start_workflow(StartRequest(request_key=uuid4(), message="???", clarification_thread_id=first.thread_id), context=context)
    assert invalid.result["question"] == "order" and len(bodies) == 1
    result = await start_workflow(StartRequest(request_key=uuid4(), message=env.args()["order_no"], clarification_thread_id=invalid.thread_id), context=context)
    assert result.status == "waiting_for_confirmation" and len(bodies) == 2
    assert await counts(env) == ("pending_payment", 0, 0)
