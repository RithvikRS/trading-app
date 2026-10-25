"""Current evidence upgrades preserve the previous statement structure atomically."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests import test_credit_statements as statement_sql
from database_tests.test_credit_accounts import credit_accounts as credit_accounts
from database_tests.test_credit_current import currents as currents
from database_tests.test_credit_sources import credit_sources as credit_sources
from database_tests.test_credit_statements import binding
from database_tests.test_ownership import OWNER_A
from tests.test_credit_current import current_values
from tests.test_credit_statements import statement_values
from trading_db import migrate
from trading_db.credit_current import CreditCurrentTransaction
from trading_db.credit_statements import CreditStatementDatabase, new_statement_id
from trading_db.recovery import HEAD

PREVIOUS = "0021_credit_statement_evidence"


def structure(admin):
    with admin.connect() as connection:
        return (
            connection.execute(
                text("""
                SELECT table_name,column_name,data_type,is_nullable,column_default
                FROM information_schema.columns WHERE table_schema='app'
                    AND table_name IN ('credit_evidence_observations','credit_statement_values')
                ORDER BY table_name,column_name
            """)
            ).all(),
            connection.execute(
                text("""
                SELECT c.conname,pg_get_constraintdef(c.oid) FROM pg_constraint c
                WHERE c.conrelid IN ('app.credit_evidence_observations'::regclass,
                    'app.credit_statement_values'::regclass) ORDER BY c.conname
            """)
            ).all(),
            connection.execute(
                text("SELECT pg_get_functiondef('app.guard_credit_statement()'::regprocedure)")
            ).scalar_one(),
            connection.execute(
                text("""
                SELECT table_name,column_name,grantee,privilege_type
                FROM information_schema.column_privileges WHERE table_schema='app'
                    AND table_name IN ('credit_evidence_observations','credit_statement_values')
                ORDER BY table_name,column_name,grantee,privilege_type
            """)
            ).all(),
        )


@pytest.mark.parametrize(
    "interruption",
    [
        "ADD COLUMN statement_child_kind",
        "CREATE TABLE app.credit_current_values",
        "CREATE OR REPLACE FUNCTION app.guard_credit_statement()",
        "GRANT INSERT (owner_id,observation_id,revision,as_of_date",
    ],
)
def test_upgrade_failure_preserves_populated_statement_schema(
    credit_sources, database, monkeypatch, interruption
):
    sources, accounts, admin = credit_sources
    url, project = database
    migrate.apply(url(), project, direction="downgrade", target=PREVIOUS)
    stream, account = binding(sources, accounts)
    store = CreditStatementDatabase(url("runtime"), project)
    try:
        root = new_statement_id()
        with store.transaction(OWNER_A) as unit:
            saved = unit.record(root, stream, 1, statement_values())
            corrected = unit.record(root, stream, 1, statement_values(), expected_revision=1)
        baseline = structure(admin)
        from alembic.operations import Operations

        original = Operations.execute

        def interrupted(self, statement, *args, **kwargs):
            result = original(self, statement, *args, **kwargs)
            if interruption in str(statement):
                raise RuntimeError("Synthetic current migration interruption")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(Operations, "execute", interrupted)
            with pytest.raises(RuntimeError, match="Synthetic"):
                migrate.apply(url(), project)
        assert migrate.revision(url(), project) == PREVIOUS
        assert structure(admin) == baseline
        with admin.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT to_regclass('app.credit_current_values')")
                ).scalar_one()
                is None
            )
        migrate.apply(url(), project)
        migrate.apply(url(), project)
        assert migrate.revision(url(), project) == HEAD
        with store.transaction(OWNER_A) as unit:
            assert unit.history(root) == (corrected, saved)
            assert unit.record(root, stream, 1, statement_values()) == saved
            current = CreditCurrentTransaction(unit._unit)
            assert current.list(account) == ()
        with admin.connect() as connection:
            assert (
                connection.execute(
                    text("""
                SELECT count(*) FROM app.credit_evidence_observations
                WHERE statement_child_kind='statement' AND current_child_kind IS NULL
            """)
                ).scalar_one()
                == 2
            )
    finally:
        store.close()


def test_empty_downgrade_restores_original_statement_contract(credit_sources, database):
    sources, accounts, admin = credit_sources
    url, project = database
    migrate.apply(url(), project, direction="downgrade", target=PREVIOUS)
    baseline = structure(admin)
    migrate.apply(url(), project)
    migrate.apply(url(), project, direction="downgrade", target=PREVIOUS)
    assert structure(admin) == baseline
    stream, account = binding(sources, accounts)
    params = statement_sql.parameters(stream, account)
    for query, supplied in (
        (statement_sql.PARENT, params),
        (statement_sql.CHILD, params),
        (statement_sql.PARENT, params | {"kind": "current"}),
    ):
        with pytest.raises(DBAPIError), admin.begin() as connection:
            connection.execute(text(query), supplied)
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT to_regclass('app.credit_current_values')")).scalar_one()
            is None
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM app.credit_evidence_observations")
            ).scalar_one()
            == 0
        )
    migrate.apply(url(), project)
    assert migrate.revision(url(), project) == HEAD


@pytest.mark.parametrize("kind", ["statement", "current", "mixed"])
def test_populated_downgrade_denies_without_changes(currents, database, kind):
    store, sources, accounts, admin = currents
    stream, _ = binding(sources, accounts)
    with store.transaction(OWNER_A) as unit:
        if kind in {"current", "mixed"}:
            unit.record(new_statement_id(), stream, 1, current_values())
        if kind in {"statement", "mixed"}:
            from trading_db.credit_statements import CreditStatementTransaction

            CreditStatementTransaction(unit._unit).record(
                new_statement_id(), stream, 1, statement_values()
            )
    baseline = structure(admin)
    url, project = database
    with pytest.raises(DBAPIError, match="forward migration"):
        migrate.apply(url(), project, direction="downgrade", target=PREVIOUS)
    assert migrate.revision(url(), project) == HEAD and structure(admin) == baseline
    with admin.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM app.credit_evidence_observations")
        ).scalar_one() == (2 if kind == "mixed" else 1)
