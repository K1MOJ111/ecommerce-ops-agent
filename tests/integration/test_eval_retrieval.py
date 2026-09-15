import pytest

from app.core.config import Settings
from app.rag.embedding import FakeEmbeddingProvider
from app.rag.ingestion import ingest_document
from app.rag.retrieval import search_after_sales_policy
from scripts.ingest_knowledge import load_documents
from scripts.seed_data import seed_data

pytestmark = pytest.mark.integration


async def test_ablation_reuses_filters_and_disables_other_channel(db_session):
    from datetime import UTC, datetime
    settings = Settings(_env_file=None, database_url="postgresql+asyncpg://localhost/unused_test")
    embedding = FakeEmbeddingProvider()
    await seed_data(db_session, app_env="test")
    for doc in load_documents():
        await ingest_document(db_session, doc, settings=settings, embedding=embedding)
    class NeverEmbed(FakeEmbeddingProvider):
        async def embed(self, texts):
            raise AssertionError("keyword must not embed")
    for mode in ("vector", "keyword", "hybrid"):
        hits = await search_after_sales_policy(db_session,"退货",settings=settings,
            embedding=NeverEmbed() if mode=="keyword" else embedding, mode=mode,
            relevant_date=datetime(2026,5,1,tzinfo=UTC))
        assert all(h.version == 1 for h in hits if h.document_key == "demo-return")
        assert all(h.scope_type == "global" for h in hits)
        if mode != "hybrid":
            assert all(h.retrieval_source == [mode] for h in hits)
        if mode == "keyword":
            assert hits
    with pytest.raises(ValueError, match="invalid_retrieval_mode"):
        await search_after_sales_policy(db_session,"退货",settings=settings,mode="bad")
