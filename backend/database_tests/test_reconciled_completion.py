"""Exact source/combined equations and immutable comparison provenance."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_accounts import seed
from database_tests.test_completion_receipts import completions as completions
from database_tests.test_completion_receipts import new_request, private
from database_tests.test_events import seed as investment_seed
from database_tests.test_imports import batch, candidate, observation
from database_tests.test_ownership import DISABLED, OWNER_A, OWNER_B, UNKNOWN, set_owner
from database_tests.test_snapshots import snapshot_candidate
from trading_db import migrate
from trading_db.completion_baseline import CompletionBaseline, CompletionUnavailable
from trading_db.completion_contracts import CompletionRequest, CompletionRow
from trading_db.completion_reconciliation import CompletionReconciliation
from trading_db.connections import engine_for
from trading_db.events import EventTransaction
from trading_db.import_contracts import StagedValue
from trading_db.imports import ImportTransaction


def checkpoint(occurrence, amount, boundary, *, currency="INR", reference=None):
    return snapshot_candidate(
        reference,
        occurrence=occurrence,
        amount=amount,
        currency=currency,
        as_of_date="2026-10-01" if boundary == "before_period" else "2026-10-24",
        reconciliation_boundary=boundary,
    )


def cash(occurrence=2, amount="-12.30", currency="INR", **changes):
    return candidate(
        occurrence,
        values=(StagedValue(role="net_cash", source=amount, currency=currency),),
        **changes,
    )


def prepare(
    store,
    *,
    source=None,
    definitions=None,
    basis="booking",
    owner=OWNER_A,
    position_id=None,
    previous_id=None,
):
    if source is None:
        _, source = seed(store, owner=owner)
    with store.transaction(owner) as unit:
        imports = ImportTransaction(unit._unit)
        observed = imports.observation(
            source.id,
            observation().model_copy(
                update={"digest": uuid4().hex * 2, "coverage": "complete_activity"}
            ),
            previous_id=previous_id,
        )
        staged = imports.stage(
            observed.id,
            batch(
                *(
                    definitions
                    or (
                        checkpoint(1, "100.00", "before_period"),
                        cash(),
                        checkpoint(3, "87.70", "after_period"),
                    )
                )
            ).model_copy(update={"cash_date_basis": basis}),
            expected_revision=0,
        )
        rows = imports.rows(staged.id, limit=100)
        for row in rows:
            imports.decide(row.id, "include", expected_revision=0)
        return CompletionRequest(
            idempotency_key=uuid4(),
            batch_id=staged.id,
            batch_revision=1,
            baseline=CompletionBaseline(unit._unit).current(),
            mode="reconciled",
            rows=tuple(
                CompletionRow(
                    row_id=row.id,
                    review_revision=1,
                    operation="record",
                    position_id=position_id if row.definition.instrument_identifier_id else None,
                )
                for row in rows
            ),
        ), source


def test_complete_cash_preserves_exact_equations_inputs_and_replay(completions):
    store, accounts, admin = completions
    request, _ = prepare(accounts)
    with store.transaction(OWNER_A) as unit:
        receipt = unit.complete(request)
        assert len(receipt.scopes) == 1
        pair = receipt.scopes[0].comparison
        assert pair.balanced
        assert pair.source.posted_total == pair.combined.posted_total == "-12.30"
        assert pair.source.evidence.opening.source == "100.00"
        assert pair.combined.evidence.closing.source == "87.70"
        assert pair.source.posted_count == pair.combined.posted_count == 1
    with store.transaction(OWNER_A) as unit:
        assert unit.complete(request) == receipt
        assert unit.get(receipt.id) == receipt
    with store.transaction(OWNER_B) as unit:
        assert unit.get(receipt.id) is None
        for table in ("completion_scopes", "completion_inputs"):
            assert unit._execute(f"SELECT count(*) FROM app.{table}").scalar_one() == 0
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM app.completion_inputs")).scalar_one() == 6
        )


@pytest.mark.parametrize("pending", (False, True))
def test_known_zero_activity_and_pending_counts_do_not_invent_posted_amounts(completions, pending):
    store, accounts, _ = completions
    definitions = [checkpoint(1, "0.00", "before_period")]
    if pending:
        definitions.append(cash(posting_state="pending"))
    definitions.append(checkpoint(3, "0.00", "after_period"))
    request, _ = prepare(accounts, definitions=definitions)
    with store.transaction(OWNER_A) as unit:
        pair = unit.complete(request).scopes[0].comparison
        assert pair.balanced
        assert pair.source.posted_count == pair.combined.posted_count == 0
        assert pair.source.pending_count == pair.combined.pending_count == int(pending)
        assert pair.source.posted_total == pair.combined.posted_total == "0"


@pytest.mark.parametrize(
    "fault", ("source_mismatch", "missing_basis", "missing_date", "unknown_fee")
)
def test_incomplete_equations_roll_back_every_financial_effect(completions, fault):
    store, accounts, admin = completions
    movement = cash()
    if fault == "unknown_fee":
        movement = movement.model_copy(
            update={
                "values": (
                    *movement.values,
                    StagedValue(
                        role="fee",
                        source=None,
                        currency="INR",
                        missing_reason="not_supplied",
                    ),
                )
            }
        )
    request, _ = prepare(
        accounts,
        basis=None
        if fault == "missing_basis"
        else "value"
        if fault == "missing_date"
        else "booking",
        definitions=(
            checkpoint(1, "100.00", "before_period"),
            movement,
            checkpoint(3, "88.00" if fault == "source_mismatch" else "87.70", "after_period"),
        ),
    )
    with pytest.raises(CompletionUnavailable), store.transaction(OWNER_A) as unit:
        unit.complete(request)
    with admin.connect() as connection:
        for table in (
            "completion_receipts",
            "completion_rows",
            "completion_scopes",
            "completion_inputs",
            "financial_events",
            "snapshot_records",
        ):
            assert connection.execute(text(f"SELECT count(*) FROM app.{table}")).scalar_one() == 0


def add_existing(store, source, *definitions):
    with store.transaction(OWNER_A) as unit:
        imports = ImportTransaction(unit._unit)
        observed = imports.observation(
            source.id, observation().model_copy(update={"digest": uuid4().hex * 2})
        )
        staged = imports.stage(observed.id, batch(*definitions), expected_revision=0)
        for row in imports.rows(staged.id, limit=100):
            imports.decide(row.id, "include", expected_revision=0)
            EventTransaction(unit._unit).record(row.id, expected_review_revision=1)


def test_balanced_source_cannot_hide_extra_combined_activity(completions):
    store, accounts, _ = completions
    _, source = seed(accounts)
    add_existing(accounts, source, cash(amount="5.00"))
    request, _ = prepare(accounts, source=source)
    with pytest.raises(CompletionUnavailable), store.transaction(OWNER_A) as unit:
        unit.complete(request)


def test_offsetting_existing_movements_must_both_be_retained(completions):
    store, accounts, _ = completions
    _, source = seed(accounts)
    add_existing(accounts, source, cash(1, "5.00"), cash(2, "-5.00"))
    request, _ = prepare(accounts, source=source)
    with store.transaction(OWNER_A) as unit:
        pair = unit.complete(request).scopes[0].comparison
        assert pair.balanced
        assert pair.source.posted_count == 1 and pair.combined.posted_count == 3
        assert sorted(item.source for item in pair.combined.evidence.activities) == [
            "-12.30",
            "-5.00",
            "5.00",
        ]


def test_direct_sql_cannot_omit_offsetting_combined_inputs(completions, monkeypatch):
    store, accounts, _ = completions
    _, source = seed(accounts)
    add_existing(accounts, source, cash(1, "5.00"), cash(2, "-5.00"))
    request, _ = prepare(accounts, source=source)
    execute = CompletionReconciliation._execute

    def tampered(self, sql, **parameters):
        if sql.startswith("INSERT INTO app.completion_scopes"):
            parameters.update(combined_posted=1, input_count=6)
        elif (
            sql.startswith("INSERT INTO app.completion_inputs")
            and parameters["side"] == "combined"
            and parameters["source"] in ("5.00", "-5.00")
        ):
            return None
        elif sql.startswith("SELECT app.validate_completion_scope"):
            return None  # The deferred database constraint still must reject this.
        return execute(self, sql, **parameters)

    monkeypatch.setattr(CompletionReconciliation, "_execute", tampered)
    with pytest.raises(CompletionUnavailable), store.transaction(OWNER_A) as unit:
        unit.complete(request)


def investment_request(accounts):
    _, source, position, initial = investment_seed(accounts)
    reference = initial[0].definition.instrument_identifier_id
    trade = candidate(
        3,
        kind="buy",
        instrument_identifier_id=reference,
        trade_date="2026-10-21",
        settlement_date="2026-10-23",
        values=(
            StagedValue(role="net_cash", source="-12.30", currency="USD"),
            StagedValue(role="quantity", source="0.123456789012"),
        ),
    )
    request, _ = prepare(
        accounts,
        source=source,
        position_id=position.id,
        definitions=(
            checkpoint(1, "100.00", "before_period", currency="USD"),
            checkpoint(2, "1.000000000000", "before_period", reference=reference, currency="USD"),
            trade,
            checkpoint(4, "87.70", "after_period", currency="USD"),
            checkpoint(5, "1.123456789012", "after_period", reference=reference, currency="USD"),
        ),
    )
    return request


def test_native_cash_and_fractional_units_have_separate_exact_scopes(completions):
    store, accounts, _ = completions
    request = investment_request(accounts)
    with store.transaction(OWNER_A) as unit:
        receipt = unit.complete(request)
        scopes = {
            item.comparison.source.evidence.scope.kind: item.comparison for item in receipt.scopes
        }
        assert set(scopes) == {"cash", "units"}
        assert scopes["cash"].source.posted_total == "-12.30"
        assert scopes["units"].source.posted_total == "0.123456789012"
        assert scopes["units"].combined.calculated_closing == "1.123456789012"
        assert scopes["units"].source.evidence.period.date_basis == "trade"
        assert scopes["units"].source.evidence.activities[0].date == "2026-10-21"


def test_currency_scopes_cannot_be_netted_together(completions):
    store, accounts, _ = completions
    _, source, _, _ = investment_seed(accounts)
    request, _ = prepare(
        accounts,
        source=source,
        definitions=(
            checkpoint(1, "100.00", "before_period", currency="USD"),
            cash(2, "-12.30", "USD"),
            checkpoint(3, "87.70", "after_period", currency="USD"),
            checkpoint(4, "100.00", "before_period"),
            cash(5, "10.00"),
            checkpoint(6, "110.00", "after_period"),
        ),
    )
    with store.transaction(OWNER_A) as unit:
        scopes = {
            item.comparison.source.evidence.scope.currency: item.comparison
            for item in unit.complete(request).scopes
        }
        assert set(scopes) == {"INR", "USD"}
        assert scopes["INR"].source.posted_total == "10.00"
        assert scopes["USD"].source.posted_total == "-12.30"


@pytest.mark.parametrize(
    "basis,day", (("booking", "2026-10-24"), ("value", "2026-10-22"), ("settlement", "2026-10-23"))
)
def test_cash_basis_preserves_the_declared_activity_date(completions, basis, day):
    store, accounts, _ = completions
    request, _ = prepare(
        accounts,
        basis=basis,
        definitions=(
            checkpoint(1, "100.00", "before_period"),
            cash(value_date="2026-10-22", settlement_date="2026-10-23"),
            checkpoint(3, "87.70", "after_period"),
        ),
    )
    with store.transaction(OWNER_A) as unit:
        pair = unit.complete(request).scopes[0].comparison
        assert pair.source.evidence.activities[0].date == day
        assert pair.combined.evidence.activities[0].date == day


@pytest.mark.parametrize("missing", (False, True))
def test_unknown_combined_dates_block_but_known_outside_dates_are_excluded(completions, missing):
    store, accounts, _ = completions
    _, source = seed(accounts)
    add_existing(accounts, source, cash(value_date=None if missing else "2026-09-30"))
    request, _ = prepare(
        accounts,
        source=source,
        basis="value",
        definitions=(
            checkpoint(1, "100.00", "before_period"),
            cash(value_date="2026-10-24"),
            checkpoint(3, "87.70", "after_period"),
        ),
    )
    if missing:
        with pytest.raises(CompletionUnavailable), store.transaction(OWNER_A) as unit:
            unit.complete(request)
    else:
        with store.transaction(OWNER_A) as unit:
            pair = unit.complete(request).scopes[0].comparison
            assert pair.combined.posted_count == 1


def test_gross_fees_and_withholding_are_not_additional_cash_movements(completions):
    store, accounts, _ = completions
    _, source, position, initial = investment_seed(accounts, kind="dividend")
    reference = initial[0].definition.instrument_identifier_id
    dividend = candidate(
        2,
        kind="dividend",
        instrument_identifier_id=reference,
        values=(
            StagedValue(role="net_cash", source="12.30", currency="USD"),
            StagedValue(role="gross_cash", source="14.30", currency="USD"),
            StagedValue(role="fee", source="1.00000000", currency="USD"),
            StagedValue(role="withholding", source="1.00000000", currency="USD"),
        ),
    )
    request, _ = prepare(
        accounts,
        source=source,
        position_id=position.id,
        definitions=(
            checkpoint(1, "100.00", "before_period", currency="USD"),
            dividend,
            checkpoint(3, "112.30", "after_period", currency="USD"),
        ),
    )
    with store.transaction(OWNER_A) as unit:
        receipt = unit.complete(request)
        assert len(receipt.scopes) == 1
        assert receipt.scopes[0].comparison.source.posted_total == "12.30"
        assert receipt.scopes[0].comparison.combined.posted_count == 1


def test_missing_native_scope_is_rejected_even_when_the_other_scope_balances(
    completions, monkeypatch
):
    store, accounts, _ = completions
    request = investment_request(accounts)
    execute = CompletionReconciliation._execute

    def omit_units(self, sql, **parameters):
        if sql.startswith("SELECT * FROM app.reconciliation_source_inputs"):
            sql = sql.replace("ORDER BY kind", "WHERE kind='cash' ORDER BY kind")
        return execute(self, sql, **parameters)

    monkeypatch.setattr(CompletionReconciliation, "_execute", omit_units)
    with pytest.raises(CompletionUnavailable), store.transaction(OWNER_A) as unit:
        unit.complete(request)


def test_later_full_correction_retains_the_original_compared_inputs(completions):
    store, accounts, _ = completions
    first, source = prepare(accounts)
    with store.transaction(OWNER_A) as unit:
        original = unit.complete(first)
        observed = unit._imports.get_batch(first.batch_id).observation_id
    second, _ = prepare(
        accounts,
        source=source,
        previous_id=observed,
        definitions=(
            checkpoint(1, "100.00", "before_period"),
            cash(amount="-22.00"),
            checkpoint(3, "78.00", "after_period"),
        ),
    )
    saved = {item.source_row_id: item for item in original.rows}
    choices = []
    for new, old in zip(second.rows, first.rows, strict=True):
        target = saved[old.row_id]
        choices.append(
            CompletionRow(
                row_id=new.row_id,
                review_revision=1,
                operation="correct",
                target_kind="event" if target.event_id else "snapshot",
                target_id=target.event_id or target.snapshot_id,
                target_revision=1,
                correction_reason="source_correction",
            )
        )
    second = second.model_copy(update={"rows": tuple(choices)})
    with store.transaction(OWNER_A) as unit:
        changed = unit.complete(second)
        assert changed.scopes[0].comparison.combined.posted_total == "-22.00"
        assert changed.scopes[0].comparison.combined.evidence.activities[0].revision == 2
        assert unit.complete(first) == original
    with store.transaction(OWNER_A) as unit:
        assert unit.get(original.id).scopes[0].comparison.combined.posted_total == "-12.30"


@pytest.mark.parametrize("provided", (False, True))
def test_overlapping_complete_statement_needs_proven_event_identity(completions, provided):
    store, accounts, _ = completions
    _, source = seed(accounts)
    first, _ = new_request(accounts, source.id, cash())
    with store.transaction(OWNER_A) as unit:
        original = unit.complete(private(first, "FAKE-OVERLAP"))
    request, _ = prepare(accounts, source=source)
    if provided:
        request = request.model_copy(
            update={
                "rows": tuple(
                    row.model_copy(update={"provider_reference": "FAKE-OVERLAP"})
                    if index == 1
                    else row
                    for index, row in enumerate(request.rows)
                )
            }
        )
        with store.transaction(OWNER_A) as unit:
            receipt = unit.complete(request)
            assert receipt.scopes[0].comparison.combined.posted_count == 1
            assert (
                next(row.event_id for row in receipt.rows if row.event_id)
                == original.rows[0].event_id
            )
    else:
        with pytest.raises(CompletionUnavailable), store.transaction(OWNER_A) as unit:
            unit.complete(request)


def test_equal_payments_without_shared_identity_remain_distinct(completions):
    store, accounts, _ = completions
    request, _ = prepare(
        accounts,
        definitions=(
            checkpoint(1, "100.00", "before_period"),
            cash(),
            cash(3),
            checkpoint(4, "75.40", "after_period"),
        ),
    )
    with store.transaction(OWNER_A) as unit:
        receipt = unit.complete(request)
        assert len({row.event_id for row in receipt.rows if row.event_id}) == 2
        assert receipt.scopes[0].comparison.combined.posted_count == 2


@pytest.mark.parametrize(
    "fault", ("missing_boundary", "missing_closing", "duplicate_opening", "pending_outside")
)
def test_complete_statement_cannot_choose_or_invent_checkpoint_meaning(completions, fault):
    store, accounts, _ = completions
    opening = checkpoint(1, "100.00", "before_period")
    if fault == "missing_boundary":
        opening = opening.model_copy(update={"reconciliation_boundary": None})
    definitions = [opening, cash()]
    if fault != "missing_closing":
        definitions.append(checkpoint(3, "87.70", "after_period"))
    if fault == "duplicate_opening":
        definitions.append(checkpoint(4, "100.00", "before_period"))
    elif fault == "pending_outside":
        definitions.append(cash(4, posting_state="pending", booking_date="2026-11-01"))
    request, _ = prepare(accounts, definitions=definitions)
    with pytest.raises(CompletionUnavailable), store.transaction(OWNER_A) as unit:
        unit.complete(request)


@pytest.mark.parametrize(
    "fault", ("amount", "source", "revision", "date", "totals", "counts", "rule")
)
def test_raw_comparison_tampering_rolls_back_at_the_database_boundary(
    completions, monkeypatch, fault
):
    store, accounts, _ = completions
    request, _ = prepare(accounts)
    execute = CompletionReconciliation._execute

    def tampered(self, sql, **parameters):
        if sql.startswith("SELECT app.validate_completion_scope"):
            return None
        if sql.startswith("INSERT INTO app.completion_scopes"):
            if fault == "totals":
                parameters.update(source_total=0, combined_total=0, closing=parameters["opening"])
            elif fault == "counts":
                parameters.update(source_posted=2)
            elif fault == "rule":
                parameters.update(rule_version=2)
        elif (
            sql.startswith("INSERT INTO app.completion_inputs")
            and parameters["side"] == "combined"
            and parameters["part"] == "activity"
        ):
            if fault == "amount":
                parameters["amount"] += 1
            elif fault == "source":
                parameters["source"] = "-99.00"
            elif fault == "revision":
                parameters["reference_revision"] = 2
            elif fault == "date":
                parameters["evidence_date"] = "2026-10-23"
        return execute(self, sql, **parameters)

    monkeypatch.setattr(CompletionReconciliation, "_execute", tampered)
    # Skip reconstruction too: rejection must come from the database constraints.
    monkeypatch.setattr(CompletionReconciliation, "list", lambda self, receipt_id: ())
    with pytest.raises(CompletionUnavailable), store.transaction(OWNER_A) as unit:
        unit.complete(request)
    with store.transaction(OWNER_A) as unit:
        assert unit.list() == ()


def test_equally_offsetting_source_inputs_cannot_be_omitted(completions, monkeypatch):
    store, accounts, _ = completions
    request, _ = prepare(
        accounts,
        definitions=(
            checkpoint(1, "100.00", "before_period"),
            cash(2, "5.00"),
            cash(3, "-5.00"),
            checkpoint(4, "100.00", "after_period"),
        ),
    )
    execute = CompletionReconciliation._execute

    def tampered(self, sql, **parameters):
        if sql.startswith("SELECT app.validate_completion_scope"):
            return None
        if sql.startswith("INSERT INTO app.completion_scopes"):
            parameters.update(source_posted=0, input_count=6)
        elif (
            sql.startswith("INSERT INTO app.completion_inputs")
            and parameters["side"] == "source"
            and parameters["part"] == "activity"
        ):
            return None
        return execute(self, sql, **parameters)

    monkeypatch.setattr(CompletionReconciliation, "_execute", tampered)
    with pytest.raises(CompletionUnavailable), store.transaction(OWNER_A) as unit:
        unit.complete(request)


def test_later_activity_in_the_same_transaction_invalidates_the_compared_set(completions):
    store, accounts, _ = completions
    request, source = prepare(accounts)
    with pytest.raises(CompletionUnavailable), store.transaction(OWNER_A) as unit:
        unit.complete(request)
        observed = unit._imports.observation(source.id, observation("b"))
        staged = unit._imports.stage(observed.id, batch(cash(amount="1.00")), expected_revision=0)
        row = unit._imports.rows(staged.id)[0]
        unit._imports.decide(row.id, "include", expected_revision=0)
        unit._events.record(row.id, expected_review_revision=1)
    with store.transaction(OWNER_A) as unit:
        assert unit.baseline() == request.baseline


def test_concurrent_replay_keeps_one_receipt_and_one_compared_set(completions):
    store, accounts, _ = completions
    request, _ = prepare(accounts)

    def complete():
        with store.transaction(OWNER_A) as unit:
            return unit.complete(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = tuple(executor.map(lambda _: complete(), range(2)))
    assert first == second
    with store.transaction(OWNER_A) as unit:
        assert unit._execute("SELECT count(*) FROM app.completion_scopes").scalar_one() == 1
        assert unit._execute("SELECT count(*) FROM app.completion_inputs").scalar_one() == 6


@pytest.mark.parametrize("table", ("completion_scopes", "completion_inputs"))
@pytest.mark.parametrize("verb", ("UPDATE", "DELETE"))
def test_comparisons_are_immutable_even_for_their_owner(completions, table, verb):
    store, accounts, _ = completions
    request, _ = prepare(accounts)
    with store.transaction(OWNER_A) as unit:
        receipt = unit.complete(request)
    with pytest.raises(CompletionUnavailable), store.transaction(OWNER_A) as unit:
        unit._execute(
            f"DELETE FROM app.{table}"
            if verb == "DELETE"
            else f"UPDATE app.{table} SET owner_id=owner_id"
        )
    with store.transaction(OWNER_A) as unit:
        assert unit.get(receipt.id) == receipt


def test_raw_comparison_reads_require_active_owner_and_auth_role_is_denied(completions, database):
    store, accounts, _ = completions
    request, _ = prepare(accounts)
    with store.transaction(OWNER_A) as unit:
        receipt = unit.complete(request)
    with store._workspace._engine.begin() as connection:
        for owner in (None, DISABLED, UNKNOWN, OWNER_B):
            if owner is not None:
                set_owner(connection, owner)
            for table in ("completion_scopes", "completion_inputs"):
                assert (
                    connection.execute(text(f"SELECT count(*) FROM app.{table}")).scalar_one() == 0
                )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM app.reconciliation_source_inputs(:own,:id)"),
                    {"own": OWNER_A, "id": receipt.id},
                ).scalar_one()
                == 0
            )
    url, _ = database
    auth = engine_for(url("auth"), migration=True)
    try:
        for table in ("completion_scopes", "completion_inputs"):
            with pytest.raises(DBAPIError), auth.begin() as connection:
                set_owner(connection, OWNER_A)
                connection.execute(text(f"SELECT * FROM app.{table}"))
    finally:
        auth.dispose()


def test_a_completed_comparison_cannot_gain_inputs_in_a_later_transaction(completions):
    store, accounts, _ = completions
    request, source = prepare(accounts)
    with store.transaction(OWNER_A) as unit:
        receipt = unit.complete(request)
    later, _ = new_request(accounts, source.id, cash())
    with pytest.raises(CompletionUnavailable), store.transaction(OWNER_A) as unit:
        unit._execute(
            "INSERT INTO app.completion_inputs (owner_id,scope_id,side,part,reference_id,"
            "reference_revision,source_row_id,source,amount,evidence_date,posting_state) VALUES "
            "(:owner,:scope,'source','activity',:row,1,:row,'-12.30',-12.30,'2026-10-24','posted')",
            scope=receipt.scopes[0].id,
            row=later.rows[0].row_id,
        )
    with store.transaction(OWNER_A) as unit:
        assert unit.get(receipt.id) == receipt


def test_failed_upgrade_rolls_back_and_populated_comparisons_prevent_downgrade(
    completions,
    database,
    monkeypatch,
):
    store, accounts, admin = completions
    url, project = database
    request, _ = prepare(accounts)
    migrate.apply(url(), project, direction="downgrade", target="0016_completion_receipts")
    from alembic.operations import Operations

    execute = Operations.execute

    def interrupted(self, statement, *args, **kwargs):
        result = execute(self, statement, *args, **kwargs)
        if "CREATE TABLE app.completion_inputs" in str(statement):
            raise RuntimeError("Synthetic interrupted reconciliation migration")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Operations, "execute", interrupted)
        with pytest.raises(RuntimeError):
            migrate.apply(url(), project)
    assert migrate.revision(url(), project) == "0016_completion_receipts"
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT to_regclass('app.completion_scopes')")).scalar_one()
            is None
        )
    migrate.apply(url(), project)
    with store.transaction(OWNER_A) as unit:
        assert unit.baseline() == request.baseline
        receipt = unit.complete(request)
    with pytest.raises(DBAPIError):
        migrate.apply(url(), project, direction="downgrade", target="0016_completion_receipts")
    with store.transaction(OWNER_A) as unit:
        assert unit.get(receipt.id) == receipt


def test_combined_input_limit_fails_without_truncation_or_partial_effects(completions):
    store, accounts, _ = completions
    _, source = seed(accounts)
    # These are independent legitimate source occurrences, each with known zero cash.
    # 997 old rows plus the full statement's three rows fit the staging/event budgets,
    # but preserving both comparison sides needs more than 1,000 inputs.
    for count in (100,) * 9 + (97,):
        add_existing(accounts, source, *(cash(index + 1, "0.00") for index in range(count)))
    request, _ = prepare(accounts, source=source)
    with pytest.raises(CompletionUnavailable), store.transaction(OWNER_A) as unit:
        unit.complete(request)
    with store.transaction(OWNER_A) as unit:
        assert unit.baseline() == request.baseline
        assert unit._execute("SELECT count(*) FROM app.financial_events").scalar_one() == 997
        assert unit._execute("SELECT count(*) FROM app.completion_inputs").scalar_one() == 0
        assert unit._execute("SELECT count(*) FROM app.snapshot_records").scalar_one() == 0
