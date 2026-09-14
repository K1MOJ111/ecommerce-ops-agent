from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import RequestContext


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session


async def get_request_context(request: Request) -> RequestContext:
    # No client header/body or model output may fill this authentication boundary.
    settings = getattr(request.app.state, "settings", None)
    if settings and settings.app_env in {"development", "test"} and settings.dev_actor_id:
        return RequestContext(settings.dev_actor_id, frozenset({"orders:read:self", "orders:cancel:self", "refunds:request:self"}), uuid4())
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication is not configured")
