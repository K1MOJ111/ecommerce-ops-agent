"""Explicit local knowledge ingestion. No application-start hook or Agent tool."""

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

from app.core.config import Settings
from app.db.session import create_db_engine, create_session_factory
from app.rag.embedding import FakeEmbeddingProvider, OpenAICompatibleEmbedding
from app.rag.ingestion import ingest_document
from app.rag.schemas import KnowledgeInput

DEFAULT_SOURCE = Path(__file__).resolve().parents[1] / "data/knowledge/simulated_policies.json"


def load_documents(path: Path = DEFAULT_SOURCE) -> list[KnowledgeInput]:
    return [KnowledgeInput.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))["documents"]]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--fake", action="store_true", help="Use explicitly simulated embeddings; never a live API")
    args = parser.parse_args()
    settings = Settings()
    if settings.app_env not in {"development", "test"}:
        raise ValueError("ingestion_command_requires_development_or_test")
    documents = load_documents(args.source)
    provider = FakeEmbeddingProvider() if args.fake else OpenAICompatibleEmbedding(settings)
    engine = create_db_engine(settings.database_url.get_secret_value())
    counts = Counter()
    try:
        async with create_session_factory(engine)() as session, session.begin():
            for document in documents:
                counts[await ingest_document(session, document, embedding=provider, settings=settings)] += 1
        print(json.dumps(dict(counts)))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
