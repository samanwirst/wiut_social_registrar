"""Require a shared Telegram phone number to complete registration."""
from alembic import op
import sqlalchemy as sa

revision = "0002_registration_phone"
down_revision = "0001_registration"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("telegram_users", sa.Column("phone_number", sa.String(32), nullable=True))
    op.add_column("telegram_users", sa.Column("phone_shared_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("telegram_users", sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_telegram_users_registered_at", "telegram_users", ["registered_at"])


def downgrade():
    op.drop_index("ix_telegram_users_registered_at", table_name="telegram_users")
    op.drop_column("telegram_users", "registered_at")
    op.drop_column("telegram_users", "phone_shared_at")
    op.drop_column("telegram_users", "phone_number")
