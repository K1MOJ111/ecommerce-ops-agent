import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.db.models.commerce import Product
from app.db.models.knowledge import KnowledgeChunk

from app.rag.retrieval import search_after_sales_policy
from app.rag.schemas import PolicySearchInput

EVAL_PATH = Path(__file__).resolve().parents[1] / "data/knowledge/retrieval_eval.json"


async def evaluate(session, *, settings, embedding) -> dict:
    dataset = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    details = []
    hits = reciprocal = positives = negatives = correct_empty = scope_correct = 0
    for case in dataset["cases"]:
        args = {key: case[key] for key in ("query", "category", "product_id", "relevant_date") if key in case}
        args.setdefault("relevant_date", datetime(2026, 9, 14, tzinfo=UTC))
        params = PolicySearchInput(**args, limit=dataset["k"])
        results = await search_after_sales_policy(session, **params.model_dump(by_alias=True), settings=settings, embedding=embedding)
        # Dataset names chunk_index; resolve the actual FK rather than guessing from the locator.
        indices = dict((await session.execute(select(KnowledgeChunk.id, KnowledgeChunk.chunk_index)
            .where(KnowledgeChunk.id.in_([r.chunk_id for r in results])))).all())
        found = [(r.document_key, r.version, indices[r.chunk_id]) for r in results]
        expected = [tuple(item) for item in case["expected"]]
        rank = next((i for i, item in enumerate(found, 1) if item in expected), None)
        if expected:
            positives += 1
            hits += rank is not None
            reciprocal += 1 / rank if rank else 0
        else:
            negatives += 1
            correct_empty += not results
        category = params.category
        if params.product_id:
            category = await session.scalar(select(Product.category_code).where(Product.id == params.product_id))
        scope_ok = all(r.scope_type in case["scope"] and (
            r.scope_type != "category" or r.category_code == category) and (
            r.scope_type != "product" or r.product_id == params.product_id) for r in results)
        scope_correct += scope_ok
        details.append({"id": case["id"], "found": found, "expected_rank": rank,
                        "expected_empty": not expected, "scope_ok": scope_ok})
    return {"provider": embedding.model, "k": dataset["k"], "positive_cases": positives, "negative_cases": negatives,
        "hit_at_k": hits / positives, "mrr": reciprocal / positives,
        "no_result_accuracy": correct_empty / negatives, "scope_accuracy": scope_correct / len(details), "cases": details}
