"""Event-specific forms and expiring answers, separate from student profiles."""
from alembic import op
import sqlalchemy as sa

revision = "0005_event_forms"
down_revision = "0004_education_level"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("description", sa.Text(), nullable=False, server_default=""))
    op.add_column("events", sa.Column("registration_open", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("events", sa.Column("questions", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("events", sa.Column("response_retention_days", sa.Integer(), nullable=False, server_default="30"))
    op.add_column("events", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("events", sa.Column("form_revision", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("events", sa.Column("form_locked", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table("event_answers",
        sa.Column("registration_id", sa.Integer(), sa.ForeignKey("event_registrations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_event_answers_expires_at", "event_answers", ["expires_at"])
    op.create_table("event_form_sessions",
        sa.Column("telegram_user_id", sa.BigInteger(), sa.ForeignKey("telegram_users.id"), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("question_index", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(16), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_event_form_sessions_event_id", "event_form_sessions", ["event_id"])
    op.create_index("ix_event_form_sessions_expires_at", "event_form_sessions", ["expires_at"])


def downgrade():
    op.drop_table("event_form_sessions")
    op.drop_table("event_answers")
    for column in ("form_locked", "form_revision", "revision", "response_retention_days", "questions", "registration_open", "description"):
        op.drop_column("events", column)
