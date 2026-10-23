"""Destructive fixtures can operate only on the runner-created disposable cluster."""

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import URL, text

from trading_db.connections import DatabaseFailure, engine_for, require_disposable, verify_server
from trading_db.local import CACHE


@pytest.fixture
def database():
    context_path = Path(os.environ["TRADING_TEST_CONTEXT"])
    context_path.resolve().relative_to((CACHE / "tests").resolve())
    if context_path.is_symlink():
        raise DatabaseFailure("Invalid test context file.")
    context = json.loads(context_path.read_text())

    def url(role="migrator"):
        return URL.create(
            "postgresql+psycopg",
            username=f"trading_{role}",
            password=(context_path.parent / role).read_text(),
            host="127.0.0.1",
            port=context["port"],
            database="trading_test",
        )

    # This check must precede connecting as administrator or dropping any schema.
    require_disposable(url(), context["project"])
    engine = engine_for(url("bootstrap"), migration=True)
    try:
        with engine.begin() as connection:
            verify_server(connection, "trading_test", context["project"])
            connection.execute(text("DROP SCHEMA IF EXISTS app CASCADE"))
            connection.execute(text("DROP SCHEMA IF EXISTS app_meta CASCADE"))
            connection.execute(text("CREATE SCHEMA app_meta AUTHORIZATION trading_migrator"))
    finally:
        engine.dispose()
    return url, context["project"]
