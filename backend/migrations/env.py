"""Use the caller's verified connection and transaction; no URL discovery or log setup."""

from alembic import context
from sqlalchemy import Connection

connection = context.config.attributes.get("connection")
if context.is_offline_mode() or not isinstance(connection, Connection):
    raise RuntimeError("Use the project's explicit database migration command.")

context.configure(connection=connection, version_table_schema="app_meta", transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
