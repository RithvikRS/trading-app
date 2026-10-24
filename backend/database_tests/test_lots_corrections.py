"""Exact lot scopes, sourced cancellation and concurrent immutable corrections."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_events import events as events
from database_tests.test_events import seed
from database_tests.test_imports import batch, candidate, observation
from database_tests.test_ownership import DISABLED, OWNER_A, OWNER_B, UNKNOWN, set_owner
from trading_db.connections import DatabaseFailure, engine_for
from trading_db.events import EventUnavailable
from trading_db.import_contracts import StagedValue
from trading_db.imports import ImportTransaction, ImportUnavailable
from trading_db.lots import LotDatabase, LotUnavailable
from trading_db.workspace import OwnerAccessDenied

TABLES = ("lots", "lot_observations", "lot_components")


@pytest.fixture
def lots(events, database):
    event_store, accounts, admin = events
    url, project = database
    store = LotDatabase(url("runtime"), project)
    try:
        yield store, event_store, accounts, admin
    finally:
        store.close()


def reviewed(accounts, source_id, *definitions, owner=OWNER_A):
    with accounts.transaction(owner) as unit:
        staging = ImportTransaction(unit._unit)
        evidence = staging.observation(
            source_id, observation().model_copy(update={"digest": uuid4().hex * 2})
        )
        staged = staging.stage(evidence.id, batch(*definitions), expected_revision=0)
        rows = staging.rows(staged.id)
        for row in rows:
            staging.decide(row.id, "include", expected_revision=0)
        return rows


def lot_candidate(reference, *, scope="lot_remaining", quantity="0.123456789012", **changes):
    values = (
        StagedValue(role="quantity", source=quantity),
        StagedValue(role="unit_price", source="100.00000000", currency="USD"),
        StagedValue(role="acquisition_cost", source="12.00000000", currency="USD"),
        StagedValue(role="discount_amount", source="0.30000000", currency="USD"),
        StagedValue(
            role="reported_tax_basis",
            source=None,
            currency="INR",
            missing_reason="incomplete_history",
        ),
    )
    return candidate(
        **(
            dict(
                kind=scope,
                instrument_identifier_id=reference,
                as_of_date="2026-10-24",
                acquisition_date="2026-09-01" if scope == "lot_acquisition" else None,
                booking_date=None,
                values=values,
            )
            | changes
        )
    )


def cancellation(occurrence=1):
    return candidate(occurrence, kind="cancellation", values=(), booking_date="2026-10-24")


def test_acquisition_remaining_and_unknown_basis_stay_independent_without_movements(lots):
    store, events, accounts, admin = lots
    account, source, position, initial = seed(accounts)
    reference = initial[0].definition.instrument_identifier_id
    acquisition, remaining = reviewed(
        accounts,
        source.id,
        lot_candidate(reference, scope="lot_acquisition", quantity="10.000000000001"),
        lot_candidate(reference, occurrence=2),
    )
    with store.transaction(OWNER_A) as unit:
        bought = unit.record(acquisition.id, position.id, expected_review_revision=1)
        left = unit.record(
            remaining.id, position.id, expected_review_revision=1, lot_id=bought.lot_id
        )
        assert bought.scope == "lot_acquisition" and left.scope == "lot_remaining"
        assert bought.acquisition_date.isoformat() == "2026-09-01"
        assert left.acquisition_date is None
        assert {v.role: v.source for v in left.components} == {
            "quantity": "0.123456789012",
            "unit_price": "100.00000000",
            "acquisition_cost": "12.00000000",
            "discount_amount": "0.30000000",
            "reported_tax_basis": None,
        }
        assert next(v for v in left.components if v.role == "reported_tax_basis").currency == "INR"
        assert len(unit.observations(bought.lot_id)) == 2
        first = unit.observations(bought.lot_id, limit=1)[0]
        assert len(unit.observations(bought.lot_id, after=first.id)) == 1
        assert unit.list(position.id)[0].id == bought.lot_id
        assert unit.list(position.id, after=bought.lot_id) == ()
        assert unit.record(acquisition.id, position.id, expected_review_revision=1) == bought
        assert unit.by_source(remaining.id) == left
        with pytest.raises(LotUnavailable):
            unit.record(acquisition.id, position.id, expected_review_revision=1, lot_id=uuid4())
        for action in ("include", "exclude", "reopen"):
            with pytest.raises(ImportUnavailable):
                unit._imports.decide(remaining.id, action, expected_revision=1)
        assert "12.00000000" not in repr(left)
    with events.transaction(OWNER_A) as unit:
        assert unit.list(account.id) == ()
        assert unit.movements(account.id, kind="cash", posting_state="posted") == ()
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM app.quantity_movements")).scalar_one()
            == 0
        )


def test_lot_corrections_cancel_and_reinstate_without_erasing_evidence(lots):
    store, _, accounts, _ = lots
    _, source, position, initial = seed(accounts)
    reference = initial[0].definition.instrument_identifier_id
    rows = reviewed(
        accounts,
        source.id,
        lot_candidate(reference),
        lot_candidate(reference, occurrence=2, quantity="0"),
        cancellation(3),
        lot_candidate(reference, occurrence=4, quantity="2.000000000001"),
    )
    with store.transaction(OWNER_A) as unit:
        original = unit.record(rows[0].id, position.id, expected_review_revision=1)
    for index, reason in ((1, "source_correction"), (2, "cancellation"), (3, "reinstatement")):
        with store.transaction(OWNER_A) as unit:
            result = unit.correct(
                original.id,
                rows[index].id,
                expected_revision=index,
                expected_review_revision=1,
                reason=reason,
            )
            assert result.revision == index + 1
            assert (
                unit.correct(
                    original.id,
                    rows[index].id,
                    expected_revision=index,
                    expected_review_revision=1,
                    reason=reason,
                )
                == result
            )
            if reason == "cancellation":
                assert result.components == () and result.status == "cancelled"
                assert unit.observations(original.lot_id) == ()
                assert len(unit.observations(original.lot_id, include_cancelled=True)) == 1
            else:
                assert result.status == "active"
    with store.transaction(OWNER_A) as unit:
        assert [v.revision for v in unit.history(original.id)] == [4, 3, 2, 1]
        assert [v.revision for v in unit.history(original.id, before=3, limit=1)] == [2]
        assert unit.by_source(rows[0].id) == original
        assert (
            unit.correct(
                original.id,
                rows[1].id,
                expected_revision=1,
                expected_review_revision=1,
                reason="source_correction",
            ).revision
            == 2
        )
        with pytest.raises(LotUnavailable):
            unit.correct(
                original.id,
                rows[1].id,
                expected_revision=1,
                expected_review_revision=1,
                reason="reinstatement",
            )


@pytest.mark.parametrize(
    "kind",
    (
        "buy",
        "sell",
        "subscription",
        "redemption",
        "dividend",
        "cash_movement",
        "fee",
        "withholding",
    ),
)
def test_event_cancellation_and_reinstatement_keep_only_effective_movements(events, kind):
    store, accounts, _ = events
    account, source, position, initial = seed(accounts, kind=kind)
    with store.transaction(OWNER_A) as unit:
        original = unit.record(
            initial[0].id, expected_review_revision=1, position_id=position.id if position else None
        )
    cancelled, restored = reviewed(
        accounts,
        source.id,
        cancellation(),
        initial[0].definition.model_copy(update={"occurrence": 2}),
    )
    with store.transaction(OWNER_A) as unit:
        result = unit.correct(
            original.id,
            cancelled.id,
            expected_revision=1,
            expected_review_revision=1,
            reason="cancellation",
        )
        assert result.status == "cancelled" and result.components == ()
        assert unit.movements(account.id, kind="cash", posting_state="posted") == ()
        if position:
            assert unit.movements(position.id, kind="quantity", posting_state="posted") == ()
    with store.transaction(OWNER_A) as unit:
        result = unit.correct(
            original.id,
            restored.id,
            expected_revision=2,
            expected_review_revision=1,
            reason="reinstatement",
        )
        assert result.components == original.components and result.status == "active"
        movements = unit.movements(account.id, kind="cash", posting_state="posted")
        assert len(movements) == 1 and movements[0].event.revision == 3
        assert [v.revision for v in unit.history(original.id, limit=2)] == [3, 2]
        assert [v.revision for v in unit.history(original.id, before=2)] == [1]
        assert unit.by_source(initial[0].id) == original
        assert (
            unit.correct(
                original.id,
                cancelled.id,
                expected_revision=1,
                expected_review_revision=1,
                reason="cancellation",
            ).revision
            == 2
        )


def test_pending_to_posted_requires_same_economics_and_source_correction_is_explicit(events):
    store, accounts, _ = events
    account, source, position, initial = seed(accounts, states=("pending",))
    with store.transaction(OWNER_A) as unit:
        original = unit.record(initial[0].id, expected_review_revision=1, position_id=position.id)
    changed = tuple(
        v.model_copy(update={"source": "-15.00"}) if v.role == "net_cash" else v
        for v in initial[0].definition.values
    )
    bad, posted, revised = reviewed(
        accounts,
        source.id,
        initial[0].definition.model_copy(update={"posting_state": "posted", "values": changed}),
        initial[0].definition.model_copy(update={"occurrence": 2, "posting_state": "posted"}),
        initial[0].definition.model_copy(
            update={"occurrence": 3, "posting_state": "posted", "values": changed}
        ),
    )
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(EventUnavailable):
            unit.correct(
                original.id,
                bad.id,
                expected_revision=1,
                expected_review_revision=1,
                reason="posting_update",
            )
        result = unit.correct(
            original.id,
            posted.id,
            expected_revision=1,
            expected_review_revision=1,
            reason="posting_update",
        )
        assert result.revision == 2
        assert unit.movements(account.id, kind="cash", posting_state="pending") == ()
        assert len(unit.movements(account.id, kind="cash", posting_state="posted")) == 1
    with store.transaction(OWNER_A) as unit:
        unit.correct(
            original.id,
            revised.id,
            expected_revision=2,
            expected_review_revision=1,
            reason="source_correction",
        )
        assert unit.movements(account.id, kind="cash", posting_state="posted")[0].amount == Decimal(
            "-15.00"
        )
        with pytest.raises(EventUnavailable):
            unit.correct(
                original.id,
                bad.id,
                expected_revision=1,
                expected_review_revision=1,
                reason="source_correction",
            )


@pytest.mark.parametrize("target", ("event", "lot"))
@pytest.mark.parametrize("same_source", (False, True))
def test_concurrent_corrections_cannot_branch_and_last_write_failure_rolls_back(
    lots, target, monkeypatch, same_source
):
    lot_store, event_store, accounts, _ = lots
    _, source, position, initial = seed(accounts)
    reference = initial[0].definition.instrument_identifier_id
    definition = initial[0].definition if target == "event" else lot_candidate(reference)
    rows = reviewed(
        accounts,
        source.id,
        definition,
        definition.model_copy(update={"occurrence": 2}),
        definition.model_copy(update={"occurrence": 3}),
        definition.model_copy(update={"occurrence": 4}),
    )
    store, error = (
        (event_store, EventUnavailable) if target == "event" else (lot_store, LotUnavailable)
    )
    with store.transaction(OWNER_A) as unit:
        original = unit.record(rows[0].id, expected_review_revision=1, position_id=position.id)
    gate = Barrier(2)

    def correct(row):
        gate.wait()
        try:
            with store.transaction(OWNER_A) as unit:
                return unit.correct(
                    original.id,
                    row.id,
                    expected_revision=1,
                    expected_review_revision=1,
                    reason="source_correction",
                ).revision
        except error:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(correct, (rows[1], rows[1]) if same_source else rows[1:3]))
    if same_source:
        assert results == [2, 2]
    else:
        assert results.count(2) == results.count("conflict") == 1
    with store.transaction(OWNER_A) as unit:
        execute = unit._execute

        def fail(sql, **params):
            result = execute(sql, **params)
            if "INSERT INTO app.cash_movements" in sql or "INSERT INTO app.lot_components" in sql:
                raise RuntimeError("Synthetic interrupted correction")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(unit, "_execute", fail)
            with pytest.raises(RuntimeError):
                unit.correct(
                    original.id,
                    rows[3].id,
                    expected_revision=2,
                    expected_review_revision=1,
                    reason="source_correction",
                )
        assert unit.get(original.id).revision == 2 and unit.by_source(rows[3].id) is None
        assert len(unit.history(original.id)) == 2


@pytest.mark.parametrize(
    "mutation", ("missing_component", "changed_spelling", "wrong_date", "foreign_position")
)
def test_direct_lot_constraints_reject_incomplete_or_altered_evidence(lots, monkeypatch, mutation):
    store, _, accounts, _ = lots
    _, source, position, initial = seed(accounts)
    _, _, foreign, _ = seed(accounts, OWNER_B)
    row = reviewed(
        accounts, source.id, lot_candidate(initial[0].definition.instrument_identifier_id)
    )[0]
    with pytest.raises(LotUnavailable), store.transaction(OWNER_A) as unit:
        execute = unit._execute

        def corrupt(sql, **params):
            if "INSERT INTO app.lot_components" in sql and params["role"] == "acquisition_cost":
                if mutation == "missing_component":
                    return None
                if mutation == "changed_spelling":
                    params["source"] = "12.0"
            if "INSERT INTO app.lot_observations" in sql and mutation == "wrong_date":
                params["as_of"] = "2026-10-23"
            if "INSERT INTO app.lots" in sql and mutation == "foreign_position":
                params["position"] = foreign.id
            return execute(sql, **params)

        monkeypatch.setattr(unit, "_execute", corrupt)
        unit.record(row.id, position.id, expected_review_revision=1)
    with store.transaction(OWNER_A) as unit:
        assert unit.list(position.id) == ()


def test_consumed_cancellation_cannot_cancel_both_event_and_lot(lots):
    lot_store, event_store, accounts, _ = lots
    _, source, position, initial = seed(accounts)
    lot_row, cancel_row = reviewed(
        accounts,
        source.id,
        lot_candidate(initial[0].definition.instrument_identifier_id),
        cancellation(2),
    )
    with event_store.transaction(OWNER_A) as unit:
        event = unit.record(initial[0].id, expected_review_revision=1, position_id=position.id)
    with lot_store.transaction(OWNER_A) as unit:
        lot = unit.record(lot_row.id, position.id, expected_review_revision=1)
    with event_store.transaction(OWNER_A) as unit:
        unit.correct(
            event.id,
            cancel_row.id,
            expected_revision=1,
            expected_review_revision=1,
            reason="cancellation",
        )
    with lot_store.transaction(OWNER_A) as unit:
        with pytest.raises(LotUnavailable):
            unit.correct(
                lot.id,
                cancel_row.id,
                expected_revision=1,
                expected_review_revision=1,
                reason="cancellation",
            )
    with pytest.raises(DBAPIError), lot_store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        connection.execute(
            text(
                "INSERT INTO app.lot_observations (owner_id,id,revision,previous_revision,"
                "lot_id,scope,source_row_id,source_review_revision,status,correction_reason,"
                "booking_date,value_count) VALUES (:owner,:id,2,1,:lot,:scope,:row,1,"
                "'cancelled','cancellation','2026-10-24',0)"
            ),
            dict(owner=OWNER_A, id=lot.id, lot=lot.lot_id, scope=lot.scope, row=cancel_row.id),
        )
    with lot_store.transaction(OWNER_A) as unit:
        assert unit.get(lot.id).revision == 1


def test_owner_grants_limits_and_unknown_resources_remain_isolated(lots, database, monkeypatch):
    store, event_store, accounts, _ = lots
    _, source, position, initial = seed(accounts)
    row = reviewed(
        accounts, source.id, lot_candidate(initial[0].definition.instrument_identifier_id)
    )[0]
    with store.transaction(OWNER_A) as unit:
        original = unit.record(row.id, position.id, expected_review_revision=1)
    with store.transaction(OWNER_B) as unit:
        assert (
            unit.get(original.id) is unit.get_lot(original.lot_id) is unit.by_source(row.id) is None
        )
        assert (
            unit.list(position.id)
            == unit.observations(original.lot_id)
            == unit.history(original.id)
            == ()
        )
        with pytest.raises(LotUnavailable):
            unit.record(row.id, position.id, expected_review_revision=1)
        with pytest.raises(LotUnavailable):
            unit.correct(
                original.id,
                uuid4(),
                expected_revision=1,
                expected_review_revision=1,
                reason="source_correction",
            )
        with pytest.raises(DatabaseFailure):
            unit.list(position.id, limit=101)
        with pytest.raises(LotUnavailable):
            unit.observations(original.lot_id, include_cancelled="true")
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
                for command in (
                    ("UPDATE", "DELETE", "TRUNCATE") if role == "runtime" else ("SELECT",)
                ):
                    statement = {
                        "UPDATE": f"UPDATE app.{table} SET owner_id=:owner",
                        "DELETE": f"DELETE FROM app.{table}",
                        "TRUNCATE": f"TRUNCATE app.{table}",
                        "SELECT": f"SELECT * FROM app.{table}",
                    }[command]
                    with pytest.raises(DBAPIError), engine.begin() as connection:
                        if role == "runtime":
                            set_owner(connection, OWNER_A)
                        connection.execute(text(statement), dict(owner=OWNER_A))
        finally:
            engine.dispose()
    fresh = reviewed(
        accounts, source.id, lot_candidate(initial[0].definition.instrument_identifier_id)
    )[0]
    monkeypatch.setattr("trading_db.lots.MAX_RECORDS", 0)
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(LotUnavailable):
            unit.record(fresh.id, position.id, expected_review_revision=1)


def test_cancellation_needs_existing_target_and_correct_scope(lots):
    store, event_store, accounts, _ = lots
    _, source, position, initial = seed(accounts)
    cancel_row, lot_row, remaining = reviewed(
        accounts,
        source.id,
        cancellation(),
        lot_candidate(
            initial[0].definition.instrument_identifier_id, scope="lot_acquisition", occurrence=2
        ),
        lot_candidate(initial[0].definition.instrument_identifier_id, occurrence=3),
    )
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(LotUnavailable):
            unit.record(cancel_row.id, position.id, expected_review_revision=1)
        original = unit.record(lot_row.id, position.id, expected_review_revision=1)
        with pytest.raises(LotUnavailable):
            unit.correct(
                original.id,
                remaining.id,
                expected_revision=1,
                expected_review_revision=1,
                reason="source_correction",
            )
    with event_store.transaction(OWNER_A) as unit:
        with pytest.raises(EventUnavailable):
            unit.record(cancel_row.id, expected_review_revision=1, position_id=position.id)
