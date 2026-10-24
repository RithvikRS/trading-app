"""Legacy normalization, transactional migration and SQL timestamp bounds."""

import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_accounts import seed
from database_tests.test_imports import batch, candidate
from database_tests.test_ownership import OWNER_A
from trading_db import migrate
from trading_db.import_contracts import ObservationDefinition, StagedValue
from trading_db.imports import ImportTransaction, canonical
from trading_db.recovery import HEAD
from trading_db.snapshots import SnapshotDatabase


def test_contract_three_snapshot_survives_interrupted_upgrade_and_legacy_only_downgrade(
    accounts, database, monkeypatch
):
    store, admin = accounts
    url, project = database
    migrate.apply(url(), project, direction="downgrade", target="0010_lots_corrections")
    with admin.connect() as connection:
        body = connection.execute(
            text("SELECT pg_get_functiondef('app.guard_staging_contract()'::regprocedure)")
        ).scalar_one()
        assert "NEW.contract_version<>3" in body and "discount_amount" in body
    account, source = seed(store)
    observation_id, batch_id, row_id = uuid4(), uuid4(), uuid4()
    legacy = batch(
        candidate(
            kind="cash_snapshot",
            as_of_date="2026-10-24",
            booking_date=None,
            values=(StagedValue(role="net_cash", source="12.30", currency="INR"),),
        )
    )
    digest = hashlib.sha256(canonical(legacy, 3).encode()).hexdigest()
    with store.transaction(OWNER_A) as unit:
        unit._execute(
            "INSERT INTO app.source_observations (owner_id,id,source_id,digest,"
            "digest_algorithm,coverage) VALUES (:owner,:id,:source,:digest,'sha256_v1',"
            "'unknown')",
            id=observation_id,
            source=source.id,
            digest="a" * 64,
        )
        unit._execute(
            "INSERT INTO app.import_batches (owner_id,id,observation_id,revision,normalizer,"
            "normalizer_version,normalized_digest,row_count,contract_version) VALUES (:owner,"
            ":id,:observation,1,'synthetic','1',:digest,1,3)",
            id=batch_id,
            observation=observation_id,
            digest=digest,
        )
        unit._execute(
            "INSERT INTO app.staged_rows (owner_id,id,batch_id,occurrence,kind,as_of_date,"
            "value_count) VALUES (:owner,:id,:batch,1,'cash_snapshot','2026-10-24',1)",
            id=row_id,
            batch=batch_id,
        )
        unit._execute(
            "INSERT INTO app.staged_values (owner_id,row_id,role,source,amount,currency) "
            "VALUES (:owner,:row,'net_cash','12.30',12.30,'INR')",
            row=row_id,
        )
        unit._execute(
            "INSERT INTO app.review_decisions (owner_id,row_id,revision,action,reason,"
            "source_id,account_mapping_revision) VALUES (:owner,:row,1,'include','reviewed',"
            ":source,1)",
            row=row_id,
            source=source.id,
        )
    from alembic.operations import Operations

    execute = Operations.execute

    def fail(self, sql, *args, **kwargs):
        result = execute(self, sql, *args, **kwargs)
        if "CREATE TABLE app.snapshot_components" in str(sql):
            raise RuntimeError("Synthetic migration interruption.")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Operations, "execute", fail)
        with pytest.raises(RuntimeError):
            migrate.apply(url(), project)
    assert migrate.revision(url(), project) == "0010_lots_corrections"
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT to_regclass('app.snapshot_records')")).scalar_one()
            is None
        )
        assert (
            connection.execute(text("SELECT count(*) FROM app.review_decisions")).scalar_one() == 1
        )
    migrate.apply(url(), project)
    migrate.apply(url(), project)
    migrate.apply(url(), project, direction="downgrade", target="0010_lots_corrections")
    migrate.apply(url(), project)
    snapshots = SnapshotDatabase(url("runtime"), project)
    try:
        with snapshots.transaction(OWNER_A) as unit:
            assert unit._imports.get_batch(batch_id).definition == legacy
            assert unit._imports.stage(observation_id, legacy, expected_revision=1).id == batch_id
            record = unit.record(row_id, expected_review_revision=1)
            assert record.as_of_instant is record.snapshot_scope is None
            assert record.components[0].source == "12.30"
            selected = unit.select(record.id, expected_snapshot_revision=1, expected_revision=0)
            assert unit.resolve(selected.id).snapshot == record
        with admin.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT normalized_digest,contract_version FROM app.import_batches WHERE id=:id"
                ),
                dict(id=batch_id),
            ).one() == (digest, 3)
        with pytest.raises(DBAPIError):
            migrate.apply(url(), project, direction="downgrade", target="0010_lots_corrections")
        assert migrate.revision(url(), project) == HEAD
        with admin.connect() as connection:
            assert (
                connection.execute(text("SELECT count(*) FROM app.snapshot_records")).scalar_one()
                == 1
            )
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM pg_class WHERE relnamespace='app'::regnamespace AND "
                        "relkind='r' AND NOT relforcerowsecurity"
                    )
                ).scalar_one()
                == 0
            )
    finally:
        snapshots.close()


