import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.session import create_db_engine

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def test_database_url() -> str:
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated PostgreSQL database ending in _test")
    url = make_url(value)
    if url.drivername != "postgresql+asyncpg" or not (url.database or "").endswith("_test"):
        pytest.fail("Integration tests require postgresql+asyncpg and a database ending in _test")
    return value


@pytest.fixture(scope="session")
def migrated_database(test_database_url: str) -> str:
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DATABASE_URL", test_database_url)
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    return test_database_url


@pytest_asyncio.fixture
async def db_engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    engine = create_db_engine(migrated_database)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            async with AsyncSession(
                bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint",
            ) as session:
                yield session
        finally:
            await transaction.rollback()
