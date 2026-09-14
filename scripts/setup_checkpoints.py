"""Explicit setup: python -m scripts.setup_checkpoints (uses DATABASE_URL)."""
from app.agent.checkpoint import setup_checkpoints
from app.core.config import Settings


if __name__ == "__main__":
    setup_checkpoints(Settings().database_url.get_secret_value())
    print("PostgreSQL checkpoint schema ready.")
