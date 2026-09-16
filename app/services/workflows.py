import asyncio
from dataclasses import replace
from hashlib import sha256
from uuid import UUID, uuid4

from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.checkpoint import checkpoint_session
from app.agent.graph import AgentContext, build_graph, initial_state
from app.db.models import AgentWorkflow
from app.core.observability import observed, correlate, emit
from app.core.security import RequestContext
from app.schemas.operations import ResumeRequest, StartRequest, WorkflowResponse
from app.services.operations import OperationError, TERMINAL, owned_workflow, verify_actor
from app.services.orders import OrderNotAccessible, authorize_order_access

# Add new protected evidence sources here alongside their owning resource's authorizer.
ORDER_EVIDENCE_IDS = {"get_order": "id", "get_logistics": "order_id"}


async def response(row: AgentWorkflow, session: AsyncSession, context: RequestContext) -> WorkflowResponse:
    # Every return path, including cached request_key and terminal Resume, uses this gate.
    await verify_actor(session, context)
    order_ids = set()
    for evidence in (row.result or {}).get("evidence", []):
        result = evidence["result"]
        field = ORDER_EVIDENCE_IDS.get(result["source"])
        if field and result["status"] == "success":
            try:
                order_ids.add(UUID(result["data"][field]))
            except (KeyError, TypeError, ValueError):
                raise OperationError("not_accessible", 403) from None
    try:
        for order_id in order_ids:
            await authorize_order_access(session, context, order_id)
    except OrderNotAccessible:
        # Reject the whole payload: its rendered text also embeds the protected evidence.
        raise OperationError("not_accessible", 403) from None
    correlate(thread_id=row.id, operation_id=row.operation_id)
    return WorkflowResponse(thread_id=row.id, request_id=row.request_id, confirmation=row.confirmation,
                            status=row.status, operation_id=row.operation_id,
                            draft=row.draft, result={k: v for k, v in row.result.items() if k != "_clarification_key"} if row.result else None)


async def get_workflow(thread_id: UUID, *, context: AgentContext) -> WorkflowResponse:
    async with context.sessions() as session:
        return await response(await owned_workflow(session, context.request, thread_id), session, context.request)


@observed("request")
async def start_workflow(request: StartRequest, *, context: AgentContext) -> WorkflowResponse:
    request = StartRequest.model_validate(request)
    digest = sha256(request.message.encode()).hexdigest()
    state = None
    if request.clarification_thread_id:
        digest = sha256(f"{request.clarification_thread_id}:{request.message}".encode()).hexdigest()
    async with context.sessions() as session, session.begin():
        await verify_actor(session, context.request)
        if request.clarification_thread_id:
            parent = await owned_workflow(session, context.request, request.clarification_thread_id, lock=True)
            await response(parent, session, context.request)
            if parent.status != "completed" or parent.operation_id or (parent.result or {}).get("kind") != "clarify":
                raise OperationError("not_waiting_for_clarification")
            if parent.result.get("_clarification_key", str(request.request_key)) != str(request.request_key):
                raise OperationError("clarification_already_answered")
            async with checkpoint_session(context.settings.database_url.get_secret_value(), parent.id) as saver:
                snapshot = await build_graph(checkpointer=saver).aget_state({"configurable": {"thread_id": str(parent.id)}})
            if not snapshot.values or snapshot.next:
                raise OperationError("clarification_checkpoint_missing", 503)
            depth = snapshot.values.get("clarification_depth", 0) + 1
            history = [m for m in snapshot.values["messages"] if m["role"] == "user"
                       or (m["role"] == "assistant" and not m.get("tool_calls"))]
            if depth > 16 or sum(len(m.get("content") or "") for m in history) + len(request.message) > 30000:
                raise OperationError("clarification_limit")
            state = initial_state(request.message, writable=True)
            state["messages"] = state["messages"][:1] + history + state["messages"][1:]
            state.update(pending_question=parent.result["question"], clarification_depth=depth,
                         intent=snapshot.values.get("intent"))
            # Claim one successor under the parent row lock; retries must reuse their original key.
            parent.result = {**parent.result, "_clarification_key": str(request.request_key)}
        await session.execute(insert(AgentWorkflow).values(
            id=uuid4(), actor_id=context.request.actor_id, request_key=request.request_key,
            request_id=context.request.request_id, input_hash=digest, status="running",
        ).on_conflict_do_nothing(index_elements=["actor_id", "request_key"]))
        row = await session.scalar(select(AgentWorkflow).where(
            AgentWorkflow.actor_id == context.request.actor_id, AgentWorkflow.request_key == request.request_key,
        ))
        if row.input_hash != digest:
            raise OperationError("request_key_reused_with_different_input")
        thread_id = row.id
    return await _drive(thread_id, context=context, message=request.message, state=state)


