"""Existing version-2 evidence/event preservation and transactional schema changes."""

import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_accounts import definition, seed
from database_tests.test_imports import batch, candidate
from database_tests.test_ownership import OWNER_A
from trading_db import migrate
from trading_db.account_keys import ReferenceKeys
from trading_db.accounts import AccountDatabase
from trading_db.connections import engine_for
from trading_db.events import EventTransaction
from trading_db.import_contracts import ObservationDefinition, StagedValue
from trading_db.imports import ImportDatabase, ImportTransaction, canonical
from trading_db.recovery import HEAD


def test_legacy_event_digest_and_values_survive_upgrade_failure_and_repeated_upgrade(
    database, monkeypatch
):
    url, project = database
    migrate.apply(url(), project, target="0009_financial_events")
    admin = engine_for(url("bootstrap"), migration=True)
    accounts = AccountDatabase(url("runtime"), project, ReferenceKeys({1: b"a" * 32}, 1))
    observation_id, batch_id, row_id, event_id = (uuid4() for _ in range(4))
    legacy = batch(
        candidate(values=(StagedValue(role="net_cash", source="12.30", currency="INR"),))
    )
    digest = hashlib.sha256(canonical(legacy, 2).encode()).hexdigest()
    try:
        with admin.begin() as connection:
            connection.execute(
                text("INSERT INTO app.owners (id,is_active) VALUES (:owner,true)"),
                dict(owner=OWNER_A),
            )
        with accounts.transaction(OWNER_A) as unit:
            account = unit.create(definition())
            source = unit.source("hdfc_statement", "FAKE-LEGACY")
            unit.map(source.id, account.id, expected_revision=0)
            unit._execute(
                "INSERT INTO app.source_observations (owner_id,id,source_id,digest,"
                "digest_algorithm,coverage) VALUES (:owner,:id,:source,:digest,'sha256_v1',"
                "'unknown')",
                id=observation_id,
                source=source.id,
                digest="a" * 64,
            )
            unit._execute(
                "INSERT INTO app.import_batches (owner_id,id,observation_id,revision,"
                "normalizer,normalizer_version,normalized_digest,row_count,contract_version) "
                "VALUES (:owner,:id,:observation,1,'synthetic','1',:digest,1,2)",
                id=batch_id,
                observation=observation_id,
                digest=digest,
            )
            unit._execute(
                "INSERT INTO app.staged_rows (owner_id,id,batch_id,occurrence,kind,"
                "posting_state,booking_date,value_count) VALUES (:owner,:id,:batch,1,"
                "'cash_movement','posted','2026-10-24',1)",
                id=row_id,
                batch=batch_id,
            )
            unit._execute(
                "INSERT INTO app.staged_values (owner_id,row_id,role,source,amount,currency) "
                "VALUES (:owner,:id,'net_cash','12.30',12.30,'INR')",
                id=row_id,
            )
            unit._execute(
                "INSERT INTO app.review_decisions (owner_id,row_id,revision,action,reason,"
                "source_id,account_mapping_revision) VALUES (:owner,:id,1,'include',"
                "'reviewed',:source,1)",
                id=row_id,
                source=source.id,
            )
            unit._execute(
                "INSERT INTO app.financial_events (owner_id,id,revision,source_row_id,"
                "source_review_revision,account_id,kind,posting_state,booking_date,"
                "value_count) VALUES (:owner,:id,1,:row,1,:account,'cash_movement','posted',"
                "'2026-10-24',1)",
                id=event_id,
                row=row_id,
                account=account.id,
            )
            unit._execute(
                "INSERT INTO app.event_components (owner_id,event_id,revision,role,source,"
                "amount,currency) VALUES (:owner,:id,1,'net_cash','12.30',12.30,'INR')",
                id=event_id,
            )
            unit._execute(
                "INSERT INTO app.cash_movements (owner_id,event_id,revision,account_id,"
                "currency,amount) VALUES (:owner,:id,1,:account,'INR',12.30)",
                id=event_id,
                account=account.id,
            )
        from alembic.operations import Operations

        original = Operations.execute

        def fail(self, sql, *args, **kwargs):
            result = original(self, sql, *args, **kwargs)
            if "CREATE TABLE app.lot_components" in str(sql):
                raise RuntimeError("Synthetic migration interruption")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(Operations, "execute", fail)
            with pytest.raises(RuntimeError):
                migrate.apply(url(), project)
        assert migrate.revision(url(), project) == "0009_financial_events"
        with admin.connect() as connection:
            assert (
                connection.execute(text("SELECT count(*) FROM app.financial_events")).scalar_one()
                == 1
            )
            assert connection.execute(text("SELECT to_regclass('app.lots')")).scalar_one() is None
        migrate.apply(url(), project)
        migrate.apply(url(), project)
        migrate.apply(url(), project, direction="downgrade", target="0009_financial_events")
        migrate.apply(url(), project)
        store = ImportDatabase(url("runtime"), project)
        try:
            with store.transaction(OWNER_A) as unit:
                assert unit.get_batch(batch_id).definition == legacy
                assert unit.stage(observation_id, legacy, expected_revision=1).id == batch_id
                events = EventTransaction(unit._accounts._unit)
                preserved = events.get(event_id)
                assert preserved.status == "active" and preserved.correction_reason is None
                assert preserved.components[0].source == "12.30"
                assert events.record(row_id, expected_review_revision=1) == preserved
                updated = unit.stage(
                    observation_id,
                    batch(
                        candidate(
                            values=(StagedValue(role="net_cash", source="12.31", currency="INR"),)
                        ),
                        version="2",
                    ),
                    expected_revision=1,
                )
                row = unit.rows(updated.id)[0]
                unit.decide(row.id, "include", expected_revision=0)
                assert (
                    events.correct(
                        event_id,
                        row.id,
                        expected_revision=1,
                        expected_review_revision=1,
                        reason="source_correction",
                    ).revision
                    == 2
                )
        finally:
            store.close()
        with admin.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT normalized_digest,contract_version FROM app.import_batches WHERE id=:id"
                ),
                dict(id=batch_id),
            ).one() == (digest, 2)
            assert (
                connection.execute(
                    text("SELECT source FROM app.event_components WHERE revision=1")
                ).scalar_one()
                == "12.30"
            )
        with pytest.raises(DBAPIError):
            migrate.apply(url(), project, direction="downgrade", target="0009_financial_events")
        assert migrate.revision(url(), project) == HEAD
        with admin.connect() as connection:
            assert (
                connection.execute(text("SELECT count(*) FROM app.financial_events")).scalar_one()
                == 2
            )
    finally:
        accounts.close()
        admin.dispose()


