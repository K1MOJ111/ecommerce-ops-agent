from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AgentWorkflow(TimestampMixin, Base):
    """One request, at most one immutable operation, with its transaction receipt."""

    __tablename__ = "agent_workflows"
    __table_args__ = (
        UniqueConstraint("actor_id", "request_key"),
        CheckConstraint("status IN ('running','waiting_for_confirmation','completed','succeeded','rejected','conflict','failed')", name="status"),
        CheckConstraint("(operation_id IS NULL AND draft IS NULL) OR (operation_id IS NOT NULL AND draft IS NOT NULL AND jsonb_typeof(draft) = 'object')", name="draft_pair"),
        CheckConstraint("status != 'waiting_for_confirmation' OR operation_id IS NOT NULL", name="waiting_operation"),
        CheckConstraint("confirmation IS NULL OR confirmation IN ('confirm','reject')", name="confirmation"),
        CheckConstraint("(status IN ('running','waiting_for_confirmation') AND result IS NULL) OR (status IN ('completed','succeeded','rejected','conflict','failed') AND result IS NOT NULL AND jsonb_typeof(result) = 'object')", name="result_state"),
    )

    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    request_key: Mapped[UUID]
    request_id: Mapped[UUID]
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="running")
    operation_id: Mapped[UUID | None] = mapped_column(unique=True)
    confirmation: Mapped[str | None] = mapped_column(String(10))
    draft: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    result: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