@observed("request")
async def resume_workflow(thread_id: UUID, request: ResumeRequest, *, context: AgentContext) -> WorkflowResponse:
    request = ResumeRequest.model_validate(request)
    return await _drive(thread_id, context=context, resume=request)


async def _drive(thread_id: UUID, *, context: AgentContext, message=None, resume=None, state=None) -> WorkflowResponse:
    correlate(thread_id=thread_id)
    if resume:
        correlate(operation_id=resume.operation_id)
        emit("resume")
    # Authorize before even loading/checking checkpoints; a thread ID is never a capability.
    await get_workflow(thread_id, context=context)
    async with checkpoint_session(context.settings.database_url.get_secret_value(), thread_id) as saver:
        async with context.sessions() as session:
            row = await owned_workflow(session, context.request, thread_id)
            if resume:
                if row.operation_id != resume.operation_id:
                    raise OperationError("operation_mismatch")
                if row.confirmation and row.confirmation != resume.decision:
                    raise OperationError("confirmation_mismatch")
            if row.status in TERMINAL:
                return await response(row, session, context.request)
            if resume and row.status != "waiting_for_confirmation":
                raise OperationError("not_waiting_for_confirmation")
            if not resume and row.status == "waiting_for_confirmation":
                return await response(row, session, context.request)
        graph = build_graph(checkpointer=saver)
        config = {"configurable": {"thread_id": str(thread_id)},
                  "recursion_limit": context.settings.agent_max_graph_steps}
        snapshot = await graph.aget_state(config)
        if resume:
            retry_failed = (row.confirmation == resume.decision and len(snapshot.tasks) == 1
                            and snapshot.tasks[0].name == "confirm_operation" and bool(snapshot.tasks[0].error))
            if ((snapshot.next != ("confirm_operation",) and not retry_failed) or snapshot.values.get("draft") != row.draft
                    or any(interrupt.value != row.draft for task in snapshot.tasks for interrupt in task.interrupts)):
                raise OperationError("checkpoint_not_waiting_for_operation")
            if not row.confirmation and not any(task.interrupts for task in snapshot.tasks):
                raise OperationError("checkpoint_not_waiting_for_operation")
            # Persist the first explicit choice before graph execution. Retries cannot flip it.
            async with context.sessions() as session, session.begin():
                current = await owned_workflow(session, context.request, thread_id, lock=True)
                current.confirmation = resume.decision
            graph_input = None if retry_failed else Command(resume=resume.model_dump(mode="json"))
        else:
            graph_input = None if snapshot.values else state or initial_state(message, writable=True)
        try:
            async with asyncio.timeout(context.settings.agent_timeout_seconds):
                output = await graph.ainvoke(graph_input, config, context=replace(context, thread_id=thread_id), durability="sync")
        except (TimeoutError, GraphRecursionError) as exc:
            raise OperationError("workflow_timeout" if isinstance(exc, TimeoutError) else "graph_step_limit", 503) from None
        async with context.sessions() as session, session.begin():
            current = await owned_workflow(session, context.request, thread_id, lock=True)
            if current.status not in TERMINAL:
                if output.get("__interrupt__"):
                    if output.get("draft") != current.draft:
                        raise OperationError("operation_mismatch")
                    current.status = "waiting_for_confirmation"
                    correlate(operation_id=current.operation_id)
                    emit("interrupt", status=current.status)
                else:
                    if current.operation_id is not None:
                        raise OperationError("operation_result_missing")
                    final = output.get("final_response")
                    if final is None:
                        raise OperationError("workflow_result_missing")
                    current.status = "completed"
                    current.result = final.model_dump(mode="json")
                await session.flush()
            return await response(current, session, context.request)
