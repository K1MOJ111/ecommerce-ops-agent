from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.db.models.knowledge import DocumentStatus, ScopeType
from app.schemas.tools import Code, Limit, Query, ToolInput

Nonempty = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]


class KnowledgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    document_key: Annotated[Nonempty, Field(max_length=150)]
    version: Annotated[int, Field(strict=True, gt=0)]
    title: Annotated[Nonempty, Field(max_length=255)]
    source_uri: Annotated[Nonempty, Field(max_length=2000)]
    content: Annotated[Nonempty, Field(max_length=200000)]
    status: DocumentStatus = DocumentStatus.DRAFT
    scope_type: ScopeType = ScopeType.GLOBAL
    category_code: Code | None = None
    product_id: UUID | None = None
    valid_from: AwareDatetime
    valid_to: AwareDatetime | None = None

    @model_validator(mode="after")
    def applicability(self):
        valid_scope = {
            ScopeType.GLOBAL: self.category_code is None and self.product_id is None,
            ScopeType.CATEGORY: self.category_code is not None and self.product_id is None,
            ScopeType.PRODUCT: self.category_code is None and self.product_id is not None,
        }
        if not valid_scope[self.scope_type] or (self.valid_to and self.valid_to <= self.valid_from):
            raise ValueError("invalid_applicability")
        return self


class PolicySearchInput(ToolInput):
    query: Query
    product_id: UUID | None = None
    category: Code | None = Field(default=None, serialization_alias="category_code")
    relevant_date: AwareDatetime | None = None
    limit: Limit | None = None


class PolicyHit(BaseModel):
    document_id: UUID
    document_key: str
    version: int
    chunk_id: UUID
    title: str
    locator: str
    content: str
    source_uri: str
    citation: str
    scope_type: ScopeType
    category_code: str | None
    product_id: UUID | None
    valid_from: datetime
    valid_to: datetime | None
    relevant_date: datetime
    retrieval_source: list[Literal["vector", "keyword"]]
    score: float
    rank: int
    vector_rank: int | None = None
    keyword_rank: int | None = None
    vector_similarity: float | None = None
