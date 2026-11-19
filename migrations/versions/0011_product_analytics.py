"""First-party usage events and password plus Telegram administrator sessions."""

import sqlalchemy as sa
from alembic import op

revision = "0011_product_analytics"
down_revision = "0010_administrator_announcements"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("user_id", sa.BigInteger()),
        sa.Column("form_id", sa.String(36)),
        sa.Column("session_id", sa.String(64)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("properties", sa.JSON(), nullable=False),
    )
    for name, columns in (
        ("ix_usage_name_time", ["name", "occurred_at"]),
        ("ix_usage_form_time", ["form_id", "occurred_at"]),
        ("ix_usage_user_time", ["user_id", "occurred_at"]),
        ("ix_usage_events_occurred_at", ["occurred_at"]),
    ):
        op.create_index(name, "usage_events", columns)
    op.create_table(
        "admin_login_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("administrator_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("outcome", sa.String(20), nullable=False),
    )
    op.create_table(
        "admin_challenges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("administrator_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("browser_hash", sa.String(64), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("credential_hash", sa.String(64), nullable=False),
        sa.Column("attempts_left", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("delivered", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "admin_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("administrator_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("credential_hash", sa.String(64), nullable=False),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )
    op.create_table(
        "analytics_settings",
        sa.Column("key", sa.String(32), primary_key=True),
        sa.Column("value", sa.String(100), nullable=False),
    )
    op.add_column("event_form_sessions", sa.Column("analytics_id", sa.String(36)))
    op.add_column(
        "event_form_sessions", sa.Column("question_started_at", sa.DateTime(timezone=True))
    )


def downgrade():
    op.drop_column("event_form_sessions", "question_started_at")
    op.drop_column("event_form_sessions", "analytics_id")
    for name in (
        "analytics_settings", "admin_sessions", "admin_challenges", "admin_login_attempts", "usage_events"
    ):
        op.drop_table(name)
