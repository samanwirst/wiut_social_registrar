"""Allow administrator announcements to use the existing durable delivery queue."""

import sqlalchemy as sa
from alembic import op

revision = "0010_administrator_announcements"
down_revision = "0009_anonymous_forms"
branch_labels = None
depends_on = None


def _nullable(nullable):
    connection = op.get_bind()
    if connection.dialect.name != "sqlite":
        op.alter_column("broadcasts", "event_id", existing_type=sa.String(36), nullable=nullable)
        return
    # SQLite recreates the parent table. Disable FK cascades on this connection
    # while copying it so existing broadcast recipients cannot be deleted.
    # Keep the complete copy/rename inside an explicit physical transaction.
    if connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("COMMIT")
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    connection.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        with op.batch_alter_table("broadcasts") as batch:
            batch.alter_column("event_id", existing_type=sa.String(36), nullable=nullable)
        connection.exec_driver_sql("COMMIT")
    except BaseException:
        connection.exec_driver_sql("ROLLBACK")
        raise
    finally:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
        raise RuntimeError("Foreign key validation failed after announcement migration")


def upgrade():
    _nullable(True)


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM broadcasts WHERE event_id IS NULL"))
        .scalar()
    ):
        raise RuntimeError("Administrator announcements must be retained before downgrading")
    _nullable(False)
