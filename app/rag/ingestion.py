import hashlib
import re
from dataclasses import dataclass

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models.knowledge import DocumentStatus, KnowledgeChunk, KnowledgeDocument
from app.rag.embedding import EmbeddingProvider, validate_vectors
from app.rag.schemas import KnowledgeInput


@dataclass(frozen=True)
class Chunk:
    content: str
    locator: str


def chunk_document(content: str, *, size: int, overlap: int) -> list[Chunk]:
    if not 0 <= overlap < size:
        raise ValueError("invalid_chunk_configuration")
    # Paragraphs are indivisible rules. Oversized rules stay whole; never sever a condition from its consequence.
    paragraphs = [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", content, re.S)]
    chunks = []
    start = 0
    while start < len(paragraphs):
        end = start + 1
        while end < len(paragraphs) and paragraphs[end][1] - paragraphs[start][0] <= size:
            end += 1
        left, right = paragraphs[start][0], paragraphs[end - 1][1]
        chunks.append(Chunk(content[left:right], f"chars:{left}-{right};paragraphs:{start + 1}-{end}"))
        if end == len(paragraphs):
            break
        next_start = end
        while next_start > start + 1 and paragraphs[end - 1][1] - paragraphs[next_start - 1][0] <= overlap:
            next_start -= 1
        start = next_start
    return chunks


async def ingest_document(session: AsyncSession, document: KnowledgeInput, *,
                          embedding: EmbeddingProvider, settings: Settings) -> str:
    document = KnowledgeInput.model_validate(document.model_dump())
    if not embedding.model or len(embedding.model) > 255:
        raise ValueError("invalid_embedding_model")
    chunks = chunk_document(document.content, size=settings.rag_chunk_size, overlap=settings.rag_chunk_overlap)
    content_hash = hashlib.sha256(document.content.encode()).hexdigest()
    values = document.model_dump()
    # Serialize this business key, including first insert. Only the caller owns the outer commit.
    async with session.begin_nested():
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": int.from_bytes(hashlib.sha256(document.document_key.encode()).digest()[:8], signed=True)})
        row = await session.scalar(select(KnowledgeDocument).where(
            KnowledgeDocument.document_key == document.document_key, KnowledgeDocument.version == document.version))
        if row:
            unchanged = row.content_hash == content_hash and all(getattr(row, k) == v for k, v in values.items())
            if not unchanged and row.status != DocumentStatus.DRAFT:
                raise ValueError("published_or_archived_version_is_immutable")
            old = list(await session.scalars(select(KnowledgeChunk).where(
                KnowledgeChunk.document_id == row.id).order_by(KnowledgeChunk.chunk_index)))
            if unchanged and len(old) == len(chunks) and all(
                c.content == p.content and c.locator == p.locator and c.embedding_model == embedding.model
                and c.embedding is not None and (settings.embedding_dim is None or len(c.embedding) == settings.embedding_dim)
                for c, p in zip(old, chunks)
            ):
                return "unchanged"
        vectors = validate_vectors(await embedding.embed([c.content for c in chunks]), len(chunks), settings.embedding_dim)
        outcome = "updated" if row else "created"
        if row:
            await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == row.id))
            for name, value in values.items():
                setattr(row, name, value)
            row.content_hash = content_hash
        else:
            row = KnowledgeDocument(**values, content_hash=content_hash)
            session.add(row)
        await session.flush()
        session.add_all([KnowledgeChunk(document_id=row.id, chunk_index=i, content=chunk.content,
            locator=chunk.locator, embedding=vector, embedding_model=embedding.model)
            for i, (chunk, vector) in enumerate(zip(chunks, vectors))])
        await session.flush()
    return outcome
