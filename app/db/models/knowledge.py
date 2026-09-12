from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.commerce import status_type


class DocumentStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ScopeType(StrEnum):
    GLOBAL = "global"
    CATEGORY = "category"
    PRODUCT = "product"


class KnowledgeDocument(TimestampMixin, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("document_key", "version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="valid_period"),
        CheckConstraint(
            "(scope_type = 'global' AND category_code IS NULL AND product_id IS NULL) OR "
            "(scope_type = 'category' AND category_code IS NOT NULL "
            "AND length(trim(category_code)) > 0 AND product_id IS NULL) OR "
            "(scope_type = 'product' AND product_id IS NOT NULL AND category_code IS NULL)", name="scope_fields",
        ),
    )

    document_key: Mapped[str] = mapped_column(String(150))
    version: Mapped[int]
    title: Mapped[str] = mapped_column(String(255))
    source_uri: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(128))
    status: Mapped[DocumentStatus] = mapped_column(status_type(DocumentStatus), default=DocumentStatus.DRAFT)
    scope_type: Mapped[ScopeType] = mapped_column(status_type(ScopeType))
    category_code: Mapped[str | None] = mapped_column(String(100))
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeChunk(TimestampMixin, Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        CheckConstraint("chunk_index >= 0", name="chunk_index_nonnegative"),
        CheckConstraint(
            "(embedding IS NULL AND embedding_model IS NULL) OR "
            "(embedding IS NOT NULL AND embedding_model IS NOT NULL "
            "AND length(trim(embedding_model)) > 0)", name="embedding_pair",
        ),
    )

    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="RESTRICT"))
    chunk_index: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    locator: Mapped[str] = mapped_column(String(500))
    # ponytail: model undecided; pin dimensions by migration before model-specific ingestion.
    embedding: Mapped[list[float] | None] = mapped_column(Vector())
    embedding_model: Mapped[str | None] = mapped_column(String(255))
