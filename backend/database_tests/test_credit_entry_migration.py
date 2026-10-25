"""Entry upgrades retain both prior typed evidence contracts atomically."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests import test_credit_current as current_sql
from database_tests import test_credit_statements as statement_sql
from database_tests.test_credit_accounts import credit_accounts as credit_accounts
from database_tests.test_credit_entries import entries as entries
from database_tests.test_credit_sources import credit_sources as credit_sources
from database_tests.test_credit_statements import binding
from database_tests.test_ownership import OWNER_A
from tests.test_credit_current import current_values
from tests.test_credit_entries import entry_values
from tests.test_credit_statements import statement_values
from trading_db import migrate
from trading_db.credit_current import CreditCurrentTransaction
from trading_db.credit_entries import CreditEntryTransaction
from trading_db.credit_statements import CreditStatementDatabase, CreditStatementTransaction
from trading_db.recovery import HEAD

PREVIOUS = "0022_credit_current_evidence"


def structure(admin):
    with admin.connect() as connection:
        return (
            connection.execute(
                text("""
                SELECT table_name,column_name,data_type,is_nullable,column_default
                FROM information_schema.columns WHERE table_schema='app'
                    AND table_name IN ('credit_evidence_observations',
                        'credit_statement_values','credit_current_values')
                ORDER BY table_name,column_name
            """)
            ).all(),
            connection.execute(
                text("""
                SELECT c.conname,pg_get_constraintdef(c.oid) FROM pg_constraint c
                WHERE c.conrelid IN ('app.credit_evidence_observations'::regclass,
                    'app.credit_statement_values'::regclass,'app.credit_current_values'::regclass)
                ORDER BY c.conname
            """)
            ).all(),
            connection.execute(
                text("SELECT pg_get_functiondef('app.guard_credit_statement()'::regprocedure)")
            ).scalar_one(),
            connection.execute(
                text("""
                SELECT table_name,column_name,grantee,privilege_type
                FROM information_schema.column_privileges WHERE table_schema='app'
                    AND table_name IN ('credit_evidence_observations',
                        'credit_statement_values','credit_current_values')
                ORDER BY table_name,column_name,grantee,privilege_type
            """)
            ).all(),
        )


@pytest.mark.parametrize(
    "interruption",
    [
        "ADD COLUMN entry_child_kind",
        "CREATE TABLE app.credit_entry_values",
        "CREATE OR REPLACE FUNCTION app.guard_credit_statement()",
        "GRANT INSERT (owner_id,observation_id,revision,role,treatment",
    ],
)
def test_upgrade_failure_preserves_populated_older_contracts(
    credit_sources, database, monkeypatch, interruption
):
    sources, accounts, admin = credit_sources
    url, project = database
    migrate.apply(url(), project, direction="downgrade", target=PREVIOUS)
    stream, account = binding(sources, accounts)
    store = CreditStatementDatabase(url("runtime"), project)
    try:
        roots = (uuid4(), uuid4())
        with store.transaction(OWNER_A) as unit:
            current = CreditCurrentTransaction(unit._unit)
            for target, root, values in (
                (unit, roots[0], statement_values()),
                (current, roots[1], current_values()),
            ):
                target.record(root, stream, 1, values)
                target.record(root, stream, 1, values, expected_revision=1)
            histories = (unit.history(roots[0]), current.history(roots[1]))
        baseline = structure(admin)
        from alembic.operations import Operations

        original = Operations.execute

        def interrupted(self, statement, *args, **kwargs):
            result = original(self, statement, *args, **kwargs)
            if interruption in str(statement):
                raise RuntimeError("Synthetic entry migration interruption")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(Operations, "execute", interrupted)
            with pytest.raises(RuntimeError, match="Synthetic"):
                migrate.apply(url(), project)
        assert migrate.revision(url(), project) == PREVIOUS and structure(admin) == baseline
        with admin.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT to_regclass('app.credit_entry_values')")
                ).scalar_one()
                is None
            )
        migrate.apply(url(), project)
        migrate.apply(url(), project)
        assert migrate.revision(url(), project) == HEAD
        with store.transaction(OWNER_A) as unit:
            current = CreditCurrentTransaction(unit._unit)
            assert (unit.history(roots[0]), current.history(roots[1])) == histories
            assert unit.record(roots[0], stream, 1, statement_values()) == histories[0][-1]
            assert current.record(roots[1], stream, 1, current_values()) == histories[1][-1]
            assert CreditEntryTransaction(unit._unit).list(account) == ()
            # Old writers continue to rely on their unchanged typed defaults.
            unit.record(uuid4(), stream, 1, statement_values())
            current.record(uuid4(), stream, 1, current_values())
        with admin.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM app.credit_evidence_observations "
                        "WHERE entry_child_kind IS NULL"
                    )
                ).scalar_one()
                == 6
            )
    finally:
        store.close()


def test_empty_roundtrip_restores_exact_previous_structure_and_grants(credit_sources, database):
    sources, accounts, admin = credit_sources
    url, project = database
    migrate.apply(url(), project, direction="downgrade", target=PREVIOUS)
    baseline = structure(admin)
    migrate.apply(url(), project)
    migrate.apply(url(), project, direction="downgrade", target=PREVIOUS)
    assert structure(admin) == baseline
    stream, account = binding(sources, accounts)
    for module in (statement_sql, current_sql):
        params = module.parameters(stream, account)
        for query in (module.PARENT, module.CHILD):
            with pytest.raises(DBAPIError), admin.begin() as connection:
                connection.execute(text(query), params)
        with pytest.raises(DBAPIError), admin.begin() as connection:
            module.pair(connection, params | {"kind": "entry"})
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT to_regclass('app.credit_entry_values')")).scalar_one()
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


@pytest.mark.parametrize("kind", ["statement", "current", "entry", "mixed"])
def test_populated_downgrade_denies_without_changes(entries, database, kind):
    store, sources, accounts, admin = entries
    stream, _ = binding(sources, accounts)
    with store.transaction(OWNER_A) as unit:
        for name, target, values in (
            ("entry", unit, entry_values()),
            ("statement", CreditStatementTransaction(unit._unit), statement_values()),
            ("current", CreditCurrentTransaction(unit._unit), current_values()),
        ):
            if kind in {name, "mixed"}:
                target.record(uuid4(), stream, 1, values)
    baseline = structure(admin)
    url, project = database
    with pytest.raises(DBAPIError, match="forward migration"):
        migrate.apply(url(), project, direction="downgrade", target=PREVIOUS)
    assert migrate.revision(url(), project) == HEAD and structure(admin) == baseline
    with admin.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM app.credit_evidence_observations")
        ).scalar_one() == (3 if kind == "mixed" else 1)
