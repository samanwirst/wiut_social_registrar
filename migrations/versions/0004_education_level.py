"""Persist the student's selected education level."""
from alembic import op
import sqlalchemy as sa

revision = "0004_education_level"
down_revision = "0003_events"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("telegram_users", sa.Column("education_level", sa.String(16), nullable=True))
    op.add_column("telegram_users", sa.Column("education_selected_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_telegram_users_education_level", "telegram_users", ["education_level"])


def downgrade():
    op.drop_index("ix_telegram_users_education_level", table_name="telegram_users")
    op.drop_column("telegram_users", "education_selected_at")
    op.drop_column("telegram_users", "education_level")
