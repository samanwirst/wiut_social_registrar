"""Events, unique student participation, and pending invitations."""
from alembic import op
import sqlalchemy as sa

revision = "0003_events"
down_revision = "0002_registration_phone"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("creator_telegram_user_id", sa.BigInteger(), sa.ForeignKey("telegram_users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_events_creator_telegram_user_id", "events", ["creator_telegram_user_id"])
    op.create_table("event_registrations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), sa.ForeignKey("telegram_users.id"), nullable=False),
        sa.Column("outlook_profile_id", sa.Integer(), sa.ForeignKey("outlook_profiles.id"), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", "outlook_profile_id", name="uq_event_student"),
        sa.UniqueConstraint("event_id", "telegram_user_id", name="uq_event_telegram_user"),
    )
    op.create_index("ix_event_registrations_telegram_user_id", "event_registrations", ["telegram_user_id"])
    op.create_index("ix_event_registrations_outlook_profile_id", "event_registrations", ["outlook_profile_id"])
    op.create_table("pending_event_registrations",
        sa.Column("telegram_user_id", sa.BigInteger(), sa.ForeignKey("telegram_users.id"), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id"), primary_key=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("pending_event_registrations")
    op.drop_index("ix_event_registrations_outlook_profile_id", table_name="event_registrations")
    op.drop_index("ix_event_registrations_telegram_user_id", table_name="event_registrations")
    op.drop_table("event_registrations")
    op.drop_index("ix_events_creator_telegram_user_id", table_name="events")
    op.drop_table("events")
