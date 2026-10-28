"""Encrypted existing-source recovery preserves historical bank mapping transitions."""

import copy
import json
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from database_tests.test_accounts import accounts as accounts
from database_tests.test_bank_mappings import command, history, save, seed_mapping
from database_tests.test_ownership import OWNER_A, OWNER_B
from database_tests.test_preferences import sql
from trading_db import migrate, recovery
from trading_db.account_keys import ReferenceKeys
from trading_db.accounts import AccountDatabase
from trading_db.bank_mappings import BankMappingUnavailable
from trading_db.connections import DatabaseFailure, engine_for
from trading_db.local import disposable


def test_encrypted_recovery_preserves_mapping_history_replay_and_separate_reference_keys(
    accounts, database
):
    store, _ = accounts
    first, second, source = seed_mapping(store)
    initial = save(store, command(source, first))
    correction = save(store, command(source, second, 1))
    unlink = save(store, command(source, None, 2))
    with store.transaction(OWNER_A) as unit:
        unit.archive(first.id, expected_revision=1)
        unit.archive(second.id, expected_revision=1)
    sbi_first, _, sbi_source = seed_mapping(store, institution="sbi", currencies=("USD", "INR"))
    sbi_saved = save(store, command(sbi_source, sbi_first))
    other_first, _, other_source = seed_mapping(store, OWNER_B)
    other_saved = save(store, command(other_source, other_first), OWNER_B)
    before = history(store, source)
    url, project = database
    recovery_key = Fernet.generate_key()
    # Identifier encryption keys remain a separate restore input; mapping routes need none.
    reference_keys = ReferenceKeys({1: b"a" * 32}, 1)
    with pytest.raises(DatabaseFailure):
        recovery.export_snapshot(url("bootstrap"), project, recovery_key)
    encrypted = recovery.export_snapshot(
        url("bootstrap"), project, recovery_key, identifier_keys=reference_keys
    )
    assert str(source.id).encode() not in encrypted
    assert b"SYNTHETIC-BANK-MAPPING" not in encrypted
    payload = json.loads(Fernet(recovery_key).decrypt(encrypted))
    assert "auth_sessions" not in payload["rows"]
    assert "auth_admissions" not in payload["rows"]
    # Do not pin schema HEAD or archive FORMAT: this feature uses existing inventory.
    tables = (
        "financial_accounts",
        "account_currencies",
        "source_accounts",
        "source_account_mappings",
    )
    original_rows = recovery.decode_snapshot(encrypted, recovery_key)
    with disposable() as target:
        migrate.apply(target.url("migrator"), target.project)
        admin = engine_for(target.url("bootstrap"), migration=True)
        restored = AccountDatabase(target.url("runtime"), target.project, reference_keys)
        try:
            for keys in [None, ReferenceKeys({1: b"z" * 32}, 1)]:
                with pytest.raises(DatabaseFailure):
                    recovery.restore_snapshot(
                        target.url("bootstrap"),
                        target.project,
                        encrypted,
                        recovery_key,
                        identifier_keys=keys,
                    )
                assert sql(admin, "SELECT count(*) FROM app.owners")[0][0] == 0
            counts = recovery.restore_snapshot(
                target.url("bootstrap"),
                target.project,
                encrypted,
                recovery_key,
                identifier_keys=reference_keys,
            )
            assert counts["source_accounts"] == 3
            assert counts["source_account_mappings"] == 5
            assert counts["auth_sessions"] == 0
            assert sql(admin, "SELECT count(*) FROM app.auth_revocations")[0][0] == 3
            assert history(restored, source) == before
            assert save(restored, command(source, first)) == initial
            assert save(restored, command(source, second, 1)) == correction
            assert save(restored, command(source, None, 2)) == unlink
            assert history(restored, source).head == unlink
            assert save(restored, command(sbi_source, sbi_first)) == sbi_saved
            assert save(restored, command(other_source, other_first), OWNER_B) == other_saved
            with pytest.raises(BankMappingUnavailable):
                save(restored, command(source, first, 3))
            with pytest.raises(BankMappingUnavailable):
                save(restored, command(other_source, other_first))
            with restored.transaction(OWNER_A) as unit:
                assert unit.source("hdfc_statement", "SYNTHETIC-BANK-MAPPING").id == source.id
                assert unit.get(first.id).archived_at is not None
                assert unit.get(second.id).archived_at is not None
                assert unit.get(sbi_first.id).definition.currencies == ("INR", "USD")
            round_trip = recovery.decode_snapshot(
                recovery.export_snapshot(
                    target.url("bootstrap"),
                    target.project,
                    recovery_key,
                    identifier_keys=reference_keys,
                ),
                recovery_key,
            )
            for table in tables:
                actual = sorted(json.dumps(row, sort_keys=True) for row in round_trip[table])
                expected = sorted(json.dumps(row, sort_keys=True) for row in original_rows[table])
                assert actual == expected
        finally:
            restored.close()
            admin.dispose()


def test_broken_mapping_chain_or_foreign_target_rolls_back_entire_restore(accounts, database):
    store, _ = accounts
    first, second, source = seed_mapping(store)
    save(store, command(source, first))
    save(store, command(source, second, 1))
    save(store, command(source, None, 2))
    foreign, _, _ = seed_mapping(store, OWNER_B)
    url, project = database
    recovery_key = Fernet.generate_key()
    reference_keys = ReferenceKeys({1: b"a" * 32}, 1)
    encrypted = recovery.export_snapshot(
        url("bootstrap"), project, recovery_key, identifier_keys=reference_keys
    )
    original = json.loads(Fernet(recovery_key).decrypt(encrypted))
    with disposable() as target:
        migrate.apply(target.url("migrator"), target.project)
        admin = engine_for(target.url("bootstrap"), migration=True)
        try:
            for defect in [
                "predecessor",
                "missing_predecessor",
                "foreign_target",
                "missing_target",
            ]:
                damaged = copy.deepcopy(original)
                rows = damaged["rows"]["source_account_mappings"]
                correction = next(row for row in rows if row["revision"] == 2)
                if defect == "predecessor":
                    correction["previous_revision"] = None
                elif defect == "missing_predecessor":
                    rows.remove(next(row for row in rows if row["revision"] == 1))
                else:
                    correction["account_id"] = str(
                        foreign.id if defect == "foreign_target" else uuid4()
                    )
                broken = Fernet(recovery_key).encrypt(json.dumps(damaged).encode())
                with pytest.raises(DatabaseFailure):
                    recovery.restore_snapshot(
                        target.url("bootstrap"),
                        target.project,
                        broken,
                        recovery_key,
                        identifier_keys=reference_keys,
                    )
                for table in [
                    "owners",
                    "financial_accounts",
                    "source_accounts",
                    "source_account_mappings",
                ]:
                    assert sql(admin, f"SELECT count(*) FROM app.{table}")[0][0] == 0
            counts = recovery.restore_snapshot(
                target.url("bootstrap"),
                target.project,
                encrypted,
                recovery_key,
                identifier_keys=reference_keys,
            )
            assert counts["source_account_mappings"] == 3
        finally:
            admin.dispose()
