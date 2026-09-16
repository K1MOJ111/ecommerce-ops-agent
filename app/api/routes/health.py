import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_request_context
from app.core.security import RequestContext
from app.db.models import User
from app.db.session import check_database

router = APIRouter()


class HealthResponse(BaseModel):
    api: Literal["ok"] = "ok"
    database: Literal["ok", "unavailable"]


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"api": "ok"}


@router.get("/health", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
async def health(
    response: Response, session: Annotated[AsyncSession, Depends(get_db_session)],
) -> HealthResponse:
    try:
        async with asyncio.timeout(3):
            await check_database(session)
    except (SQLAlchemyError, OSError, TimeoutError):
        response.status_code = 503
        return HealthResponse(database="unavailable")
    return HealthResponse(database="ok")


@router.get("/status")
async def status(
    request: Request, response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> dict:
    settings = request.app.state.settings
    try:
        async with asyncio.timeout(3):
            user = await session.get(User, context.actor_id)
    except (SQLAlchemyError, OSError, TimeoutError):
        raise HTTPException(503, "status_unavailable") from None
    if user is None or user.status != "active":
        raise HTTPException(403, "not_accessible")
    response.headers["Cache-Control"] = "no-store"

    def provider(kind):
        mode = getattr(settings, f"{kind}_provider")
        prefix = "llm" if kind == "agent" else kind
        key = getattr(settings, f"{prefix}_api_key")
        configured = (getattr(settings, f"{prefix}_base_url") and getattr(settings, f"{prefix}_model")
                      and key and key.get_secret_value().strip())
        return "fake" if mode == "fake" else "configured" if configured else "not_configured"

    return {"api": "ok", "database": "ok", "agent_provider": provider("agent"),
            "embedding_provider": provider("embedding"),
            "user": {"id": str(user.id), "display_name": user.display_name}}
