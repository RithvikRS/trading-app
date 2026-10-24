"""Repeated disposable schema churn must not accumulate unbounded catalog files."""

from sqlalchemy import text

from database_tests.conftest import reset_database
from trading_db.connections import engine_for


def test_repeated_schema_churn_reuses_catalog_storage(database):
    url, project = database
    engine = engine_for(url("bootstrap"), migration=True)
    try:
        with engine.connect() as connection:
            initial = connection.execute(
                text("SELECT pg_database_size(current_database())")
            ).scalar_one()
        for _ in range(10):
            with engine.begin() as connection:
                connection.execute(text("CREATE SCHEMA app AUTHORIZATION trading_migrator"))
                for index in range(100):
                    columns = ",".join(f"value_{column} numeric" for column in range(10))
                    connection.execute(
                        text(
                            f"CREATE TABLE app.synthetic_{index} (id bigint PRIMARY KEY,{columns})"
                        )
                    )
            reset_database(engine, project)
        with engine.connect() as connection:
            final = connection.execute(
                text("SELECT pg_database_size(current_database())")
            ).scalar_one()
        # Some reusable pages/index high-water marks remain; they must stay small
        # compared with the fixed 256 MiB tmpfs shared with WAL and cluster files.
        assert final - initial < 8 * 1024 * 1024
    finally:
        engine.dispose()