@pytest.mark.parametrize("version", (1, 2, 3))
@pytest.mark.parametrize("field", ("as_of_instant", "snapshot_scope"))
def test_legacy_contract_cannot_include_new_metadata_even_during_restore(accounts, version, field):
    store, admin = accounts
    _, source = seed(store)
    with store.transaction(OWNER_A) as unit:
        observation = ImportTransaction(unit._unit).observation(
            source.id, ObservationDefinition(digest="a" * 64, coverage="unknown")
        )
    batch_id = uuid4()
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
                observation=observation.id,
                digest="a" * 64,
                version=version,
            ),
        )
        connection.execute(
            text(
                "INSERT INTO app.staged_rows (owner_id,id,batch_id,occurrence,kind,"
                "as_of_date,as_of_instant,snapshot_scope,value_count) VALUES (:owner,:id,"
                ":batch,1,'cash_snapshot','2026-10-24',:instant,:scope,0)"
            ),
            dict(
                owner=OWNER_A,
                id=uuid4(),
                batch=batch_id,
                instant="2026-10-24T10:00:00Z" if field == "as_of_instant" else None,
                scope="native_cash" if field == "snapshot_scope" else None,
            ),
        )


@pytest.mark.parametrize(
    "value,valid",
    [
        (None, True),
        ("2026-10-24T00:30:00.120+05:30", True),
        ("2026-10-24T23:59:59.999999-14:00", True),
        ("2026-10-24T10:00:00", False),
        ("2026-10-24T10:00:00-00:00", False),
        ("2026-10-24T10:00:00+14:01", False),
        ("2026-10-24T10:00:00+05:60", False),
        ("2026-10-24T24:00:00Z", False),
        ("2026-10-24T10:00:60Z", False),
        ("2026-10-24T10:00:00.1234567Z", False),
        ("2026-10-23T10:00:00Z", False),
        ("2026-02-30T10:00:00Z", False),
    ],
)
def test_direct_sql_timestamp_validation_preserves_supported_precision(accounts, value, valid):
    store, _ = accounts
    with store.transaction(OWNER_A) as unit:
        assert (
            unit._execute(
                "SELECT app.valid_snapshot_instant(:value,DATE '2026-10-24')", value=value
            ).scalar_one()
            is valid
        )


def test_sql_instant_must_also_fit_the_supported_utc_calendar_range(accounts):
    store, _ = accounts
    with store.transaction(OWNER_A) as unit:
        for value, valid in (
            ("0001-01-01T00:00:00Z", True),
            ("0001-01-01T00:00:00+14:00", False),
            ("9999-12-31T23:59:59Z", True),
            ("9999-12-31T23:59:59-14:00", False),
        ):
            assert (
                unit._execute(
                    "SELECT app.valid_snapshot_instant(:value,CAST(:day AS date))",
                    value=value,
                    day=value[:10],
                ).scalar_one()
                is valid
            )
