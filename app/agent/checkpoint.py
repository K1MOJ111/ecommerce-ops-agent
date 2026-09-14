"""Official PostgresSaver with stdlib async bridging for Windows Proactor compatibility."""
import asyncio
from contextlib import asynccontextmanager
from uuid import UUID

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import Connection
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url


class PostgresCheckpointer(PostgresSaver):
    async def aget_tuple(self, config):
        return await asyncio.to_thread(self.get_tuple, config)

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)


def checkpoint_url(database_url: str) -> str:
    return make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)


def setup_checkpoints(database_url: str) -> None:
    """Explicit infrastructure setup, never DDL at API startup."""
    with Connection.connect(checkpoint_url(database_url), autocommit=True, connect_timeout=3, row_factory=dict_row) as connection:
        connection.execute("CREATE SCHEMA IF NOT EXISTS agent_checkpoints")
        connection.execute("SET search_path TO agent_checkpoints")
        # Official migrations include concurrent indexes; autocommit is required.
        PostgresSaver(connection).setup()


@asynccontextmanager
async def checkpoint_session(database_url: str, thread_id: UUID):
    connection = await asyncio.to_thread(
        Connection.connect, checkpoint_url(database_url), autocommit=True, prepare_threshold=0,
        row_factory=dict_row, connect_timeout=3,
        options="-c search_path=agent_checkpoints -c statement_timeout=5000",
    )
    try:
        # Serialize graph writers across processes, not business tables or unrelated workflows.
        # Session lock is released on connection close, including process death.
        await asyncio.to_thread(connection.execute, "SELECT pg_advisory_lock(%s)", (thread_id.int & ((1 << 63) - 1),))
        serializer = JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=[
            ("app.agent.state", name) for name in ("Evidence", "Decision", "AgentError", "FinalResponse")
        ])
        yield PostgresCheckpointer(connection, serde=serializer)
    finally:
        await asyncio.to_thread(connection.close)
