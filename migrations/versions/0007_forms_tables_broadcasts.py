"""General forms, temporary editable tables, and durable native-message broadcasts."""

import sqlalchemy as sa
from alembic import op

revision = "0007_forms_tables_broadcasts"
down_revision = "0006_event_qr_designs"
branch_labels = None
depends_on = None


def upgrade():
    for column in [
        sa.Column("kind", sa.String(16), nullable=False, server_default="event"),
        sa.Column("department", sa.String(100), nullable=False, server_default=""),
        sa.Column("table_columns", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("columns_revision", sa.Integer(), nullable=False, server_default="1"),
    ]:
        op.add_column("events", column)
    op.add_column(
        "event_registrations",
        sa.Column("table_revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("event_registrations", sa.Column("table_expires_at", sa.DateTime(timezone=True)))
    connection = op.get_bind()
    deadline = (
        "registered_at + (SELECT response_retention_days FROM events WHERE events.id = event_registrations.event_id) * INTERVAL '1 day'"
        if connection.dialect.name == "postgresql"
        else "datetime(registered_at, '+' || (SELECT response_retention_days FROM events WHERE events.id = event_registrations.event_id) || ' days')"
    )
    connection.execute(sa.text("UPDATE event_registrations SET table_expires_at = " + deadline))
    connection.execute(
        sa.text(
            "UPDATE event_registrations SET table_expires_at = (SELECT expires_at FROM event_answers WHERE registration_id = event_registrations.id) WHERE EXISTS (SELECT 1 FROM event_answers WHERE registration_id = event_registrations.id AND expires_at < table_expires_at)"
        )
    )
    op.create_table(
        "event_table_values",
        sa.Column(
            "registration_id",
            sa.Integer(),
            sa.ForeignKey("event_registrations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_event_table_values_expires_at", "event_table_values", ["expires_at"])
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.BigInteger(), sa.ForeignKey("telegram_users.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("prompt_message_id", sa.BigInteger()),
        sa.Column("source_message_id", sa.BigInteger()),
        sa.Column("content_kind", sa.String(24)),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    for name in ["event_id", "owner_id", "status", "created_at", "expires_at"]:
        op.create_index("ix_broadcasts_" + name, "broadcasts", [name])
    op.create_table(
        "broadcast_recipients",
        sa.Column(
            "broadcast_id",
            sa.String(36),
            sa.ForeignKey("broadcasts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "telegram_user_id",
            sa.BigInteger(),
            sa.ForeignKey("telegram_users.id"),
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_id", sa.BigInteger()),
        sa.Column("error_code", sa.String(32)),
    )
    for name in ["status", "next_attempt_at"]:
        op.create_index("ix_broadcast_recipients_" + name, "broadcast_recipients", [name])


def downgrade():
    op.drop_table("broadcast_recipients")
    op.drop_table("broadcasts")
    op.drop_table("event_table_values")
    # Native DROP COLUMN keeps referencing tables and their foreign keys intact.
    # Rebuilding the events table with SQLite batch mode would drop a referenced parent.
    for name in ["table_expires_at", "table_revision"]:
        op.drop_column("event_registrations", name)
    for name in ["columns_revision", "table_columns", "department", "kind"]:
        op.drop_column("events", name)
