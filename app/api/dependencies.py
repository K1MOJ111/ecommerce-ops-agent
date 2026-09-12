from collections.abc import AsyncIterator

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import RequestContext


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session


async def get_request_context() -> RequestContext:
    # No client header/body or model output may fill this authentication boundary.
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication is not configured")
