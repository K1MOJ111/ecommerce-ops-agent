from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.llm import Message
from app.schemas.tools import ToolResult

Question = Literal["product", "sku", "color", "size", "order", "query", "order_item", "quantity", "amount", "reason"]
Reason = Literal["write_operation", "policy_unavailable", "unsupported"]


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    action: Literal["answer", "clarify", "reject"]
    intent: str | None = Field(default=None, max_length=80)
    evidence_ids: list[Annotated[int, Field(strict=True, ge=1)]] = Field(default_factory=list, max_length=128)
    question: Question | None = None
    reason: Reason | None = None

    @model_validator(mode="after")
    def consistent_action(self) -> "Decision":
        if ((self.action == "clarify") != (self.question is not None)
                or (self.action == "reject") != (self.reason is not None)):
            raise ValueError("invalid_decision")
        return self


class AgentError(BaseModel):
    code: str
    tool_call_id: str | None = None


class Evidence(BaseModel):
    id: int
    tool_call_id: str
    result: ToolResult


class FinalResponse(BaseModel):
    kind: Literal["answer", "clarify", "reject"]
    status: Literal["ok", "partial", "unconfirmed", "clarify", "rejected"]
    text: str
    evidence: list[Evidence] = Field(default_factory=list)
    errors: list[AgentError] = Field(default_factory=list)
    question: Question | None = None
    reason: Reason | None = None


class AgentState(TypedDict):
    messages: list[Message]
    intent: str | None
    evidence: list[Evidence]
    tool_call_count: int
    errors: list[AgentError]
    decision: Decision | None
    final_response: FinalResponse | None
    draft: dict | None
    operation_result: dict | None
