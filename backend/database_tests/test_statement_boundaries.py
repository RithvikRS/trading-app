"""Statement metadata is immutable, owner-scoped and checked by PostgreSQL too."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_accounts import seed
from database_tests.test_imports import batch, observation
from database_tests.test_ownership import OWNER_A, OWNER_B, set_owner
from tests.test_statement_contracts import checkpoint
from trading_db.import_contracts import ObservationDefinition, StagedValue
from trading_db.imports import ImportTransaction, ImportUnavailable
from trading_db.snapshots import SnapshotTransaction, SnapshotUnavailable


def source_period(**changes):
    return observation().model_copy(update={"period_start": "2026-10-24", **changes})


def test_statement_basis_and_boundaries_round_trip_without_posting_activity(accounts):
    store, admin = accounts
    account, source = seed(store)
    with store.transaction(OWNER_A) as unit:
        imports = ImportTransaction(unit._unit)
        observed = imports.observation(source.id, source_period())
        definition = batch(
            checkpoint(),
            checkpoint(
                occurrence=2,
                reconciliation_boundary="after_period",
                values=(StagedValue(role="net_cash", source="125.00", currency="INR"),),
            ),
        ).model_copy(update={"cash_date_basis": "booking"})
        staged = imports.stage(observed.id, definition, expected_revision=0)
        assert imports.get_batch(staged.id).definition == definition
        assert imports.stage(observed.id, definition, expected_revision=0) == staged
        rows = imports.rows(staged.id)
        snapshots = SnapshotTransaction(unit._unit)
        records = []
        for row in rows:
            imports.decide(row.id, "include", expected_revision=0)
            records.append(snapshots.record(row.id, expected_review_revision=1))
        assert [record.reconciliation_boundary for record in records] == [
            "before_period",
            "after_period",
        ]
        assert all(record.cash_date_basis == "booking" for record in records)
        choice = snapshots.select(records[1].id, expected_snapshot_revision=1, expected_revision=0)
        assert snapshots.resolve(choice.id).snapshot == records[1]
        assert records[1].components[0].source == "125.00"
        assert snapshots.list(account.id)
    with store.transaction(OWNER_B) as unit:
        assert ImportTransaction(unit._unit).get_batch(staged.id) is None
        assert SnapshotTransaction(unit._unit).get(records[0].id) is None
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM app.financial_events")).scalar_one() == 0
        )
        assert connection.execute(text("SELECT count(*) FROM app.cash_movements")).scalar_one() == 0


@pytest.mark.parametrize("basis", ("value", "settlement"))
def test_changed_basis_requires_new_normalization_and_invalidates_old_review(accounts, basis):
    store, _ = accounts
    _, source = seed(store)
    with store.transaction(OWNER_A) as unit:
        imports = ImportTransaction(unit._unit)
        observed = imports.observation(source.id, source_period())
        original = batch(checkpoint()).model_copy(update={"cash_date_basis": "booking"})
        first = imports.stage(observed.id, original, expected_revision=0)
        row = imports.rows(first.id)[0]
        imports.decide(row.id, "include", expected_revision=0)
    with pytest.raises(ImportUnavailable), store.transaction(OWNER_A) as unit:
        ImportTransaction(unit._unit).stage(
            observed.id, original.model_copy(update={"cash_date_basis": basis}), expected_revision=1
        )
    with store.transaction(OWNER_A) as unit:
        imports = ImportTransaction(unit._unit)
        second = imports.stage(
            observed.id,
            original.model_copy(update={"normalizer_version": "2", "cash_date_basis": basis}),
            expected_revision=1,
        )
        assert second.revision == 2 and second.definition.cash_date_basis == basis
        assert imports.get_row(row.id).status == "superseded"
        assert imports.get_batch(first.id).definition.cash_date_basis == "booking"


@pytest.mark.parametrize("coverage", ("snapshot", "unknown"))
def test_cash_basis_cannot_invent_an_activity_period(accounts, coverage):
    store, _ = accounts
    _, source = seed(store)
    with store.transaction(OWNER_A) as unit:
        observed = ImportTransaction(unit._unit).observation(
            source.id, source_period(coverage=coverage)
        )
    with pytest.raises(ImportUnavailable), store.transaction(OWNER_A) as unit:
        ImportTransaction(unit._unit).stage(
            observed.id,
            batch(checkpoint()).model_copy(update={"cash_date_basis": "booking"}),
            expected_revision=0,
        )


@pytest.mark.parametrize(
    "boundary,day", (("before_period", "2026-10-23"), ("after_period", "2026-10-25"))
)
def test_wrong_boundary_date_rolls_back_the_whole_batch(accounts, boundary, day):
    store, admin = accounts
    _, source = seed(store)
    with store.transaction(OWNER_A) as unit:
        observed = ImportTransaction(unit._unit).observation(source.id, source_period())
    with pytest.raises(ImportUnavailable), store.transaction(OWNER_A) as unit:
        ImportTransaction(unit._unit).stage(
            observed.id,
            batch(
                checkpoint(),
                checkpoint(occurrence=2, reconciliation_boundary=boundary, as_of_date=day),
            ),
            expected_revision=0,
        )
    with admin.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM app.import_batches")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM app.staged_rows")).scalar_one() == 0


@pytest.mark.parametrize(
    "other_boundary,instant",
    ((None, None), ("before_period", None), ("after_period", "2026-10-24T00:00:00Z")),
)
def test_boundary_labels_do_not_hide_a_real_or_ambiguous_same_point_conflict(
    accounts, other_boundary, instant
):
    store, _ = accounts
    _, source = seed(store)
    with store.transaction(OWNER_A) as unit:
        imports = ImportTransaction(unit._unit)
        observed = imports.observation(source.id, source_period())
        staged = imports.stage(
            observed.id,
            batch(
                checkpoint(as_of_instant=instant),
                checkpoint(
                    occurrence=2,
                    reconciliation_boundary=other_boundary,
                    as_of_instant=instant,
                    values=(StagedValue(role="net_cash", source="125.00", currency="INR"),),
                ),
            ),
            expected_revision=0,
        )
        snapshots = SnapshotTransaction(unit._unit)
        records = []
        for row in imports.rows(staged.id):
            imports.decide(row.id, "include", expected_revision=0)
            records.append(snapshots.record(row.id, expected_review_revision=1))
    with pytest.raises(SnapshotUnavailable), store.transaction(OWNER_A) as unit:
        SnapshotTransaction(unit._unit).select(
            records[0].id, expected_snapshot_revision=1, expected_revision=0
        )


@pytest.mark.parametrize(
    "field,value",
    (
        ("reconciliation_boundary", "automatic"),
        ("as_of_date", "2026-10-25"),
        ("snapshot_scope", None),
        ("kind", "cash_movement"),
    ),
)
def test_direct_sql_cannot_bypass_boundary_shape_or_period(accounts, field, value):
    store, _ = accounts
    _, source = seed(store)
    with store.transaction(OWNER_A) as unit:
        imports = ImportTransaction(unit._unit)
        observed = imports.observation(source.id, source_period())
        # A batch header alone cannot commit; the failed row rejects first and rolls it back.
    fields = dict(
        reconciliation_boundary="before_period",
        as_of_date="2026-10-24",
        snapshot_scope="native_cash",
        kind="cash_snapshot",
    )
    fields[field] = value
    with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        batch_id = uuid4()
        connection.execute(
            text(
                "INSERT INTO app.import_batches (owner_id,id,observation_id,revision,normalizer,"
                "normalizer_version,normalized_digest,row_count,contract_version) VALUES "
                "(:owner,:id,:observation,1,'synthetic','1',:digest,1,5)"
            ),
            dict(owner=OWNER_A, id=batch_id, observation=observed.id, digest="a" * 64),
        )
        connection.execute(
            text(
                "INSERT INTO app.staged_rows (owner_id,id,batch_id,occurrence,kind,as_of_date,"
                "snapshot_scope,reconciliation_boundary,value_count) VALUES "
                "(:owner,:id,:batch,1,:kind,:as_of_date,:snapshot_scope,:reconciliation_boundary,0)"
            ),
            dict(owner=OWNER_A, id=uuid4(), batch=batch_id, **fields),
        )


def test_unknown_period_cannot_supply_a_statement_boundary(accounts):
    store, _ = accounts
    _, source = seed(store)
    with store.transaction(OWNER_A) as unit:
        observed = ImportTransaction(unit._unit).observation(
            source.id, ObservationDefinition(digest="a" * 64, coverage="unknown")
        )
    with pytest.raises(ImportUnavailable), store.transaction(OWNER_A) as unit:
        ImportTransaction(unit._unit).stage(observed.id, batch(checkpoint()), expected_revision=0)


def test_new_metadata_has_narrow_grants_and_cannot_rewrite_retained_meaning(accounts):
    store, admin = accounts
    _, source = seed(store)
    with store.transaction(OWNER_A) as unit:
        imports = ImportTransaction(unit._unit)
        observed = imports.observation(source.id, source_period())
        imports.stage(
            observed.id,
            batch(checkpoint()).model_copy(update={"cash_date_basis": "booking"}),
            expected_revision=0,
        )
    for table, column, value in (
        ("import_batches", "cash_date_basis", "value"),
        ("staged_rows", "reconciliation_boundary", "after_period"),
    ):
        with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
            set_owner(connection, OWNER_A)
            connection.execute(text(f"UPDATE app.{table} SET {column}=:value"), dict(value=value))
        with admin.connect() as connection:
            for role, operation, permitted in (
                ("trading_runtime", "INSERT", True),
                ("trading_runtime", "SELECT", True),
                ("trading_runtime", "UPDATE", False),
                ("trading_auth", "SELECT", False),
                ("trading_auth", "INSERT", False),
            ):
                assert (
                    connection.execute(
                        text("SELECT has_column_privilege(:role,:table,:column,:operation)"),
                        dict(role=role, table="app." + table, column=column, operation=operation),
                    ).scalar_one()
                    is permitted
                )
