"""Strict local targets and bounded, non-logging database connections."""

import re
from typing import Any, Literal

import psycopg
from sqlalchemy import URL, Connection, Engine, create_engine, event, text
from sqlalchemy.exc import DisconnectionError
from sqlalchemy.pool import ConnectionPoolEntry, NullPool, PoolResetState

Role = Literal["bootstrap", "migrator", "runtime", "auth"]


class DatabaseFailure(ValueError):
    """A failure safe to report without connection details or server errors."""


def validate_url(url: URL, *, test: bool = False) -> None:
    if (
        url.drivername != "postgresql+psycopg"
        or url.host != "127.0.0.1"
        or url.database not in ({"trading_test"} if test else {"trading_dev", "trading_test"})
        or url.username
        not in {"trading_bootstrap", "trading_migrator", "trading_runtime", "trading_auth"}
        or url.port is None
        or not 1024 <= url.port <= 65535
        or not url.password
        or url.query
    ):
        raise DatabaseFailure("Only the managed local database target is accepted.")


def engine_for(url: URL, *, migration: bool = False) -> Engine:
    validate_url(url)
    options = (
        {"poolclass": NullPool}
        if migration
        else {
            "pool_size": 2,
            "max_overflow": 0,
            "pool_timeout": 5,
            "pool_pre_ping": True,
            "pool_recycle": 300,
        }
    )
    runtime = url.username in {"trading_runtime", "trading_auth"}
    engine = create_engine(
        url,
        **options,
        echo=False,
        hide_parameters=True,
        isolation_level="READ COMMITTED",
        pool_reset_on_return=None if runtime else "rollback",
        connect_args={
            "hostaddr": "127.0.0.1",  # Override libpq's PGHOSTADDR/service-file redirects too.
            "connect_timeout": 5,
            "sslmode": "disable",  # Only the validated literal loopback address is accepted.
            "options": "-c statement_timeout=15000 -c lock_timeout=5000 "
            "-c idle_in_transaction_session_timeout=15000 -c search_path=pg_catalog "
            "-c timezone=UTC" + (" -c app.owner_id=" if runtime else ""),
        },
    )
    if runtime:
        event.listen(engine, "reset", _reset_owner_context)
    return engine


def _reset_owner_context(
    connection: psycopg.Connection[tuple[Any, ...]],
    record: ConnectionPoolEntry,
    state: PoolResetState,
) -> None:
    if state.terminate_only:
        return
    try:
        # Roll back first: cleanup must never commit unfinished application writes.
        connection.rollback()
        connection.execute("SELECT pg_catalog.set_config('app.owner_id', '', false)")
        connection.commit()
    except BaseException:
        # Never return an uncertain session to the pool or log driver payloads.
        record.invalidate()
        raise DisconnectionError("Runtime connection reset failed.") from None


def verify_server(connection: Connection, database: str, project: str) -> None:
    row = connection.execute(
        text(
            "SELECT current_database(), current_setting('cluster_name'), "
            "current_setting('server_version_num')::int / 10000"
        )
    ).one()
    if tuple(row) != (database, project, 17):
        raise DatabaseFailure("Local database identity or PostgreSQL major does not match.")


def require_disposable(url: URL, project: str) -> None:
    """Validate before connecting, then verify the per-run server marker before any reset."""
    validate_url(url, test=True)
    if not re.fullmatch(r"trading-test-[0-9a-f]{16}", project):
        raise DatabaseFailure("Disposable database project identity is required.")
    engine = engine_for(url, migration=True)
    try:
        with engine.connect() as connection:
            verify_server(connection, "trading_test", project)
    finally:
        engine.dispose()
