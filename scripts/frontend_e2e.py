"""Run the real browser against an isolated PostgreSQL database populated with the existing Seed."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
from psycopg import Connection, sql
from sqlalchemy.engine import make_url

from app.agent.checkpoint import checkpoint_url
from app.core.config import Settings
from scripts.seed_data import seed_id

ROOT = Path(__file__).resolve().parents[1]


def main():
    settings = Settings()
    if settings.app_env not in {"development", "test"}:
        raise SystemExit("frontend_e2e_requires_development_or_test")
    for port in (8010, 5173):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"Port {port} is in use; stop that local server before E2E")
    name = f"ops_frontend_{uuid4().hex[:10]}_test"
    source = make_url(settings.database_url.get_secret_value())
    database_url = source.set(database=name).render_as_string(hide_password=False)
    admin_url = checkpoint_url(source.set(database="postgres").render_as_string(hide_password=False))
    env = {**os.environ, "DATABASE_URL": database_url, "APP_ENV": "test", "AGENT_PROVIDER": "fake",
           "EMBEDDING_PROVIDER": "fake", "DEV_ACTOR_ID": str(seed_id("customer-a")),
           "VITE_API_BASE_URL": "http://127.0.0.1:8010", "FRONTEND_E2E": "1"}
    output = ROOT / "output/playwright"
    output.mkdir(parents=True, exist_ok=True)
    server = None
    with Connection.connect(admin_url, autocommit=True, connect_timeout=3) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            for args in (("alembic", "upgrade", "head"), ("scripts.setup_checkpoints",),
                         ("scripts.seed_data",), ("scripts.ingest_knowledge", "--fake")):
                subprocess.run([sys.executable, "-m", *args], cwd=ROOT, env=env, check=True)
            with (output / "backend.log").open("w", encoding="utf-8") as log:
                server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010"],
                    cwd=ROOT, env=env, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                for _ in range(60):
                    try:
                        if httpx.get("http://127.0.0.1:8010/health", timeout=1).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.5)
                else:
                    raise RuntimeError("E2E API did not become healthy; inspect output/playwright/backend.log")
                subprocess.run([shutil.which("npm.cmd" if os.name == "nt" else "npm"), "run", "test:e2e"],
                               cwd=ROOT / "frontend", env=env, check=True)
                with Connection.connect(checkpoint_url(database_url), connect_timeout=3) as check:
                    assert check.execute("SELECT status FROM orders WHERE order_no='SEED-O001'").fetchone()[0] == "cancelled"
                    assert check.execute("SELECT payment_status FROM orders WHERE order_no='SEED-O003'").fetchone()[0] == "paid"
                    assert check.execute("SELECT count(*) FROM refunds WHERE status='requested'").fetchone()[0] == 1
                    assert check.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == 3
                print("E2E database postconditions passed: cancelled order, requested refund, unchanged payment, 3 audits")
        finally:
            if server:
                server.terminate()
                server.wait(timeout=15)
            # Only the random database created by this invocation; never the configured development database.
            assert name.startswith("ops_frontend_") and name.endswith("_test") and name != source.database
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            print("Removed this run's isolated E2E database")


if __name__ == "__main__":
    main()
