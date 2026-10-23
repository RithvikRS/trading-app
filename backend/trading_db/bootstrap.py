"""Administrator-only local provisioning; never imported by the HTTP application."""

from collections.abc import Mapping

import psycopg
from psycopg import sql
from sqlalchemy import URL

from trading_db.connections import DatabaseFailure, Role, validate_url


def provision(url: URL, passwords: Mapping[Role, str], project: str) -> None:
    validate_url(url)
    if url.username != "trading_bootstrap" or url.database is None:
        raise DatabaseFailure("Bootstrap requires its dedicated local identity.")
    with psycopg.connect(
        host=url.host,
        hostaddr="127.0.0.1",
        port=url.port,
        dbname=url.database,
        user=url.username,
        password=url.password,
        connect_timeout=5,
        sslmode="disable",
        options="-c statement_timeout=15000 -c lock_timeout=5000 -c search_path=pg_catalog",
    ) as connection:
        identity = connection.execute(
            "SELECT current_database(), current_setting('cluster_name'), "
            "current_setting('server_version_num')::int / 10000"
        ).fetchone()
        if identity != (url.database, project, 17):
            raise DatabaseFailure("Bootstrap database identity does not match.")
        # Serialize bootstrap and migrations with the same transaction-scoped lock.
        connection.execute("SELECT pg_advisory_xact_lock(714039231)")
        for role in ("migrator", "runtime"):
            name = f"trading_{role}"
            if not connection.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)
            ).fetchone():
                connection.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(name)))
            connection.execute(
                sql.SQL(
                    "ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION "
                    "NOBYPASSRLS NOINHERIT CONNECTION LIMIT 10 PASSWORD {}"
                ).format(sql.Identifier(name), sql.Literal(passwords[role]))
            )
            for setting, value in (
                ("search_path", "pg_catalog"),
                ("statement_timeout", "15s"),
                ("lock_timeout", "5s"),
                ("idle_in_transaction_session_timeout", "15s"),
            ):
                connection.execute(
                    sql.SQL("ALTER ROLE {} SET {} TO {}").format(
                        sql.Identifier(name), sql.Identifier(setting), sql.Literal(value)
                    )
                )
        for database in (url.database, "postgres", "template1", "template0"):
            connection.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
            )
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO trading_migrator, trading_runtime").format(
                sql.Identifier(url.database)
            )
        )
        connection.execute(
            sql.SQL("GRANT CREATE ON DATABASE {} TO trading_migrator").format(
                sql.Identifier(url.database)
            )
        )
        connection.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        connection.execute("CREATE SCHEMA IF NOT EXISTS app_meta AUTHORIZATION trading_migrator")
        connection.execute("REVOKE ALL ON SCHEMA app_meta FROM PUBLIC, trading_runtime")
        for objects, privilege in (
            ("TABLES", "ALL"),
            ("SEQUENCES", "ALL"),
            ("FUNCTIONS", "EXECUTE"),
            ("TYPES", "USAGE"),
        ):
            connection.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES FOR ROLE trading_migrator REVOKE {} ON {} FROM PUBLIC"
                ).format(sql.SQL(privilege), sql.SQL(objects))
            )
