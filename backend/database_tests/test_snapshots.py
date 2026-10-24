"""Snapshot selection cannot fabricate activity, merge evidence or hide conflicts."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_events import events as events
from database_tests.test_events import seed
from database_tests.test_imports import candidate
from database_tests.test_lots_corrections import cancellation, reviewed
from database_tests.test_ownership import DISABLED, OWNER_A, OWNER_B, UNKNOWN, set_owner
from trading_db.connections import DatabaseFailure, engine_for
from trading_db.events import EventUnavailable
from trading_db.import_contracts import StagedValue
from trading_db.imports import ImportUnavailable
from trading_db.snapshots import SnapshotDatabase, SnapshotUnavailable
from trading_db.workspace import OwnerAccessDenied

TABLES = ("snapshot_records", "snapshot_components", "snapshot_selections")


@pytest.fixture
def snapshots(events, database):
    event_store, account_store, admin = events
    url, project = database
    store = SnapshotDatabase(url("runtime"), project)
    try:
        yield store, event_store, account_store, admin
    finally:
        store.close()


def snapshot_candidate(reference=None, *, amount="0.123456789012", currency="USD", **changes):
    position = reference is not None
    values = (
        (
            StagedValue(role="quantity", source=amount),
            StagedValue(
                role="unit_price",
                source=None,
                currency=currency,
                missing_reason="not_supplied",
            ),
        )
        if position
        else (StagedValue(role="net_cash", source=amount, currency=currency),)
    )
    return candidate(
        **(
            dict(
                kind="position_snapshot" if position else "cash_snapshot",
                instrument_identifier_id=reference,
                as_of_date="2026-10-24",
                booking_date=None,
                snapshot_scope="selected_position" if position else "native_cash",
                values=values,
            )
            | changes
        )
    )


def prepare(snapshots, *, amount="0.123456789012", **changes):
    store, _, account_store, _ = snapshots
    account, source, position, initial = seed(account_store)
    reference = initial[0].definition.instrument_identifier_id
    row = reviewed(
        account_store, source.id, snapshot_candidate(reference, amount=amount, **changes)
    )[0]
    with store.transaction(OWNER_A) as unit:
        record = unit.record(row.id, expected_review_revision=1, position_id=position.id)
    return account, source, position, reference, row, record


def test_native_snapshots_preserve_source_precision_and_never_write_movements(snapshots):
    store, event_store, accounts, admin = snapshots
    account, source, position, reference, row, original = prepare(
        snapshots,
        as_of_instant="2026-10-24T00:30:00.120+05:30",
        snapshot_scope="full_account",
    )
    cash = reviewed(accounts, source.id, snapshot_candidate(amount="0.00", currency="INR"))[0]
    with store.transaction(OWNER_A) as unit:
        balance = unit.record(cash.id, expected_review_revision=1)
        assert balance.currency == "INR" and balance.components[0].source == "0.00"
        assert balance.as_of_instant is None and balance.snapshot_scope == "native_cash"
        assert original.as_of_instant == "2026-10-24T00:30:00.120+05:30"
        assert original.snapshot_scope == "full_account" and original.coverage == "partial_activity"
        assert original.source_id == source.id and original.observation_id
        assert original.components[1].source is None
        assert unit.record(row.id, expected_review_revision=1, position_id=position.id) == original
        assert len(unit.list(account.id)) == 2
        first = unit.list(account.id, limit=1)[0]
        assert len(unit.list(account.id, after=first.id)) == 1
        assert unit.selections(account.id) == ()
        chosen = unit.select(original.id, expected_snapshot_revision=1, expected_revision=0)
        assert unit.resolve(chosen.id).snapshot == original
        cash_choice = unit.select(balance.id, expected_snapshot_revision=1, expected_revision=0)
        assert unit.resolve(cash_choice.id).snapshot == balance
        assert len(unit.selections(account.id)) == 2
        assert "0.123456789012" not in repr(original)
        with pytest.raises(ImportUnavailable):
            unit._imports.decide(row.id, "reopen", expected_revision=1)
    with event_store.transaction(OWNER_A) as unit:
        assert unit.list(account.id) == ()
        assert unit.movements(account.id, kind="cash", posting_state="posted") == ()
        assert unit.movements(position.id, kind="quantity", posting_state="posted") == ()


def test_conflicting_sources_require_correction_and_identical_descriptions_are_not_summed(
    snapshots,
):
    store, _, accounts, _ = snapshots
    account, source, position, reference, _, first = prepare(snapshots, amount="10.00")
    with accounts.transaction(OWNER_A) as unit:
        other_source = unit.source("indmoney_us", "FAKE-SECOND-SOURCE")
        unit.map(other_source.id, account.id, expected_revision=0)
    same, different = reviewed(
        accounts,
        other_source.id,
        snapshot_candidate(reference, amount="10.000"),
        snapshot_candidate(reference, amount="11", occurrence=2),
    )
    with store.transaction(OWNER_A) as unit:
        identical = unit.record(same.id, expected_review_revision=1, position_id=position.id)
        selection = unit.select(first.id, expected_snapshot_revision=1, expected_revision=0)
        assert unit.resolve(selection.id).snapshot.components[0].source == "10.00"
    with store.transaction(OWNER_A) as unit:
        conflicting = unit.record(different.id, expected_review_revision=1, position_id=position.id)
        assert unit.resolve(selection.id).state == "conflicting"
        with pytest.raises(SnapshotUnavailable):
            unit.select(identical.id, expected_snapshot_revision=1, expected_revision=1)
    corrected = reviewed(accounts, source.id, snapshot_candidate(reference, amount="10"))[0]
    with store.transaction(OWNER_A) as unit:
        result = unit.correct(
            conflicting.id,
            corrected.id,
            expected_revision=1,
            expected_review_revision=1,
            reason="source_correction",
        )
        assert result.revision == 2
        assert unit.resolve(selection.id).snapshot.id == first.id
        assert len(unit.list(account.id)) == 3


@pytest.mark.parametrize(
    "other_instant,other_date,conflict",
    [
        ("2026-10-24T10:00:00+05:30", "2026-10-24", True),
        ("2026-10-24T04:30:00.000Z", "2026-10-24", True),
        ("2026-10-24T04:30:00.000001Z", "2026-10-24", False),
        (None, "2026-10-24", False),
    ],
)
def test_comparability_uses_exact_instant_and_never_invents_midnight(
    snapshots, other_instant, other_date, conflict
):
    store, _, accounts, _ = snapshots
    _, source, position, reference, _, first = prepare(
        snapshots, amount="1", as_of_instant="2026-10-24T04:30:00Z"
    )
    other = reviewed(
        accounts,
        source.id,
        snapshot_candidate(
            reference, amount="2", as_of_instant=other_instant, as_of_date=other_date
        ),
    )[0]
    with store.transaction(OWNER_A) as unit:
        unit.record(other.id, expected_review_revision=1, position_id=position.id)
        if conflict:
            with pytest.raises(SnapshotUnavailable):
                unit.select(first.id, expected_snapshot_revision=1, expected_revision=0)
        else:
            selected = unit.select(first.id, expected_snapshot_revision=1, expected_revision=0)
            assert unit.resolve(selected.id).snapshot == first


def test_correction_stales_selection_and_retains_cancel_reinstate_and_clear_history(snapshots):
    store, _, accounts, _ = snapshots
    _, source, position, reference, _, original = prepare(snapshots)
    with store.transaction(OWNER_A) as unit:
        chosen = unit.select(original.id, expected_snapshot_revision=1, expected_revision=0)
    change, cancel, restore = reviewed(
        accounts,
        source.id,
        snapshot_candidate(reference, amount="2"),
        cancellation(2),
        snapshot_candidate(reference, amount="3", occurrence=3),
    )
    with store.transaction(OWNER_A) as unit:
        changed = unit.correct(
            original.id,
            change.id,
            expected_revision=1,
            expected_review_revision=1,
            reason="source_correction",
        )
        assert unit.resolve(chosen.id).state == "stale"
        with pytest.raises(SnapshotUnavailable):
            unit.select(original.id, expected_snapshot_revision=1, expected_revision=1)
        selected = unit.select(
            original.id, expected_snapshot_revision=2, expected_revision=1, reason="correction"
        )
        assert selected.revision == 2 and unit.resolve(chosen.id).snapshot == changed
    with store.transaction(OWNER_A) as unit:
        cancelled = unit.correct(
            original.id,
            cancel.id,
            expected_revision=2,
            expected_review_revision=1,
            reason="cancellation",
        )
        assert cancelled.status == "cancelled" and cancelled.components == ()
        assert unit.resolve(chosen.id).state == "stale"
        with pytest.raises(SnapshotUnavailable):
            unit.select(original.id, expected_snapshot_revision=3, expected_revision=2)
        reinstated = unit.correct(
            original.id,
            restore.id,
            expected_revision=3,
            expected_review_revision=1,
            reason="reinstatement",
        )
        assert reinstated.revision == 4
        assert (
            unit.correct(
                original.id,
                change.id,
                expected_revision=1,
                expected_review_revision=1,
                reason="source_correction",
            )
            == changed
        )
        assert unit.select(original.id, expected_snapshot_revision=1, expected_revision=0) == chosen
        unit.select(
            original.id, expected_snapshot_revision=4, expected_revision=2, reason="correction"
        )
        cleared = unit.clear(chosen.id, expected_revision=3)
        assert unit.clear(chosen.id, expected_revision=3) == cleared
        assert unit.resolve(chosen.id).state == "unselected"
        assert len(unit.history(original.id)) == 4
        assert len(unit.history(original.id, before=4)) == 3
        assert len(unit.selection_history(chosen.id)) == 4
        assert len(unit.selection_history(chosen.id, before=4)) == 3


@pytest.mark.parametrize("same", (True, False))
def test_concurrent_selection_retries_are_atomic_and_cannot_branch(snapshots, same):
    store, _, accounts, _ = snapshots
    _, source, position, reference, _, first = prepare(snapshots)
    row = reviewed(accounts, source.id, snapshot_candidate(reference))[0]
    with store.transaction(OWNER_A) as unit:
        second = unit.record(row.id, expected_review_revision=1, position_id=position.id)
    barrier = Barrier(2)

    def select(record):
        barrier.wait(timeout=10)
        try:
            with store.transaction(OWNER_A) as unit:
                return unit.select(record.id, expected_snapshot_revision=1, expected_revision=0)
        except SnapshotUnavailable:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(select, (first, first if same else second)))
    selected = [result for result in results if result is not None]
    assert len(selected) == (2 if same else 1)
    assert len({result.id for result in selected}) == 1
    with store.transaction(OWNER_A) as unit:
        assert len(unit.selection_history(selected[0].id)) == 1


def test_failed_last_component_write_rolls_back_and_missing_or_foreign_ids_stay_hidden(
    snapshots, database, monkeypatch
):
    store, _, accounts, _ = snapshots
    account, source, position, reference, row, original = prepare(snapshots)
    change = reviewed(accounts, source.id, snapshot_candidate(reference, amount="2"))[0]
    with store.transaction(OWNER_A) as unit:
        original_execute = unit._execute

        def interrupt(sql, **parameters):
            result = original_execute(sql, **parameters)
            if sql.startswith("INSERT INTO app.snapshot_components"):
                raise DatabaseFailure("Synthetic interrupted write.")
            return result

        monkeypatch.setattr(unit, "_execute", interrupt)
        with pytest.raises(DatabaseFailure):
            unit.correct(
                original.id,
                change.id,
                expected_revision=1,
                expected_review_revision=1,
                reason="source_correction",
            )
        monkeypatch.setattr(unit, "_execute", original_execute)
        assert unit.get(original.id) == original and unit.by_source(change.id) is None
        chosen = unit.select(original.id, expected_snapshot_revision=1, expected_revision=0)
    with store.transaction(OWNER_B) as unit:
        assert unit.get(original.id) is unit.by_source(row.id) is unit.resolve(chosen.id) is None
        assert (
            unit.list(account.id) == unit.history(original.id) == unit.selections(account.id) == ()
        )
        for target in (original.id, uuid4()):
            with pytest.raises(SnapshotUnavailable):
                unit.select(target, expected_snapshot_revision=1, expected_revision=0)
        with pytest.raises(DatabaseFailure):
            unit.list(account.id, limit=101)
        with pytest.raises(SnapshotUnavailable):
            unit.record(row.id, expected_review_revision=1, position_id=position.id)
    with pytest.raises(DatabaseFailure, match="ended"):
        unit.get(original.id)
    for owner in (DISABLED, UNKNOWN):
        with pytest.raises(OwnerAccessDenied), store.transaction(owner):
            pass
    with store._workspace._engine.connect() as connection:
        assert connection.execute(text("SELECT app.current_owner_id()")).scalar_one() is None
        for table in TABLES:
            assert connection.execute(text(f"SELECT count(*) FROM app.{table}")).scalar_one() == 0
    url, _ = database
    for role in ("runtime", "auth"):
        engine = engine_for(url(role))
        try:
            for table in TABLES:
                for statement in (
                    (
                        f"UPDATE app.{table} SET owner_id=:owner",
                        f"DELETE FROM app.{table}",
                        f"TRUNCATE app.{table}",
                    )
                    if role == "runtime"
                    else (f"SELECT * FROM app.{table}",)
                ):
                    with pytest.raises(DBAPIError), engine.begin() as connection:
                        if role == "runtime":
                            set_owner(connection, OWNER_A)
                        connection.execute(text(statement), dict(owner=OWNER_A))
        finally:
            engine.dispose()
    monkeypatch.setattr("trading_db.snapshots.MAX_RECORDS", 0)
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(SnapshotUnavailable):
            unit.record(change.id, expected_review_revision=1, position_id=position.id)


@pytest.mark.parametrize("mutation", ("scope", "instant", "source", "missing_component", "audit"))
def test_direct_sql_cannot_change_source_snapshot_or_incomplete_components(
    snapshots, monkeypatch, mutation
):
    store, _, accounts, _ = snapshots
    _, source, position, reference, _, original = prepare(snapshots)
    row = reviewed(
        accounts, source.id, snapshot_candidate(reference, amount="2", as_of_date="2026-10-25")
    )[0]
    with pytest.raises((SnapshotUnavailable, DBAPIError)), store.transaction(OWNER_A) as unit:
        execute = unit._execute

        def corrupt(sql, **parameters):
            if sql.startswith("INSERT INTO app.snapshot_records"):
                if mutation == "scope":
                    parameters["scope"] = "full_account"
                if mutation == "instant":
                    parameters["instant"] = "2026-10-25T00:00:00Z"
                if mutation == "audit":
                    sql = sql.replace("value_count)", "value_count,created_at)").replace(
                        ":count)", ":count,statement_timestamp())"
                    )
            if (
                sql.startswith("INSERT INTO app.snapshot_components")
                and parameters["role"] == "quantity"
            ):
                if mutation == "source":
                    parameters["source"] = "2.00"
                if mutation == "missing_component":
                    return None
            return execute(sql, **parameters)

        monkeypatch.setattr(unit, "_execute", corrupt)
        unit.record(row.id, expected_review_revision=1, position_id=position.id)
    with store.transaction(OWNER_A) as unit:
        assert unit.by_source(row.id) is None and unit.get(original.id) == original


def test_direct_sql_selection_cannot_choose_conflicting_or_wrong_target(snapshots, monkeypatch):
    store, _, accounts, _ = snapshots
    account, source, position, reference, _, original = prepare(snapshots, amount="1")
    row = reviewed(accounts, source.id, snapshot_candidate(reference, amount="2"))[0]
    with store.transaction(OWNER_A) as unit:
        unit.record(row.id, expected_review_revision=1, position_id=position.id)
    # Bypass the Python check; the deferred database invariant still rejects selection.
    with pytest.raises(SnapshotUnavailable), store.transaction(OWNER_A) as unit:
        monkeypatch.setattr(unit, "_state", lambda snapshot: "selected")
        unit.select(original.id, expected_snapshot_revision=1, expected_revision=0)
    cash = reviewed(accounts, source.id, snapshot_candidate(amount="5.00", currency="INR"))[0]
    with store.transaction(OWNER_A) as unit:
        saved_cash = unit.record(cash.id, expected_review_revision=1)
    with pytest.raises(SnapshotUnavailable), store.transaction(OWNER_A) as unit:
        execute = unit._execute

        def wrong_currency(sql, **parameters):
            if sql.startswith("INSERT INTO app.snapshot_selections"):
                parameters["currency"] = "USD"
            return execute(sql, **parameters)

        monkeypatch.setattr(unit, "_execute", wrong_currency)
        unit.select(saved_cash.id, expected_snapshot_revision=1, expected_revision=0)
    with store.transaction(OWNER_A) as unit:
        assert unit.selections(account.id) == ()


def test_cancellation_source_cannot_be_consumed_by_snapshot_and_event(snapshots):
    store, events, accounts, _ = snapshots
    _, source, position, reference, _, original = prepare(snapshots)
    event_row, cancel_row = reviewed(
        accounts,
        source.id,
        candidate(
            kind="buy",
            instrument_identifier_id=reference,
            trade_date="2026-10-24",
            values=(
                StagedValue(role="quantity", source="1"),
                StagedValue(role="net_cash", source="-1.00", currency="USD"),
            ),
        ),
        cancellation(2),
    )
    with events.transaction(OWNER_A) as unit:
        event = unit.record(event_row.id, expected_review_revision=1, position_id=position.id)
        unit.correct(
            event.id,
            cancel_row.id,
            expected_revision=1,
            expected_review_revision=1,
            reason="cancellation",
        )
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(SnapshotUnavailable):
            unit.correct(
                original.id,
                cancel_row.id,
                expected_revision=1,
                expected_review_revision=1,
                reason="cancellation",
            )
    with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        connection.execute(
            text(
                "INSERT INTO app.snapshot_records (owner_id,id,revision,previous_revision,"
                "source_row_id,source_review_revision,account_id,position_id,instrument_id,"
                "kind,status,correction_reason,booking_date,value_count) VALUES (:owner,:id,"
                "2,1,:row,1,:account,:position,:instrument,'position_snapshot','cancelled',"
                "'cancellation','2026-10-24',0)"
            ),
            dict(
                owner=OWNER_A,
                id=original.id,
                row=cancel_row.id,
                account=original.account_id,
                position=position.id,
                instrument=original.instrument_id,
            ),
        )
    with events.transaction(OWNER_A) as unit:
        with pytest.raises(EventUnavailable):
            unit.record(cancel_row.id, expected_review_revision=1, position_id=position.id)
    with store.transaction(OWNER_A) as unit:
        assert unit.get(original.id).revision == 1


def test_mapping_changes_and_archival_make_selection_unavailable_without_erasing_history(snapshots):
    store, _, accounts, _ = snapshots
    account, source, _, _, _, original = prepare(snapshots)
    with store.transaction(OWNER_A) as unit:
        chosen = unit.select(original.id, expected_snapshot_revision=1, expected_revision=0)
    with accounts.transaction(OWNER_A) as unit:
        unit.map(source.id, None, expected_revision=1)
    with store.transaction(OWNER_A) as unit:
        assert unit.resolve(chosen.id).state == "stale"
        assert unit.get(original.id) == original
        with pytest.raises(SnapshotUnavailable):
            unit.select(original.id, expected_snapshot_revision=1, expected_revision=1)
    with accounts.transaction(OWNER_A) as unit:
        unit.archive(account.id, expected_revision=1)
    with store.transaction(OWNER_A) as unit:
        assert unit.resolve(chosen.id).state == "archived"
        with pytest.raises(SnapshotUnavailable):
            unit.clear(chosen.id, expected_revision=1)


def test_resolution_cannot_mix_versions_across_a_concurrent_correction(snapshots):
    store, _, accounts, _ = snapshots
    _, source, _, reference, _, original = prepare(snapshots)
    with store.transaction(OWNER_A) as unit:
        chosen = unit.select(original.id, expected_snapshot_revision=1, expected_revision=0)
    changed = reviewed(accounts, source.id, snapshot_candidate(reference, amount="2"))[0]
    started = Event()

    def resolve():
        with store.transaction(OWNER_A) as reader:
            started.set()
            return reader.resolve(chosen.id)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.transaction(OWNER_A) as writer:
            writer.correct(
                original.id,
                changed.id,
                expected_revision=1,
                expected_review_revision=1,
                reason="source_correction",
            )
            result = pool.submit(resolve)
            assert started.wait(timeout=5)
            with pytest.raises(TimeoutError):
                result.result(timeout=0.2)
        assert result.result(timeout=5).state == "stale"
