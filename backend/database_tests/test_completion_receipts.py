"""Atomic receipt constraints are exercised through the restricted database role."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_accounts import definition, seed
from database_tests.test_completion_baseline import wait_for_owner_lock
from database_tests.test_events import seed as investment_seed
from database_tests.test_imports import batch, candidate, observation
from database_tests.test_lots_corrections import lot_candidate
from database_tests.test_ownership import DISABLED, OWNER_A, OWNER_B, UNKNOWN, set_owner
from database_tests.test_snapshots import snapshot_candidate
from trading_db import migrate
from trading_db.account_keys import ReferenceKeys
from trading_db.accounts import AccountTransaction, AccountUnavailable
from trading_db.completion import CompletionDatabase
from trading_db.completion_baseline import CompletionBaseline, CompletionUnavailable
from trading_db.completion_contracts import (
    CompletionRequest,
    CompletionRow,
    CompletionSelection,
    canonical_request,
)
from trading_db.connections import engine_for
from trading_db.events import EventTransaction
from trading_db.import_contracts import StagedValue
from trading_db.imports import ImportTransaction
from trading_db.workspace import WorkspaceTransaction


@pytest.fixture
def completions(accounts, database):
    account_store, admin = accounts
    url, project = database
    store = CompletionDatabase(url("runtime"), project, ReferenceKeys({1: b"a" * 32}, 1))
    try:
        yield store, account_store, admin
    finally:
        store.close()


def staged_request(store, *, action="include", coverage="partial_activity"):
    _, source = seed(store)
    with store.transaction(OWNER_A) as unit:
        imports = ImportTransaction(unit._unit)
        observed = imports.observation(
            source.id, observation().model_copy(update={"coverage": coverage})
        )
        staged = imports.stage(observed.id, batch(), expected_revision=0)
        row = imports.rows(staged.id)[0]
        imports.decide(row.id, action, expected_revision=0)
        return CompletionRequest(
            idempotency_key=uuid4(),
            batch_id=staged.id,
            batch_revision=1,
            baseline=CompletionBaseline(unit._unit).current(),
            mode="limited",
            rows=(
                CompletionRow(
                    row_id=row.id,
                    review_revision=1,
                    operation="exclude" if action == "exclude" else "record",
                ),
            ),
        )


def insert_root(unit, request, *, canonical=None, coverage="partial_activity"):
    encoded = canonical if canonical is not None else canonical_request(request)
    identity = uuid4()
    unit._execute(
        "INSERT INTO app.completion_receipts (owner_id,id,idempotency_key,batch_id,"
        "batch_revision,baseline_digest,request_canonical,request_digest,mode,coverage,"
        "row_count,selection_count) VALUES (:owner,:id,:key,:batch,:revision,:baseline,"
        ":canonical,:digest,:mode,:coverage,:rows,:selections)",
        id=identity,
        key=request.idempotency_key,
        batch=request.batch_id,
        revision=request.batch_revision,
        baseline=request.baseline,
        canonical=encoded,
        digest=hashlib.sha256(encoded.encode()).hexdigest(),
        mode=request.mode,
        coverage=coverage,
        rows=len(request.rows),
        selections=len(request.selections),
    )
    return identity


def insert_row(unit, request, receipt_id, *, event=None, outcome=None):
    row = request.rows[0]
    unit._execute(
        "INSERT INTO app.completion_rows (owner_id,receipt_id,source_row_id,review_revision,"
        "operation,outcome,event_id,record_revision) VALUES "
        "(:owner,:receipt,:row,:review,:operation,:outcome,:event,:revision)",
        receipt=receipt_id,
        row=row.row_id,
        review=row.review_revision,
        operation=row.operation,
        outcome=outcome or ("excluded" if row.operation == "exclude" else "recorded"),
        event=event.id if event else None,
        revision=event.revision if event else None,
    )


def test_root_rows_and_financial_effects_commit_together_with_owner_isolation(accounts):
    store, admin = accounts
    request = staged_request(store)
    with store.transaction(OWNER_A) as unit:
        root = insert_root(unit, request)
        event = EventTransaction(unit._unit).record(
            request.rows[0].row_id, expected_review_revision=1
        )
        insert_row(unit, request, root, event=event)
    with store.transaction(OWNER_A) as unit:
        assert CompletionBaseline(unit._unit).current() != request.baseline
        assert unit._execute("SELECT count(*) FROM app.completion_receipts").scalar_one() == 1
        assert unit._execute("SELECT count(*) FROM app.completion_rows").scalar_one() == 1
    with store.transaction(OWNER_B) as unit:
        assert unit._execute("SELECT count(*) FROM app.completion_receipts").scalar_one() == 0
        assert unit._execute("SELECT count(*) FROM app.completion_rows").scalar_one() == 0
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM app.financial_events")).scalar_one() == 1
        )


@pytest.mark.parametrize(
    "fault",
    ("missing_row", "changed_outcome", "stale_baseline", "private_manifest", "complete_coverage"),
)
def test_failed_completion_rolls_back_root_and_financial_effects(accounts, fault):
    store, admin = accounts
    request = staged_request(
        store, coverage="complete_activity" if fault == "complete_coverage" else "partial_activity"
    )
    with pytest.raises(AccountUnavailable):
        with store.transaction(OWNER_A) as unit:
            value = (
                request.model_copy(update={"baseline": "0" * 64})
                if fault == "stale_baseline"
                else request
            )
            canonical = None
            if fault == "private_manifest":
                body = json.loads(canonical_request(value))
                body["rows"][0]["provider_reference"] = "FAKE-PRIVATE"
                canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
            root = insert_root(unit, value, canonical=canonical)
            event = EventTransaction(unit._unit).record(
                value.rows[0].row_id, expected_review_revision=1
            )
            if fault != "missing_row":
                insert_row(
                    unit,
                    value,
                    root,
                    event=event,
                    outcome="linked" if fault == "changed_outcome" else None,
                )
    with admin.connect() as connection:
        for table in (
            "completion_receipts",
            "completion_rows",
            "financial_events",
            "cash_movements",
        ):
            assert connection.execute(text(f"SELECT count(*) FROM app.{table}")).scalar_one() == 0


def test_completed_exclusion_cannot_be_reopened_or_posted(accounts):
    store, _ = accounts
    request = staged_request(store, action="exclude")
    with store.transaction(OWNER_A) as unit:
        root = insert_root(unit, request)
        insert_row(unit, request, root)
    with pytest.raises(AccountUnavailable), store.transaction(OWNER_A) as unit:
        # Raw SQL cannot append a new include decision to the completed occurrence.
        unit._execute(
            "INSERT INTO app.review_decisions (owner_id,row_id,revision,previous_revision,"
            "action,reason,source_id) SELECT owner_id,row_id,2,1,'exclude',reason,source_id "
            "FROM app.review_decisions WHERE owner_id=:owner AND row_id=:row AND revision=1",
            row=request.rows[0].row_id,
        )


def test_service_retries_return_original_receipt_and_changed_keys_conflict(completions):
    store, account_store, admin = completions
    request = staged_request(account_store)
    with store.transaction(OWNER_A) as unit:
        first = unit.complete(request)
    store.close()
    with store.transaction(OWNER_A) as unit:
        assert unit.complete(request) == first
        assert unit.get(first.id) == first
        assert unit.list() == (first,)
        assert unit.baseline() != request.baseline
        for change in ({"idempotency_key": uuid4()}, {"baseline": unit.baseline()}):
            with pytest.raises(CompletionUnavailable):
                unit.complete(request.model_copy(update=change))
    with store.transaction(OWNER_B) as unit:
        assert unit.get(first.id) is None and unit.list() == ()
        with pytest.raises(CompletionUnavailable):
            unit.complete(request)
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM app.financial_events")).scalar_one() == 1
        )


def test_private_retry_is_checked_separately_from_the_public_manifest(completions):
    store, account_store, _ = completions
    request = staged_request(account_store)
    request = request.model_copy(
        update={"rows": (request.rows[0].model_copy(update={"provider_reference": "FAKE-FIRST"}),)}
    )
    changed = request.model_copy(
        update={"rows": (request.rows[0].model_copy(update={"provider_reference": "FAKE-SECOND"}),)}
    )
    assert canonical_request(request) == canonical_request(changed)
    with store.transaction(OWNER_A) as unit:
        first = unit.complete(request)
    with store.transaction(OWNER_A) as unit:
        assert unit.complete(request) == first
        with pytest.raises(CompletionUnavailable):
            unit.complete(changed)
        assert first.rows[0].provider_identity_id is not None
        assert "FAKE-" not in canonical_request(request)


def test_late_service_failure_rolls_back_every_effect_and_allows_clean_retry(
    completions, monkeypatch
):
    store, account_store, _ = completions
    request = staged_request(account_store)
    with store.transaction(OWNER_A) as unit:
        execute = unit._execute

        def interrupted(sql, **parameters):
            result = execute(sql, **parameters)
            if "INSERT INTO app.completion_rows" in sql:
                raise RuntimeError("Synthetic interrupted completion")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(unit, "_execute", interrupted)
            with pytest.raises(RuntimeError):
                unit.complete(request)
        assert unit.baseline() == request.baseline
        assert unit.list() == ()
        assert unit._events.by_source(request.rows[0].row_id) is None
        assert unit.complete(request).rows[0].outcome == "recorded"


def new_request(
    store, source_id, *definitions, observed=None, version="1", coverage="partial_activity"
):
    with store.transaction(OWNER_A) as unit:
        imports = ImportTransaction(unit._unit)
        if observed is None:
            observed = imports.observation(
                source_id,
                observation().model_copy(
                    update={
                        "digest": uuid4().hex * 2,
                        "coverage": coverage,
                    }
                ),
            ).id
        current = imports.latest_batch(observed)
        staged = imports.stage(
            observed,
            batch(*definitions, version=version),
            expected_revision=current.revision if current else 0,
        )
        rows = imports.rows(staged.id, limit=100)
        for row in rows:
            imports.decide(row.id, "include", expected_revision=0)
        request = CompletionRequest(
            idempotency_key=uuid4(),
            batch_id=staged.id,
            batch_revision=staged.revision,
            baseline=CompletionBaseline(unit._unit).current(),
            mode="limited",
            rows=tuple(
                CompletionRow(row_id=row.id, review_revision=1, operation="record") for row in rows
            ),
        )
        return request, observed


def private(request, value):
    return request.model_copy(
        update={"rows": (request.rows[0].model_copy(update={"provider_reference": value}),)}
    )


def test_normalizer_reuse_requires_proven_identity_and_preserves_original_receipts(completions):
    store, accounts, admin = completions
    _, source = seed(accounts)
    first, observed = new_request(accounts, source.id, candidate())
    with store.transaction(OWNER_A) as unit:
        original = unit.complete(first)
    second, _ = new_request(accounts, source.id, candidate(), observed=observed, version="2")
    with store.transaction(OWNER_A) as unit:
        linked = unit.complete(second)
        assert linked.rows[0].outcome == "linked"
        assert linked.rows[0].event_id == original.rows[0].event_id
        assert unit.complete(first) == original
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM app.financial_events")).scalar_one() == 1
        )
        assert (
            connection.execute(text("SELECT count(*) FROM app.completion_receipts")).scalar_one()
            == 2
        )


def test_changed_normalization_requires_explicit_correction_and_keeps_old_receipt(completions):
    store, accounts, admin = completions
    _, source = seed(accounts)
    first, observed = new_request(accounts, source.id, candidate())
    with store.transaction(OWNER_A) as unit:
        original = unit.complete(first)
    changed = candidate(values=(StagedValue(role="net_cash", source="-99.99", currency="INR"),))
    second, _ = new_request(accounts, source.id, changed, observed=observed, version="2")
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(CompletionUnavailable):
            unit.complete(second)
        assert unit.baseline() == second.baseline
        corrected = second.model_copy(
            update={
                "rows": (
                    CompletionRow(
                        row_id=second.rows[0].row_id,
                        review_revision=1,
                        operation="correct",
                        target_kind="event",
                        target_id=original.rows[0].event_id,
                        target_revision=1,
                        correction_reason="source_correction",
                    ),
                )
            }
        )
        result = unit.complete(corrected)
        assert result.rows[0].record_revision == 2
        assert result.rows[0].outcome == "corrected"
        assert unit.complete(first) == original
    with admin.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(DISTINCT id) FROM app.financial_events")
            ).scalar_one()
            == 1
        )
        assert (
            connection.execute(text("SELECT count(*) FROM app.financial_events")).scalar_one() == 2
        )


@pytest.mark.parametrize("provided", (False, True))
def test_equal_payments_from_different_observations_need_provider_identity_to_merge(
    completions, provided
):
    store, accounts, admin = completions
    _, source = seed(accounts)
    first, _ = new_request(accounts, source.id, candidate())
    if provided:
        first = private(first, "FAKE-REPEATED")
    with store.transaction(OWNER_A) as unit:
        original = unit.complete(first)
    second, _ = new_request(accounts, source.id, candidate())
    if provided:
        second = private(second, "FAKE-REPEATED")
    with store.transaction(OWNER_A) as unit:
        result = unit.complete(second)
        assert (result.rows[0].event_id == original.rows[0].event_id) is provided
    with admin.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM app.financial_events")
        ).scalar_one() == (1 if provided else 2)


def test_changed_provider_reference_cannot_create_another_event_for_the_same_raw_occurrence(
    completions,
):
    store, accounts, admin = completions
    _, source = seed(accounts)
    first, observed = new_request(accounts, source.id, candidate())
    with store.transaction(OWNER_A) as unit:
        unit.complete(private(first, "FAKE-ORIGINAL"))
    second, _ = new_request(accounts, source.id, candidate(), observed=observed, version="2")
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(CompletionUnavailable):
            unit.complete(private(second, "FAKE-DIFFERENT"))
        assert unit.complete(private(second, "FAKE-ORIGINAL")).rows[0].outcome == "linked"
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM app.financial_events")).scalar_one() == 1
        )


def test_snapshot_selection_and_revised_source_require_explicit_correction(completions):
    store, accounts, _ = completions
    _, source = seed(accounts)
    definition = snapshot_candidate(amount="100.00", currency="INR")
    first, observed = new_request(accounts, source.id, definition, coverage="snapshot")
    first = first.model_copy(
        update={
            "selections": (CompletionSelection(row_id=first.rows[0].row_id, expected_revision=0),)
        }
    )
    with store.transaction(OWNER_A) as unit:
        original = unit.complete(first)
        assert original.rows[0].selection_revision == 1
    second, _ = new_request(accounts, source.id, definition, observed=observed, version="2")
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(CompletionUnavailable):
            unit.complete(second)
        corrected = second.model_copy(
            update={
                "rows": (
                    CompletionRow(
                        row_id=second.rows[0].row_id,
                        review_revision=1,
                        operation="correct",
                        target_kind="snapshot",
                        target_id=original.rows[0].snapshot_id,
                        target_revision=1,
                        correction_reason="source_correction",
                    ),
                ),
                "selections": (
                    CompletionSelection(
                        row_id=second.rows[0].row_id, expected_revision=1, reason="correction"
                    ),
                ),
            }
        )
        result = unit.complete(corrected)
        assert result.rows[0].snapshot_id == original.rows[0].snapshot_id
        assert result.rows[0].selection_revision == 2
        assert unit.complete(first) == original


def test_new_lot_anchor_preserves_separate_acquisition_and_remaining_evidence(completions):
    store, accounts, _ = completions
    _, source, position, initial = investment_seed(accounts)
    reference = initial[0].definition.instrument_identifier_id
    request, _ = new_request(
        accounts,
        source.id,
        lot_candidate(reference, scope="lot_acquisition", quantity="10.000000000001"),
        lot_candidate(reference, occurrence=2),
    )
    request = request.model_copy(
        update={
            "rows": (
                request.rows[0].model_copy(update={"position_id": position.id}),
                request.rows[1].model_copy(
                    update={"position_id": position.id, "lot_source_row_id": request.rows[0].row_id}
                ),
            )
        }
    )
    with store.transaction(OWNER_A) as unit:
        receipt = unit.complete(request)
        records = [unit._lots.get(row.lot_observation_id) for row in receipt.rows]
        assert len({record.lot_id for record in records}) == 1
        assert {record.scope for record in records} == {"lot_acquisition", "lot_remaining"}
        assert all(
            next(value for value in record.components if value.role == "reported_tax_basis").source
            is None
            for record in records
        )


@pytest.mark.parametrize("same_key", (True, False))
def test_concurrent_completion_has_one_financial_effect_and_one_receipt(completions, same_key):
    store, accounts, admin = completions
    request = staged_request(accounts)
    other = request if same_key else request.model_copy(update={"idempotency_key": uuid4()})
    gate = Barrier(2)

    def complete(value):
        gate.wait(timeout=5)
        try:
            with store.transaction(OWNER_A) as unit:
                return unit.complete(value).id
        except CompletionUnavailable:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(complete, (request, other)))
    winners = [result for result in results if result is not None]
    assert len(winners) == (2 if same_key else 1) and len(set(winners)) == 1
    with admin.connect() as connection:
        for table in ("financial_events", "completion_receipts", "completion_rows"):
            assert connection.execute(text(f"SELECT count(*) FROM app.{table}")).scalar_one() == 1


def test_raw_receipt_insert_cannot_use_a_snapshot_from_before_waiting_for_a_writer(completions):
    store, accounts, admin = completions
    request = staged_request(accounts)
    pending = Queue()

    def insert():
        with pytest.raises(DBAPIError):
            with store._workspace._engine.begin() as connection:
                set_owner(connection, OWNER_A)
                pending.put(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
                # No Python write lock: INSERT itself must wait and then refresh its baseline.
                unit = AccountTransaction(WorkspaceTransaction(connection, OWNER_A), None)
                insert_root(unit, request)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with accounts.transaction(OWNER_A) as unit:
            unit.create(definition(institution="sbi"))
            future = pool.submit(insert)
            wait_for_owner_lock(admin, pending.get(timeout=5))
            assert not future.done()
        future.result(timeout=5)
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM app.completion_receipts")).scalar_one()
            == 0
        )


@pytest.mark.parametrize("change", ("review", "normalization", "observation"))
def test_deferred_guards_reject_source_changes_after_receipt_root_insert(accounts, change):
    store, admin = accounts
    request = staged_request(store, action="exclude")
    with pytest.raises(AccountUnavailable):
        with store.transaction(OWNER_A) as unit:
            root = insert_root(unit, request)
            imports = ImportTransaction(unit._unit)
            original = imports.get_batch(request.batch_id)
            observed = imports.get_observation(original.observation_id)
            if change == "review":
                imports.decide(request.rows[0].row_id, "reopen", expected_revision=1)
            elif change == "normalization":
                imports.stage(observed.id, batch(version="2"), expected_revision=1)
            else:
                imports.observation(observed.source_id, observation("b"), previous_id=observed.id)
            insert_row(unit, request, root)
    with store.transaction(OWNER_A) as unit:
        assert CompletionBaseline(unit._unit).current() == request.baseline
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM app.completion_receipts")).scalar_one()
            == 0
        )


def test_public_manifest_validation_rejects_unknown_private_and_noncanonical_data(accounts):
    store, _ = accounts
    request = staged_request(store)
    original = canonical_request(request)
    body = json.loads(original)

    def encode(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    bad = [
        original + " ",
        original.replace('"request_contract":1', '"request_contract":1,"request_contract":1'),
    ]
    for field, value in (
        ("owner_id", str(uuid4())),
        ("baseline", None),
        ("baseline", "a" * 64 + "\n"),
        ("mode", True),
        ("request_contract", 1.0),
        ("request_contract", True),
        ("batch_id", str(uuid4()) + "\n"),
        ("rows", [None]),
    ):
        bad.append(encode(body | {field: value}))
    for field, value in (
        ("provider_reference", "FAKE-PRIVATE"),
        ("provider_reference_supplied", "false"),
        ("row_id", None),
        ("position_id", None),
        ("target_id", str(uuid4())),
        ("review_revision", True),
    ):
        bad.append(encode(body | {"rows": [body["rows"][0] | {field: value}]}))
    with store.transaction(OWNER_A) as unit:
        for canonical in bad:
            with pytest.raises(AccountUnavailable), unit._write():
                insert_root(unit, request, canonical=canonical)
        assert CompletionBaseline(unit._unit).current() == request.baseline


@pytest.mark.parametrize("table", ("completion_receipts", "completion_rows"))
@pytest.mark.parametrize("verb", ("UPDATE", "DELETE"))
def test_receipts_and_dispositions_are_immutable_even_for_their_owner(completions, table, verb):
    store, accounts, _ = completions
    request = staged_request(accounts)
    with store.transaction(OWNER_A) as unit:
        receipt = unit.complete(request)
    with pytest.raises(CompletionUnavailable), store.transaction(OWNER_A) as unit:
        sql = (
            f"DELETE FROM app.{table}"
            if verb == "DELETE"
            else f"UPDATE app.{table} SET owner_id=owner_id"
        )
        unit._execute(sql)
    with store.transaction(OWNER_A) as unit:
        assert unit.get(receipt.id) == receipt


def test_raw_reads_require_active_owner_and_auth_role_cannot_read_receipts(completions, database):
    store, accounts, _ = completions
    request = staged_request(accounts)
    with store.transaction(OWNER_A) as unit:
        unit.complete(request)
    with store._workspace._engine.begin() as connection:
        for owner in (None, DISABLED, UNKNOWN, OWNER_B):
            if owner is not None:
                set_owner(connection, owner)
            for table in ("completion_receipts", "completion_rows"):
                assert (
                    connection.execute(text(f"SELECT count(*) FROM app.{table}")).scalar_one() == 0
                )
    url, _ = database
    auth = engine_for(url("auth"), migration=True)
    try:
        for table in ("completion_receipts", "completion_rows"):
            with pytest.raises(DBAPIError), auth.begin() as connection:
                set_owner(connection, OWNER_A)
                connection.execute(text(f"SELECT * FROM app.{table}"))
    finally:
        auth.dispose()


@pytest.mark.parametrize(
    "fault", ("target", "revision", "family", "provider", "selection", "review")
)
def test_raw_disposition_tampering_cannot_commit_financial_effects(accounts, fault):
    store, admin = accounts
    request = staged_request(store)
    with pytest.raises(AccountUnavailable), store.transaction(OWNER_A) as unit:
        root = insert_root(unit, request)
        event = EventTransaction(unit._unit).record(
            request.rows[0].row_id, expected_review_revision=1
        )
        values = dict(
            receipt=root,
            row=request.rows[0].row_id,
            review=1,
            event=event.id,
            revision=1,
            snapshot=None,
            provider=None,
            selection=None,
            selection_revision=None,
        )
        if fault == "target":
            values["event"] = uuid4()
        elif fault == "revision":
            values["revision"] = 2
        elif fault == "family":
            values.update(event=None, snapshot=event.id)
        elif fault == "provider":
            values["provider"] = uuid4()
        elif fault == "selection":
            values.update(selection=uuid4(), selection_revision=1)
        else:
            values["review"] = 2
        unit._execute(
            "INSERT INTO app.completion_rows (owner_id,receipt_id,source_row_id,review_revision,"
            "operation,outcome,event_id,snapshot_id,record_revision,provider_identity_id,"
            "selection_id,selection_revision) VALUES (:owner,:receipt,:row,:review,'record',"
            "'recorded',:event,:snapshot,:revision,:provider,:selection,:selection_revision)",
            **values,
        )
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM app.financial_events")).scalar_one() == 0
        )
        assert (
            connection.execute(text("SELECT count(*) FROM app.completion_receipts")).scalar_one()
            == 0
        )


def test_completed_raw_row_cannot_be_posted_again_through_an_event_primitive(completions):
    store, accounts, _ = completions
    _, source = seed(accounts)
    first, observed = new_request(accounts, source.id, candidate())
    with store.transaction(OWNER_A) as unit:
        original = unit.complete(first)
    second, _ = new_request(accounts, source.id, candidate(), observed=observed, version="2")
    with store.transaction(OWNER_A) as unit:
        result = unit.complete(second)
        assert result.rows[0].event_id == original.rows[0].event_id
    with pytest.raises(AccountUnavailable), accounts.transaction(OWNER_A) as unit:
        # An otherwise valid fresh primary event conflicts with the receipt's proven target.
        event_id = uuid4()
        account_id = unit.mapping(source.id).account_id
        unit._execute(
            "INSERT INTO app.financial_events (owner_id,id,revision,source_row_id,"
            "source_review_revision,account_id,kind,posting_state,status,booking_date,value_count) "
            "VALUES (:owner,:id,1,:row,1,:account,'cash_movement','posted','active',"
            "'2026-10-24',1)",
            id=event_id,
            row=second.rows[0].row_id,
            account=account_id,
        )
        unit._execute(
            "INSERT INTO app.event_components (owner_id,event_id,revision,role,source,"
            "amount,currency) VALUES (:owner,:id,1,'net_cash','-12.30',-12.30,'INR')",
            id=event_id,
        )
        unit._execute(
            "INSERT INTO app.cash_movements (owner_id,event_id,revision,account_id,"
            "currency,amount) VALUES (:owner,:id,1,:account,'INR',-12.30)",
            id=event_id,
            account=account_id,
        )
    with store.transaction(OWNER_A) as unit:
        assert unit.complete(second) == result


def test_populated_receipts_prevent_downgrade_and_failed_upgrade_is_atomic(
    completions, database, monkeypatch
):
    store, accounts, admin = completions
    url, project = database
    request = staged_request(accounts)
    before = request.baseline
    migrate.apply(url(), project, direction="downgrade", target="0015_completion_baseline")
    from alembic.operations import Operations

    execute = Operations.execute

    def interrupted(self, statement, *args, **kwargs):
        result = execute(self, statement, *args, **kwargs)
        if "CREATE TABLE app.completion_rows" in str(statement):
            raise RuntimeError("Synthetic interrupted receipt migration")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Operations, "execute", interrupted)
        with pytest.raises(RuntimeError):
            migrate.apply(url(), project)
    assert migrate.revision(url(), project) == "0015_completion_baseline"
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT to_regclass('app.completion_receipts')")).scalar_one()
            is None
        )
    migrate.apply(url(), project)
    with store.transaction(OWNER_A) as unit:
        assert unit.baseline() == before
        receipt = unit.complete(request)
    with pytest.raises(DBAPIError):
        migrate.apply(url(), project, direction="downgrade", target="0015_completion_baseline")
    assert migrate.revision(url(), project) == "0016_completion_receipts"
    with store.transaction(OWNER_A) as unit:
        assert unit.get(receipt.id) == receipt
