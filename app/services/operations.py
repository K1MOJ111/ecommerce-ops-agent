"""Fixed business actions. No model, checkpoint, or caller-owned transaction state."""
from datetime import UTC, datetime
from decimal import Decimal, ROUND_DOWN
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import RequestContext
from app.db.models import AgentWorkflow, AuditLog, Logistics, Order, OrderItem, Refund, User
from app.db.models.commerce import UserStatus
from app.schemas.operations import CancellationInput, OperationDraft, RefundRequestInput

PERMISSIONS = {"request_order_cancellation": "orders:cancel:self", "create_refund_request": "refunds:request:self"}
INPUTS = {"request_order_cancellation": CancellationInput, "create_refund_request": RefundRequestInput}
RESERVED_REFUNDS = ("requested", "approved", "processing", "succeeded")
TERMINAL = {"completed", "succeeded", "rejected", "conflict", "failed"}


class OperationError(Exception):
    def __init__(self, code: str, http_status: int = 409):
        self.code, self.http_status = code, http_status
        super().__init__(code)


async def verify_actor(session: AsyncSession, context: RequestContext) -> None:
    if not isinstance(context, RequestContext):
        raise TypeError("server_request_context_required")
    if await session.scalar(select(User.id).where(User.id == context.actor_id, User.status == UserStatus.ACTIVE)) is None:
        raise OperationError("not_accessible", 403)


async def owned_workflow(session: AsyncSession, context: RequestContext, thread_id: UUID, *, lock=False) -> AgentWorkflow:
    await verify_actor(session, context)
    query = select(AgentWorkflow).where(AgentWorkflow.id == thread_id, AgentWorkflow.actor_id == context.actor_id)
    if lock:
        query = query.with_for_update()
    workflow = await session.scalar(query.execution_options(populate_existing=True))
    if workflow is None:
        raise OperationError("not_accessible", 403)
    if workflow.draft and PERMISSIONS[workflow.draft["operation_type"]] not in context.permissions:
        raise OperationError("not_accessible", 403)
    return workflow


async def _inspect(session: AsyncSession, context: RequestContext, operation_type: str, params):
    await verify_actor(session, context)
    if PERMISSIONS[operation_type] not in context.permissions:
        raise OperationError("not_accessible", 403)
    # All writers take the parent order lock first, including refunds on different items.
    order = await session.scalar(select(Order).where(
        Order.order_no == params.order_no, Order.user_id == context.actor_id,
    ).with_for_update().execution_options(populate_existing=True))
    if order is None:
        raise OperationError("not_accessible", 403)
    state = {"order_status": order.status, "payment_status": order.payment_status,
             "order_updated_at": order.updated_at.isoformat(), "paid_amount": str(order.paid_amount),
             "payable_amount": str(order.payable_amount), "currency": order.currency}
    item = None
    if operation_type == "request_order_cancellation":
        # Paid cancellation needs reservation ownership/release and refund coordination, absent in this schema.
        if order.status != "pending_payment" or order.payment_status != "unpaid" or order.paid_amount != 0:
            raise OperationError("cancellation_not_allowed")
        if await session.scalar(select(Logistics.id).where(Logistics.order_id == order.id).limit(1)):
            raise OperationError("fulfillment_already_exists")
        if await session.scalar(select(Refund.id).join(OrderItem).where(OrderItem.order_id == order.id).limit(1)):
            raise OperationError("refund_already_exists")
    else:
        if (order.status not in {"pending_fulfillment", "partially_shipped", "shipped", "completed"}
                or order.payment_status not in {"paid", "partially_refunded"}
                or order.paid_amount <= 0 or order.paid_amount != order.payable_amount):
            raise OperationError("refund_not_allowed")
        item = await session.scalar(select(OrderItem).where(
            OrderItem.id == params.order_item_id, OrderItem.order_id == order.id,
        ).with_for_update().execution_options(populate_existing=True))
        if item is None:
            raise OperationError("not_accessible", 403)
        used_quantity, used_amount = (await session.execute(select(
            func.coalesce(func.sum(Refund.quantity), 0), func.coalesce(func.sum(Refund.amount), 0),
        ).where(Refund.order_item_id == item.id, Refund.status.in_(RESERVED_REFUNDS)))).one()
        order_used = await session.scalar(select(func.coalesce(func.sum(Refund.amount), 0)).join(
            OrderItem, OrderItem.id == Refund.order_item_id,
        ).where(OrderItem.order_id == order.id, Refund.status.in_(RESERVED_REFUNDS)))
        remaining_quantity = item.quantity - used_quantity
        remaining_amount = item.line_amount - used_amount
        quantity_cap = (item.line_amount * params.quantity / item.quantity).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if params.quantity > remaining_quantity:
            raise OperationError("refund_quantity_exceeded")
        if params.amount > min(remaining_amount, quantity_cap, order.paid_amount - order_used):
            raise OperationError("refund_amount_exceeded")
        state.update(item_updated_at=item.updated_at.isoformat(), purchased_quantity=item.quantity,
                     line_amount=str(item.line_amount), remaining_quantity=remaining_quantity,
                     remaining_amount=str(remaining_amount), quantity_amount_cap=str(quantity_cap),
                     order_remaining_amount=str(order.paid_amount - order_used))
    return order, item, state


