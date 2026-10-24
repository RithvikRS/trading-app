"""Explicit transactional migrations using only the schema owner's identity."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import URL, text

from trading_db.connections import DatabaseFailure, engine_for, require_disposable, verify_server

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def apply(
    url: URL,
    project: str,
    *,
    direction: str = "upgrade",
    target: str = "head",
    directory: Path = MIGRATIONS,
) -> None:
    if url.username != "trading_migrator":
        raise DatabaseFailure("Migrations require the dedicated schema owner.")
    if direction not in {"upgrade", "downgrade"}:
        raise DatabaseFailure("Unknown migration direction.")
    if direction == "downgrade" or directory != MIGRATIONS:
        require_disposable(url, project)
    engine = engine_for(url, migration=True)
    try:
        with engine.begin() as connection:
            verify_server(connection, str(url.database), project)
            role = connection.execute(
                text(
                    "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            ).one()
            if any(role):
                raise DatabaseFailure("Migration identity has unexpected elevated privileges.")
            connection.execute(text("SELECT pg_advisory_xact_lock(714039231)"))
            config = Config()
            config.set_main_option("script_location", str(directory))
            config.attributes["connection"] = connection
            if direction == "upgrade":
                command.upgrade(config, target)
            else:
                # A forced owner policy hides records from the migrator too. Lock
                # disposable tables before making guards visible to their owner;
                # restore FORCE before commit, including tables retained by a downgrade.
                tables = tuple(
                    connection.execute(
                        text(
                            "SELECT relname FROM pg_class WHERE "
                            "relnamespace=to_regnamespace('app') "
                            "AND relkind='r' AND relforcerowsecurity ORDER BY relname"
                        )
                    ).scalars()
                )
                quote = connection.dialect.identifier_preparer.quote
                for table in tables:
                    connection.execute(
                        text(f"LOCK TABLE app.{quote(table)} IN ACCESS EXCLUSIVE MODE")
                    )
                for table in tables:
                    connection.execute(
                        text(f"ALTER TABLE app.{quote(table)} NO FORCE ROW LEVEL SECURITY")
                    )
                command.downgrade(config, target)
                remaining = set(
                    connection.execute(
                        text("SELECT tablename FROM pg_tables WHERE schemaname='app'")
                    ).scalars()
                )
                for table in tables:
                    if table in remaining:
                        connection.execute(
                            text(f"ALTER TABLE app.{quote(table)} FORCE ROW LEVEL SECURITY")
                        )
    finally:
        engine.dispose()


def revision(url: URL, project: str) -> str:
    engine = engine_for(url, migration=True)
    try:
        with engine.connect() as connection:
            verify_server(connection, str(url.database), project)
            context = MigrationContext.configure(
                connection, opts={"version_table_schema": "app_meta"}
            )
            return context.get_current_revision() or "base"
    finally:
        engine.dispose()
