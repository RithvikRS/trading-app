"""Transactional statement schema, complete structure and populated downgrade guards."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_credit_accounts import credit_accounts as credit_accounts
from database_tests.test_credit_sources import credit_sources as credit_sources
from database_tests.test_credit_statements import binding
from database_tests.test_credit_statements import statements as statements
from database_tests.test_ownership import OWNER_A
from tests.test_credit_statements import statement_values
from trading_db import migrate
from trading_db.connections import engine_for
from trading_db.credit_statements import new_statement_id
from trading_db.recovery import HEAD


def test_statement_migration_failure_repeat_and_empty_round_trip(database, monkeypatch):
    url, project = database
    previous = "0020_credit_source_mappings"
    migrate.apply(url(), project, target=previous)
    admin = engine_for(url("bootstrap"), migration=True)
    try:
        with admin.begin() as connection:
            connection.execute(text("INSERT INTO app.owners (id) VALUES (:id)"), dict(id=OWNER_A))
        from alembic.operations import Operations

        original = Operations.execute

        def interrupted(self, statement, *args, **kwargs):
            result = original(self, statement, *args, **kwargs)
            if "CREATE TABLE app.credit_statement_values" in str(statement):
                raise RuntimeError("Synthetic statement migration interruption")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(Operations, "execute", interrupted)
            with pytest.raises(RuntimeError, match="Synthetic"):
                migrate.apply(url(), project)
        assert migrate.revision(url(), project) == previous
        with admin.connect() as connection:
            for table in ("credit_evidence_observations", "credit_statement_values"):
                assert (
                    connection.execute(
                        text("SELECT to_regclass(:name)"), dict(name="app." + table)
                    ).scalar_one()
                    is None
                )
            assert not connection.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_constraint "
                    "WHERE conname='credit_mapping_binding')"
                )
            ).scalar_one()
        migrate.apply(url(), project)
        migrate.apply(url(), project)
        assert migrate.revision(url(), project) == HEAD
        migrate.apply(url(), project, direction="downgrade", target=previous)
        migrate.apply(url(), project)
        with admin.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM app.owners")).scalar_one() == 1
    finally:
        admin.dispose()


@pytest.mark.parametrize("corrected", [False, True])
def test_populated_statement_history_blocks_downgrade(statements, database, corrected):
    store, sources, accounts, _ = statements
    stream, account = binding(sources, accounts)
    root = new_statement_id()
    with store.transaction(OWNER_A) as unit:
        unit.record(root, stream, 1, statement_values())
        if corrected:
            unit.record(root, stream, 1, statement_values(), expected_revision=1)
        expected = unit.history(root)
    with accounts.transaction(OWNER_A) as unit:
        unit.archive(account, expected_revision=1)
    url, project = database
    with pytest.raises(DBAPIError, match="forward migration"):
        migrate.apply(url(), project, direction="downgrade", target="0020_credit_source_mappings")
    assert migrate.revision(url(), project) == HEAD
    with store.transaction(OWNER_A) as unit:
        assert unit.history(root) == expected
