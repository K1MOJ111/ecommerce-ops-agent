from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def create_db_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(
        database_url, pool_pre_ping=True, pool_timeout=3,
        connect_args={"timeout": 3, "command_timeout": 3, "server_settings": {"timezone": "UTC"}},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_database(session: AsyncSession) -> None:
    await session.execute(text("SELECT 1"))
