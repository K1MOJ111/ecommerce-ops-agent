from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """Append-event schema only; runtime append-only privileges arrive with audit writing."""

    __tablename__ = "audit_logs"
    __table_args__ = (CheckConstraint("jsonb_typeof(details) = 'object'", name="details_object"),)

    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    request_id: Mapped[UUID]
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[UUID | None]
    result: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict[str, object]] = mapped_column(JSONB)
