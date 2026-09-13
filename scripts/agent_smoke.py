"""Read existing development seed through the real graph; never calls a live LLM."""

import asyncio
import json
from uuid import uuid4

from app.agent.graph import AgentContext, run_agent
from app.agent.llm import ModelReply
from app.core.config import Settings
from app.core.security import RequestContext
from app.db.session import create_db_engine, create_session_factory
from scripts.seed_data import seed_id


class SmokeModel:
    async def complete(self, messages, tools):
        if messages[-1]["role"] == "tool":
            return ModelReply(content=json.dumps({"action": "answer", "evidence_ids": [1, 2, 3, 4, 5, 6]}))
        calls = [
            ("search_products", {"query": "短袖"}), ("get_product", {"product_id": str(seed_id("product-1"))}),
            ("list_product_skus", {"product_id": str(seed_id("product-1"))}), ("get_inventory", {"sku_id": str(seed_id("sku-1"))}),
            ("get_order", {"order_no": "SEED-O005"}), ("get_logistics", {"order_no": "SEED-O005"}),
        ]
        return ModelReply(tool_calls=[{"id": f"smoke-{i}", "function": {"name": name, "arguments": json.dumps(args)}}
                                      for i, (name, args) in enumerate(calls)])


async def main():
    settings = Settings()
    if settings.app_env not in {"development", "test"}:
        raise ValueError("smoke_requires_development_or_test")
    engine = create_db_engine(settings.database_url.get_secret_value())
    try:
        state = await run_agent("查询开发样例商品、库存、订单和物流", context=AgentContext(
            RequestContext(seed_id("customer-a"), frozenset({"orders:read:self"}), uuid4()),
            SmokeModel(), create_session_factory(engine), settings,
        ))
        assert state["tool_call_count"] == 6 and state["final_response"].status == "ok"
        assert len(state["evidence"]) == 6 and all(e.result.status == "success" for e in state["evidence"])
        print("Agent smoke passed: real LangGraph + Registry + PostgreSQL; Fake Model; 6 read-only tools.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
