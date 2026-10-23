"""Strict local targets and bounded, non-logging database connections."""

import re
from typing import Literal

from sqlalchemy import URL, Connection, Engine, create_engine, text
from sqlalchemy.pool import NullPool

Role = Literal["bootstrap", "migrator", "runtime"]


class DatabaseFailure(ValueError):
    """A failure safe to report without connection details or server errors."""


def validate_url(url: URL, *, test: bool = False) -> None:
    if (
        url.drivername != "postgresql+psycopg"
        or url.host != "127.0.0.1"
        or url.database not in ({"trading_test"} if test else {"trading_dev", "trading_test"})
        or url.username not in {"trading_bootstrap", "trading_migrator", "trading_runtime"}
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
    return create_engine(
        url,
        **options,
        echo=False,
        hide_parameters=True,
        connect_args={
            "hostaddr": "127.0.0.1",  # Override libpq's PGHOSTADDR/service-file redirects too.
            "connect_timeout": 5,
            "sslmode": "disable",  # Only the validated literal loopback address is accepted.
            "options": "-c statement_timeout=15000 -c lock_timeout=5000 "
            "-c idle_in_transaction_session_timeout=15000 -c search_path=pg_catalog",
        },
    )


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
