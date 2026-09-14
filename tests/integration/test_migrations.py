import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url

from app.db.base import Base
from app.db import models  # noqa: F401
from app.db.session import create_db_engine

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


async def inspect_database(url: str, *, require_empty: bool = False) -> tuple[set[str], set[str], list[str]]:
    engine = create_db_engine(url)
    try:
        async with engine.connect() as connection:
            tables = set(await connection.run_sync(lambda conn: inspect(conn).get_table_names()))
            assert not tables - (set(Base.metadata.tables) | {"alembic_version"}), "Unexpected tables; refusing downgrade"
            if require_empty:
                for table in Base.metadata.sorted_tables:
                    if table.name in tables:
                        assert await connection.scalar(select(func.count()).select_from(table)) == 0, "Database has rows; refusing downgrade"
            extensions = set((await connection.scalars(text("SELECT extname FROM pg_extension"))).all())
            definitions = list((await connection.scalars(text(
                "SELECT conrelid::regclass::text || ':' || conname || ':' || pg_get_constraintdef(oid) "
                "FROM pg_constraint WHERE connamespace='public'::regnamespace "
                "UNION ALL SELECT tablename || ':' || indexdef FROM pg_indexes WHERE schemaname='public' "
                "ORDER BY 1"
            ))).all())
            return tables, extensions, definitions
    finally:
        await engine.dispose()


def test_migration_round_trip() -> None:
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        pytest.skip("Set MIGRATION_DATABASE_URL to an empty dedicated *_migration_test database")
    parsed = make_url(url)
    assert parsed.drivername == "postgresql+asyncpg" and (parsed.database or "").endswith("_migration_test")
    environment = {**os.environ, "DATABASE_URL": url}

    def alembic(*args: str) -> str:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args], cwd=ROOT,
            env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout + result.stderr

    asyncio.run(inspect_database(url, require_empty=True))
    alembic("upgrade", "head")
    before = asyncio.run(inspect_database(url, require_empty=True))
    alembic("downgrade", "base")
    tables, extensions, definitions = asyncio.run(inspect_database(url))
    assert tables == {"alembic_version"}
    assert extensions == before[1]  # Shared extensions intentionally survive revision rollback.
    assert len(definitions) == 2  # Only Alembic's PK constraint and its index remain.
    alembic("upgrade", "head")
    assert "0002 (head)" in alembic("current")
    assert "No new upgrade operations detected" in alembic("check")
    assert asyncio.run(inspect_database(url, require_empty=True)) == before
