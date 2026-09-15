import re
from datetime import UTC, datetime
from uuid import UUID
from typing import Literal
from app.core.observability import observed

from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import Settings, get_settings
from app.db.models.commerce import Product, ProductStatus
from app.db.models.knowledge import DocumentStatus, KnowledgeChunk, KnowledgeDocument, ScopeType
from app.rag.embedding import EmbeddingProvider, OpenAICompatibleEmbedding, validate_vectors
from app.rag.schemas import PolicyHit, PolicySearchInput


def fuse_ranks(vector_ids: list[UUID], keyword_ids: list[UUID]) -> list[tuple[UUID, float]]:
    scores: dict[UUID, float] = {}
    for ids in (vector_ids, keyword_ids):
        for rank, key in enumerate(dict.fromkeys(ids), 1):
            scores[key] = scores.get(key, 0.0) + 1 / (60 + rank)
    # Stable ties retain vector-first candidate order; SQL orders ties by document key and chunk index.
    return sorted(scores.items(), key=lambda item: -item[1])


@observed("rag")
async def search_after_sales_policy(session: AsyncSession, query: str, *, product_id: UUID | None = None,
        category_code: str | None = None, relevant_date: datetime | None = None, limit: int | None = None,
        settings: Settings | None = None, embedding: EmbeddingProvider | None = None,
        mode: Literal["vector", "keyword", "hybrid"] = "hybrid") -> list[PolicyHit]:
    if mode not in {"vector", "keyword", "hybrid"}:
        raise ValueError("invalid_retrieval_mode")
    params = PolicySearchInput(query=query, product_id=product_id, category=category_code,
                               relevant_date=relevant_date, limit=limit)
    settings = settings or get_settings()
    embedding = embedding if embedding is not None else OpenAICompatibleEmbedding(settings)
    query, category_code, product_id = params.query, params.category, params.product_id
    if product_id is not None:
        product = await session.scalar(select(Product).where(Product.id == product_id, Product.status == ProductStatus.ACTIVE))
        if product is None:
            return []
        if category_code is not None and category_code != product.category_code:
            raise ValueError("product_category_mismatch")
        category_code = product.category_code
    at = params.relevant_date or datetime.now(UTC)
    k = params.limit or settings.rag_top_k
    doc, chunk = KnowledgeDocument, KnowledgeChunk
    def scope_filter(table):
        scopes = [table.scope_type == ScopeType.GLOBAL]
        if category_code:
            scopes.append(and_(table.scope_type == ScopeType.CATEGORY, table.category_code == category_code))
        if product_id:
            scopes.append(and_(table.scope_type == ScopeType.PRODUCT, table.product_id == product_id))
        return or_(*scopes)
    newer = aliased(KnowledgeDocument)
    # Highest published, effective version per key; no assumption that order creation is the policy event date.
    filters = [doc.status == DocumentStatus.PUBLISHED, doc.valid_from <= at,
        or_(doc.valid_to.is_(None), doc.valid_to > at), scope_filter(doc),
        ~exists(select(newer.id).where(newer.document_key == doc.document_key, newer.version > doc.version,
            newer.status == DocumentStatus.PUBLISHED, newer.valid_from <= at, scope_filter(newer),
            or_(newer.valid_to.is_(None), newer.valid_to > at)))]
    base = select(chunk, doc).join(doc, chunk.document_id == doc.id).where(*filters)
    if await session.scalar(base.with_only_columns(chunk.id).limit(1)) is None:
        return []
    vector_rows = []
    if mode != "keyword":
        vector = validate_vectors(await embedding.embed([query]), 1, settings.embedding_dim)[0]
        # CASE protects the distance operation even if PostgreSQL reorders WHERE predicates.
        safe_vector = case((and_(chunk.embedding_model == embedding.model,
            func.vector_dims(chunk.embedding) == len(vector)), chunk.embedding), else_=None)
        similarity = 1 - safe_vector.cosine_distance(vector)
        # ponytail: exact vector and substring scans suit this small corpus; add indexes only after query-plan evidence.
        vector_rows = list((await session.execute(base.add_columns(similarity.label("similarity"))
            .where(similarity >= settings.rag_min_similarity)
            .order_by(similarity.desc(), doc.document_key, doc.version, chunk.chunk_index).limit(k * 4))).all())
    # Keep English words and overlapping Chinese bigrams; all matches are bound/escaped literals.
    tokens = list(dict.fromkeys(m.group(1) or m.group() for m in re.finditer(
        r"[a-z0-9]+|(?=([\u4e00-\u9fff]{2}))", query.lower())))[:100]
    keyword_score = sum((case((chunk.content.icontains(t, autoescape=True), 1), else_=0) for t in tokens),
                        case((chunk.content.icontains(query, autoescape=True), 2), else_=0))
    keyword_rows = []
    if mode != "vector":
        keyword_rows = list((await session.execute(base.where(keyword_score > 0)
            .order_by(keyword_score.desc(), doc.document_key, doc.version, chunk.chunk_index).limit(k * 4))).all())
    vector_ids = [c.id for c, d, s in vector_rows]
    keyword_ids = [c.id for c, d in keyword_rows]
    rows = {c.id: (c, d) for c, d in keyword_rows}
    rows.update({c.id: (c, d) for c, d, s in vector_rows})
    similarities = {c.id: float(s) for c, d, s in vector_rows}
    result = []
    for rank, (key, score) in enumerate(fuse_ranks(vector_ids, keyword_ids)[:k], 1):
        c, d = rows[key]
        result.append(PolicyHit(document_id=d.id, document_key=d.document_key, version=d.version, chunk_id=c.id,
            title=d.title, locator=c.locator, content=c.content, source_uri=d.source_uri,
            citation=f"{d.document_key}@v{d.version}#{c.id}:{c.locator}", scope_type=d.scope_type,
            category_code=d.category_code, product_id=d.product_id, valid_from=d.valid_from, valid_to=d.valid_to,
            relevant_date=at, retrieval_source=[s for s, ids in (("vector", vector_ids), ("keyword", keyword_ids)) if key in ids],
            score=score, rank=rank, vector_rank=vector_ids.index(key) + 1 if key in vector_ids else None,
            keyword_rank=keyword_ids.index(key) + 1 if key in keyword_ids else None,
            vector_similarity=similarities.get(key)))
    return result
