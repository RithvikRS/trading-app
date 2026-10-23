"""Create the private application schema without domain or identity tables."""

from alembic import op

revision = "0001_private_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA app AUTHORIZATION trading_migrator")
    op.execute("REVOKE ALL ON SCHEMA app FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA app TO trading_runtime")


def downgrade() -> None:
    # No CASCADE: an unexpected object must stop rollback instead of deleting it.
    op.execute("DROP SCHEMA app")
