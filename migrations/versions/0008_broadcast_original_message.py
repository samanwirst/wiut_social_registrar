"""Keep the original organizer message reference for completed broadcasts."""

import sqlalchemy as sa
from alembic import op

revision = "0008_broadcast_original_message"
down_revision = "0007_forms_tables_broadcasts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("broadcasts", sa.Column("original_message_id", sa.BigInteger()))


def downgrade():
    op.drop_column("broadcasts", "original_message_id")
