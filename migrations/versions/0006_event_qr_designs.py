"""Persist the selected QR design independently of temporary generation jobs."""

import sqlalchemy as sa
from alembic import op

revision = "0006_event_qr_designs"
down_revision = "0005_event_forms"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_qr_designs",
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("design_id", sa.String(36), nullable=False, unique=True),
        sa.Column("transparent_png", sa.LargeBinary(), nullable=False),
        sa.Column("opaque_png", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("event_qr_designs")
