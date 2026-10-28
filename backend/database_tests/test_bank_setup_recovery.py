"""Setup schema upgrade, encrypted recovery and historical replay after restoration."""

import copy
import json
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_bank_setup import save
from database_tests.test_ownership import OWNER_A
from database_tests.test_preferences import sql
from tests.test_bank_setup import command
from trading_api.bank_setup_contracts import BankSetupCommand
from trading_db import migrate, recovery
from trading_db.bank_setup import BankSetupTransaction
from trading_db.connections import DatabaseFailure, engine_for
from trading_db.local import disposable
from trading_db.workspace import WorkspaceDatabase


def test_setup_migration_is_atomic_repeatable_and_empty_downgrade_preserves_accounts(
    database, monkeypatch
):
    url, project = database
    migrate.apply(url(), project, target="0023_credit_entry_evidence")
    admin = engine_for(url("bootstrap"), migration=True)
    try:
        sql(admin, "INSERT INTO app.owners (id) VALUES (:id)", id=OWNER_A)
        from alembic.operations import Operations

        original = Operations.execute

        def interrupted(self, statement, *args, **kwargs):
            result = original(self, statement, *args, **kwargs)
            if "CREATE TABLE app.bank_account_setups" in str(statement):
                raise RuntimeError("Synthetic migration interruption.")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(Operations, "execute", interrupted)
            with pytest.raises(RuntimeError, match="Synthetic"):
                migrate.apply(url(), project)
        assert migrate.revision(url(), project) == "0023_credit_entry_evidence"
        assert sql(admin, "SELECT to_regclass('app.bank_account_setups')")[0][0] is None
        migrate.apply(url(), project)
        migrate.apply(url(), project)
        assert migrate.revision(url(), project) == recovery.HEAD
        migrate.apply(url(), project, direction="downgrade", target="0023_credit_entry_evidence")
        migrate.apply(url(), project)
        assert sql(admin, "SELECT count(*) FROM app.owners")[0][0] == 1
    finally:
        admin.dispose()


def test_populated_setup_refuses_downgrade(accounts, database):
    store, _ = accounts
    body = command()
    saved = save(store, body)
    url, project = database
    with pytest.raises(DBAPIError, match="forward migration"):
        migrate.apply(url(), project, direction="downgrade", target="0023_credit_entry_evidence")
    assert migrate.revision(url(), project) == recovery.HEAD
    assert save(store, body) == saved


def test_recovery_preserves_historical_declaration_and_replay_with_reordered_receipts(
    accounts, database
):
    store, _ = accounts
    body = command()
    first = save(store, body)
    second = save(store, command() | {"expected_revision": 1, "institution": "sbi"})
    with store.transaction(OWNER_A) as unit:
        unit.archive(UUID(first.account_id), expected_revision=1)
        unit._execute(
            "INSERT INTO app.account_currencies (owner_id,account_id,currency) "
            "VALUES (:owner,:account,'USD')",
            account=UUID(first.account_id),
        )
    url, project = database
    key = Fernet.generate_key()
    encrypted = recovery.export_snapshot(url("bootstrap"), project, key)
    assert body["label"].encode() not in encrypted and body["intent_id"].encode() not in encrypted
    payload = json.loads(Fernet(key).decrypt(encrypted))
    assert payload["format"] == 20
    assert "auth_sessions" not in payload["rows"]
    payload["rows"]["bank_account_setups"].reverse()
    with disposable() as target:
        migrate.apply(target.url("migrator"), target.project)
        admin = engine_for(target.url("bootstrap"), migration=True)
        workspace = WorkspaceDatabase(target.url("runtime"), target.project)
        try:
            mutations = [
                ("label", "Different"),
                ("institution", "hdfc"),
                ("currency_set", "INR,USD"),
                ("previous_revision", None),
                ("account_id", first.account_id),
                ("created_at", "infinity"),
            ]
            for field, value in mutations:
                damaged = copy.deepcopy(payload)
                damaged["rows"]["bank_account_setups"][0][field] = value
                broken = Fernet(key).encrypt(json.dumps(damaged).encode())
                with pytest.raises(DatabaseFailure):
                    recovery.restore_snapshot(target.url("bootstrap"), target.project, broken, key)
                assert sql(admin, "SELECT count(*) FROM app.owners")[0][0] == 0
            old = copy.deepcopy(payload)
            old["format"] = 19
            with pytest.raises(DatabaseFailure):
                recovery.restore_snapshot(
                    target.url("bootstrap"),
                    target.project,
                    Fernet(key).encrypt(json.dumps(old).encode()),
                    key,
                )
            restored = Fernet(key).encrypt(json.dumps(payload).encode())
            counts = recovery.restore_snapshot(
                target.url("bootstrap"), target.project, restored, key
            )
            assert counts["bank_account_setups"] == 2 and counts["auth_sessions"] == 0
            with workspace.transaction(OWNER_A) as unit:
                service = BankSetupTransaction(unit)
                assert service.create(BankSetupCommand.model_validate(body)) == first
                assert service.query().last_saved == second
            assert sql(admin, "SELECT count(*) FROM app.auth_revocations")[0][0] == 3
            with pytest.raises(DatabaseFailure):
                recovery.restore_snapshot(target.url("bootstrap"), target.project, restored, key)
        finally:
            workspace.close()
            admin.dispose()
