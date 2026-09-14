from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.tools import Code, ToolInput

OperationType = Literal["request_order_cancellation", "create_refund_request"]
ReasonText = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500)]


class CancellationInput(ToolInput):
    order_no: Code
    reason: ReasonText


class RefundRequestInput(CancellationInput):
    order_item_id: UUID
    quantity: Annotated[int, Field(strict=True, gt=0, le=2147483647)]
    amount: Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2, allow_inf_nan=False)]


class OperationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    operation_type: OperationType
    actor: UUID
    target: dict
    parameters: dict
    current_state: dict
    expected_change: dict
    confirmation_summary: str


class StartRequest(ToolInput):
    request_key: UUID
    message: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=10000)]


class ResumeRequest(ToolInput):
    operation_id: UUID
    decision: Literal["confirm", "reject"]


class WorkflowResponse(BaseModel):
    thread_id: UUID
    status: Literal["running", "waiting_for_confirmation", "completed", "succeeded", "rejected", "conflict", "failed"]
    operation_id: UUID | None = None
    draft: OperationDraft | None = None
    result: dict | None = None
