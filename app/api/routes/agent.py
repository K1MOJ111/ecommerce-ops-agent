from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg import Error as CheckpointError
from sqlalchemy.exc import SQLAlchemyError

from app.agent.graph import AgentContext
from app.api.dependencies import get_request_context
from app.core.security import RequestContext
from app.schemas.operations import ResumeRequest, StartRequest, WorkflowResponse
from app.services.operations import OperationError
from app.services.workflows import get_workflow, resume_workflow, start_workflow

router = APIRouter(prefix="/agent", tags=["agent"])


async def agent_context(request: Request, actor: Annotated[RequestContext, Depends(get_request_context)]) -> AgentContext:
    return AgentContext(actor, request.app.state.agent_model, request.app.state.session_factory,
                        request.app.state.settings)


async def _call(awaitable):
    try:
        return await awaitable
    except OperationError as exc:
        raise HTTPException(exc.http_status, exc.code) from None
    except (SQLAlchemyError, CheckpointError):
        raise HTTPException(503, "workflow_storage_unavailable") from None


@router.post("/requests", response_model=WorkflowResponse)
async def start(body: StartRequest, context: Annotated[AgentContext, Depends(agent_context)]):
    return await _call(start_workflow(body, context=context))


@router.get("/threads/{thread_id}", response_model=WorkflowResponse)
async def get(thread_id: UUID, context: Annotated[AgentContext, Depends(agent_context)]):
    return await _call(get_workflow(thread_id, context=context))


@router.post("/threads/{thread_id}/resume", response_model=WorkflowResponse)
async def resume(thread_id: UUID, body: ResumeRequest, context: Annotated[AgentContext, Depends(agent_context)]):
    return await _call(resume_workflow(thread_id, body, context=context))