@pytest.mark.parametrize("version", (1, 2))
@pytest.mark.parametrize("field", ("acquisition_date", "cancellation", "discount_amount"))
def test_legacy_contracts_reject_new_metadata_even_during_restore(accounts, version, field):
    store, admin = accounts
    _, source = seed(store)
    with store.transaction(OWNER_A) as unit:
        evidence = ImportTransaction(unit._unit).observation(
            source.id, ObservationDefinition(digest="a" * 64, coverage="unknown")
        )
    batch_id, row_id = uuid4(), uuid4()
    with (
        pytest.raises(DBAPIError, match="Evidence exceeds its versioned contract"),
        admin.begin() as connection,
    ):
        connection.execute(
            text(
                "INSERT INTO app.import_batches (owner_id,id,observation_id,revision,"
                "normalizer,normalizer_version,normalized_digest,row_count,contract_version) "
                "VALUES (:owner,:id,:observation,1,'synthetic','1',:digest,1,:version)"
            ),
            dict(
                owner=OWNER_A,
                id=batch_id,
                observation=evidence.id,
                digest="a" * 64,
                version=version,
            ),
        )
        connection.execute(
            text(
                "INSERT INTO app.staged_rows (owner_id,id,batch_id,occurrence,kind,"
                "as_of_date,booking_date,acquisition_date,value_count) VALUES (:owner,:id,"
                ":batch,1,:kind,'2026-10-24','2026-10-24',:acquisition,:count)"
            ),
            dict(
                owner=OWNER_A,
                id=row_id,
                batch=batch_id,
                kind="cancellation" if field == "cancellation" else "lot_remaining",
                acquisition="2026-09-01" if field == "acquisition_date" else None,
                count=1 if field == "discount_amount" else 0,
            ),
        )
        if field == "discount_amount":
            connection.execute(
                text(
                    "INSERT INTO app.staged_values (owner_id,row_id,role,source,amount,"
                    "currency) VALUES (:owner,:row,'discount_amount','1',1,'INR')"
                ),
                dict(owner=OWNER_A, row=row_id),
            )
