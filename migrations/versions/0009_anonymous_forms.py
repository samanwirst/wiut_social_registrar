"""Anonymous form settings and response-local opaque identities."""

from alembic import op
import sqlalchemy as sa

revision = "0009_anonymous_forms"
down_revision = "0008_broadcast_original_message"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "events", sa.Column("anonymous", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column(
        "events",
        sa.Column("anonymous_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("event_registrations", sa.Column("anonymous_id", sa.String(36), nullable=True))
    op.create_index(
        "ux_event_registration_anonymous_id", "event_registrations", ["anonymous_id"], unique=True
    )
    op.execute(
        sa.text(
            "UPDATE events SET anonymous_locked = true WHERE EXISTS (SELECT 1 FROM event_registrations WHERE event_registrations.event_id = events.id)"
        )
    )


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM events WHERE anonymous = true"))
        .scalar()
    ):
        raise RuntimeError(
            "Anonymous forms must not be downgraded to code that exposes identified responses"
        )
    op.drop_index("ux_event_registration_anonymous_id", table_name="event_registrations")
    op.drop_column("event_registrations", "anonymous_id")
    op.drop_column("events", "anonymous_locked")
    op.drop_column("events", "anonymous")