async def create_draft(session: AsyncSession, context: RequestContext, *, thread_id: UUID,
                       operation_type: str, arguments: dict) -> OperationDraft:
    if operation_type not in INPUTS:
        raise OperationError("unknown_tool", 422)
    params = INPUTS[operation_type].model_validate(arguments)
    workflow = await owned_workflow(session, context, thread_id, lock=True)
    normalized = params.model_dump(mode="json")
    if workflow.draft:
        draft = OperationDraft.model_validate(workflow.draft)
        if draft.operation_type != operation_type or draft.parameters != normalized:
            raise OperationError("one_operation_per_workflow")
        return draft
    if workflow.status != "running":
        raise OperationError("workflow_not_running")
    order, item, state = await _inspect(session, context, operation_type, params)
    operation_id = uuid4()
    target = {"order_id": str(order.id), "order_no": order.order_no}
    if item:
        target["order_item_id"] = str(item.id)
    expected = {"order_status": "cancelled"} if item is None else {
        "refund_status": "requested", "quantity": params.quantity, "amount": str(params.amount),
        "currency": order.currency, "payment_status_unchanged": True,
    }
    summary = (f"取消未付款订单 {order.order_no}；当前状态 {order.status}。"
               if item is None else f"为订单 {order.order_no} 的明细 {item.id} 创建退款申请，数量 {params.quantity}，金额 {params.amount} CNY；当前状态 {order.status}。仅申请，不审批或打款。")
    draft = OperationDraft(operation_id=operation_id, operation_type=operation_type, actor=context.actor_id,
                           target=target, parameters=normalized, current_state=state,
                           expected_change=expected, confirmation_summary=summary + "请显式 confirm 或 reject。")
    workflow.operation_id, workflow.draft = operation_id, draft.model_dump(mode="json")
    await session.flush()
    return draft


async def append_audit(session: AsyncSession, workflow: AgentWorkflow, context: RequestContext, result: dict) -> None:
    draft = workflow.draft
    # No free-form reason, user message, addresses, credentials or exception text in Audit.
    session.add(AuditLog(actor_id=context.actor_id, request_id=context.request_id,
                         action=draft["operation_type"], resource_type="order_item" if "order_item_id" in draft["target"] else "order",
                         resource_id=UUID(draft["target"].get("order_item_id", draft["target"]["order_id"])),
                         result=result["status"], details={"operation_id": str(workflow.operation_id),
                         "thread_id": str(workflow.id), "initial_request_id": str(workflow.request_id),
                         "code": result["code"], "change": draft["expected_change"] if result["status"] == "succeeded" else {}}))
    await session.flush()


async def finish_operation(session: AsyncSession, context: RequestContext, *, thread_id: UUID,
                           operation_id: UUID, decision: str) -> dict:
    """Caller opens one transaction; row lock and receipt serialize duplicate execution."""
    workflow = await owned_workflow(session, context, thread_id, lock=True)
    if workflow.operation_id != operation_id:
        raise OperationError("operation_mismatch")
    if decision not in {"confirm", "reject"} or workflow.confirmation != decision:
        raise OperationError("confirmation_mismatch")
    if workflow.status in TERMINAL:
        return workflow.result
    if workflow.status != "waiting_for_confirmation":
        raise OperationError("not_waiting_for_confirmation")
    draft = OperationDraft.model_validate(workflow.draft)
    if draft.actor != context.actor_id or draft.operation_id != operation_id:
        raise OperationError("operation_mismatch")
    result = {"status": "rejected", "code": "user_rejected", "operation_id": str(operation_id)}
    if decision == "confirm":
        try:
            async with session.begin_nested():
                params = INPUTS[draft.operation_type].model_validate(draft.parameters)
                order, item, current = await _inspect(session, context, draft.operation_type, params)
                if current != draft.current_state or str(order.id) != draft.target["order_id"]:
                    raise OperationError("business_state_changed")
                result = {"status": "succeeded", "code": "order_cancelled" if item is None else "refund_request_created",
                          "operation_id": str(operation_id), "order_id": str(order.id)}
                if item is None:
                    order.status, order.cancelled_at = "cancelled", datetime.now(UTC)
                else:
                    # Existing refund_no UNIQUE is a second DB fence; operation identity is never model supplied.
                    refund = Refund(refund_no=f"OP-{operation_id}", order_item_id=item.id,
                                    requested_by=context.actor_id, quantity=params.quantity, amount=params.amount,
                                    reason=params.reason, status="requested", requested_at=datetime.now(UTC))
                    session.add(refund)
                    await session.flush()
                    result.update(refund_id=str(refund.id), refund_status="requested", quantity=params.quantity,
                                  amount=str(params.amount), currency=order.currency)
                await session.flush()
        except OperationError as exc:
            result = {"status": "conflict", "code": exc.code, "operation_id": str(operation_id)}
        except SQLAlchemyError:
            result = {"status": "failed", "code": "business_write_failed", "operation_id": str(operation_id)}
    # Audit failure rolls back the entire transaction, including business changes and receipt.
    await append_audit(session, workflow, context, result)
    workflow.status, workflow.result = result["status"], result
    await session.flush()
    return result
