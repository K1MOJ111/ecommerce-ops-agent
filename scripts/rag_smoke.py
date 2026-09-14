"""Full Fake RAG/Agent/Eval smoke in an existing dedicated test DB, always rolled back."""

import argparse
import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import AgentContext, run_agent
from app.agent.llm import ModelReply
from app.core.config import Settings
from app.core.security import RequestContext
from app.db.session import create_db_engine
from app.rag.embedding import FakeEmbeddingProvider
from app.rag.ingestion import ingest_document
from scripts.ingest_knowledge import load_documents
from scripts.rag_eval import evaluate
from scripts.seed_data import seed_data, seed_id


class PolicySmokeModel:
    async def complete(self, messages, tools):
        if messages[-1]["role"] != "tool":
            name, args = "get_order", {"order_no": "SEED-O005"}
        else:
            result = json.loads(messages[-1]["content"])
            assert result["status"] == "success"
            if result["source"] == "get_order":
                name, args = "search_products", {"query": result["data"]["items"][0]["product_name_snapshot"]}
            elif result["source"] == "search_products":
                assert len(result["data"]) == 1
                name, args = "list_product_skus", {"product_id": result["data"][0]["id"]}
            elif result["source"] == "list_product_skus":
                order = next(json.loads(m["content"]) for m in messages if m["role"] == "tool"
                             and json.loads(m["content"])["source"] == "get_order")
                sku = next(s for s in result["data"] if s["id"] == order["data"]["items"][0]["sku_id"])
                name, args = "search_after_sales_policy", {"query": "退货 质量 开线", "product_id": sku["product_id"],
                                                          "relevant_date": "2026-09-14T00:00:00Z"}
            else:
                return ModelReply(content='{"action":"answer","evidence_ids":[1,4]}')
        return ModelReply(tool_calls=[{"id": f"smoke-{len(messages)}", "function": {"name": name, "arguments": json.dumps(args)}}])


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url or make_url(url).drivername != "postgresql+asyncpg" or not (make_url(url).database or "").endswith("_test"):
        raise ValueError("dedicated_TEST_DATABASE_URL_required")
    settings = Settings(_env_file=None, database_url=url, app_env="test")
    embedding = FakeEmbeddingProvider()
    engine = create_db_engine(url)
    try:
        async with engine.connect() as connection, connection.begin() as transaction:
            @asynccontextmanager
            async def sessions():
                async with AsyncSession(connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
                    yield session
            async with sessions() as session:
                await seed_data(session, app_env="test")
                for doc in load_documents():
                    await ingest_document(session, doc, settings=settings, embedding=embedding)
                    assert await ingest_document(session, doc, settings=settings, embedding=embedding) == "unchanged"
                report = await evaluate(session, settings=settings, embedding=embedding)
                await session.commit()  # Release SAVEPOINT only; outer transaction is always rolled back.
            state = await run_agent("我的订单 SEED-O005 有哪些退货和质量规则？", context=AgentContext(
                RequestContext(seed_id("customer-a"), frozenset({"orders:read:self"}), uuid4()),
                PolicySmokeModel(), sessions, settings, embedding))
            assert state["final_response"].status == "ok" and state["tool_call_count"] == 4
            assert [e.result.source for e in state["final_response"].evidence] == ["get_order", "search_after_sales_policy"]
            report["smoke"] = "passed: ingestion + PostgreSQL/pgvector + Registry + LangGraph + multi-tool Evidence; rolled back"
            await transaction.rollback()
        if args.report:
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=True))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
