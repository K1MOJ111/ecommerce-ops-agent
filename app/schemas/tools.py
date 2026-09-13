from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Query = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)]
Code = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=100)]
SpecKey = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=64)]
Limit = Annotated[int, Field(strict=True, ge=1, le=100)]


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, revalidate_instances="always")


class SearchProductsInput(ToolInput):
    query: Query
    category: Code | None = Field(default=None, serialization_alias="category_code")
    limit: Limit = 20


class GetProductInput(ToolInput):
    product_id: UUID


class ListProductSKUsInput(GetProductInput):
    specs: Annotated[dict[SpecKey, Code], Field(max_length=8)] | None = None
    limit: Limit = 100


class GetInventoryInput(ToolInput):
    sku_id: UUID
    warehouse_code: Code | None = None


class OrderQueryInput(ToolInput):
    order_no: Code


ToolStatus = Literal["success", "not_found", "invalid_argument", "forbidden", "temporarily_unavailable"]


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


DataT = TypeVar("DataT")


class ToolResult(BaseModel, Generic[DataT]):
    model_config = ConfigDict(extra="forbid")

    status: ToolStatus
    data: DataT | None = None
    source: str
    queried_at: datetime
    request_id: UUID
    error: ToolError | None = None

    @model_validator(mode="after")
    def consistent_outcome(self) -> "ToolResult[DataT]":
        if self.status == "success":
            if self.data is None or self.error is not None:
                raise ValueError("success_requires_data_and_no_error")
        elif self.data is not None or self.error is None:
            raise ValueError("failure_requires_error_and_no_data")
        return self
