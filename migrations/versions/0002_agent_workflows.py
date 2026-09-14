"""Durable ownership and one-operation transaction receipt; preserve all business rows."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_workflows",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_key", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("operation_id", sa.Uuid(), unique=True),
        sa.Column("confirmation", sa.String(10)),
        sa.Column("draft", postgresql.JSONB(none_as_null=True)),
        sa.Column("result", postgresql.JSONB(none_as_null=True)),
        sa.UniqueConstraint("actor_id", "request_key"),
        sa.CheckConstraint("status IN ('running','waiting_for_confirmation','completed','succeeded','rejected','conflict','failed')", name="status"),
        sa.CheckConstraint("(operation_id IS NULL AND draft IS NULL) OR (operation_id IS NOT NULL AND draft IS NOT NULL AND jsonb_typeof(draft) = 'object')", name="draft_pair"),
        sa.CheckConstraint("status != 'waiting_for_confirmation' OR operation_id IS NOT NULL", name="waiting_operation"),
        sa.CheckConstraint("confirmation IS NULL OR confirmation IN ('confirm','reject')", name="confirmation"),
        sa.CheckConstraint("(status IN ('running','waiting_for_confirmation') AND result IS NULL) OR (status IN ('completed','succeeded','rejected','conflict','failed') AND result IS NOT NULL AND jsonb_typeof(result) = 'object')", name="result_state"),
    )


def downgrade() -> None:
    op.drop_table("agent_workflows")
