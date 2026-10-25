"""Credit identity migration preserves data and refuses destructive downgrades."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_credit_accounts import create
from database_tests.test_credit_accounts import credit_accounts as credit_accounts
from database_tests.test_ownership import OWNER_A
from trading_db import migrate
from trading_db.connections import engine_for
from trading_db.recovery import HEAD


def test_credit_upgrade_is_atomic_repeatable_and_round_trips_when_empty(database, monkeypatch):
    url, project = database
    migrate.apply(url(), project, target="0018_indmoney_authorization")
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
            if "CREATE TABLE app.credit_billing_accounts" in str(statement):
                raise RuntimeError("Synthetic migration interruption.")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(Operations, "execute", fail)
            with pytest.raises(RuntimeError, match="Synthetic"):
                migrate.apply(url(), project)
        assert migrate.revision(url(), project) == "0018_indmoney_authorization"
        with admin.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT to_regclass('app.credit_billing_accounts')")
                ).scalar_one()
                is None
            )
            assert connection.execute(text("SELECT count(*) FROM app.owners")).scalar_one() == 1
        migrate.apply(url(), project)
        migrate.apply(url(), project)
        assert migrate.revision(url(), project) == HEAD
        migrate.apply(url(), project, direction="downgrade", target="0018_indmoney_authorization")
        migrate.apply(url(), project)
        with admin.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM app.owners")).scalar_one() == 1
            assert (
                connection.execute(
                    text("SELECT count(*) FROM app.credit_billing_accounts")
                ).scalar_one()
                == 0
            )
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM pg_class WHERE relnamespace='app'::regnamespace "
                        "AND relkind='r' AND NOT relforcerowsecurity"
                    )
                ).scalar_one()
                == 0
            )
    finally:
        admin.dispose()


@pytest.mark.parametrize("archived", [False, True])
def test_credit_records_block_downgrade_and_remain_unchanged(credit_accounts, database, archived):
    store, admin = credit_accounts
    account = create(store)
    if archived:
        with store.transaction(OWNER_A) as unit:
            account = unit.archive(account.id, expected_revision=1)
    url, project = database
    with pytest.raises(DBAPIError, match="forward migration"):
        migrate.apply(url(), project, direction="downgrade", target="0018_indmoney_authorization")
    assert migrate.revision(url(), project) == HEAD
    with store.transaction(OWNER_A) as unit:
        assert unit.get(account.id) == account
    with admin.connect() as connection:
        assert connection.execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class "
                "WHERE oid='app.credit_billing_accounts'::regclass"
            )
        ).scalar_one()
