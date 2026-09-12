import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
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
