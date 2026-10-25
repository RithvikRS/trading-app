"""Credit source migration is transactional and never silently discards lineage."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_credit_accounts import create
from database_tests.test_credit_accounts import credit_accounts as credit_accounts
from database_tests.test_credit_sources import credit_sources as credit_sources
from database_tests.test_credit_sources import source
from database_tests.test_ownership import OWNER_A
from trading_db import migrate
from trading_db.connections import engine_for
from trading_db.recovery import HEAD


def test_source_migration_atomic_repeatable_empty_round_trip(database, monkeypatch):
    url, project = database
    previous = "0019_credit_billing_accounts"
    migrate.apply(url(), project, target=previous)
    admin = engine_for(url("bootstrap"), migration=True)
    try:
        with admin.begin() as connection:
            connection.execute(
                text("INSERT INTO app.owners (id) VALUES (:owner)"), dict(owner=OWNER_A)
            )
        from alembic.operations import Operations

        execute = Operations.execute

        def fail(self, statement, *args, **kwargs):
            result = execute(self, statement, *args, **kwargs)
            if "CREATE TABLE app.credit_source_handles" in str(statement):
                raise RuntimeError("Synthetic migration interruption.")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(Operations, "execute", fail)
            with pytest.raises(RuntimeError, match="Synthetic"):
                migrate.apply(url(), project)
        assert migrate.revision(url(), project) == previous
        with admin.connect() as connection:
            for table in ("credit_source_handles", "credit_source_account_mappings"):
                assert (
                    connection.execute(
                        text("SELECT to_regclass(:name)"), dict(name=f"app.{table}")
                    ).scalar_one()
                    is None
                )
            assert connection.execute(text("SELECT count(*) FROM app.owners")).scalar_one() == 1
        migrate.apply(url(), project)
        migrate.apply(url(), project)
        assert migrate.revision(url(), project) == HEAD
        migrate.apply(url(), project, direction="downgrade", target=previous)
        migrate.apply(url(), project)
        with admin.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM app.owners")).scalar_one() == 1
            assert (
                connection.execute(
                    text("SELECT count(*) FROM app.credit_source_handles")
                ).scalar_one()
                == 0
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM app.credit_source_account_mappings")
                ).scalar_one()
                == 0
            )
    finally:
        admin.dispose()


@pytest.mark.parametrize("state", ["unmapped", "linked", "unlinked", "archived"])
def test_nonempty_credit_source_history_blocks_downgrade(credit_sources, database, state):
    store, accounts, _ = credit_sources
    item = source(store)
    account = create(accounts)
    with store.transaction(OWNER_A) as unit:
        if state != "unmapped":
            unit.map(item.id, account.id, expected_revision=0)
        if state == "unlinked":
            unit.map(item.id, None, expected_revision=1)
        history = unit.history(item.id)
    if state == "archived":
        with accounts.transaction(OWNER_A) as unit:
            unit.archive(account.id, expected_revision=1)
    url, project = database
    with pytest.raises(DBAPIError, match="forward migration"):
        migrate.apply(url(), project, direction="downgrade", target="0019_credit_billing_accounts")
    assert migrate.revision(url(), project) == HEAD
    with store.transaction(OWNER_A) as unit:
        assert unit.get(item.id) == item and unit.history(item.id) == history
