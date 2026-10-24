"""Receipt reads reconstruct immutable comparisons without asserting current balances."""

import json
import time
import tracemalloc
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import event
from starlette.testclient import TestClient

from database_tests.test_accounts import definition
from database_tests.test_events import seed as investment_seed
from database_tests.test_imports import batch, candidate, observation
from database_tests.test_preferences import ORIGIN, login, sql
from database_tests.test_preferences import environment as environment
from database_tests.test_reconciled_completion import cash, checkpoint, prepare
from tests.auth_support import ISSUER, SUBJECT
from trading_api.application import create_app
from trading_auth.browser import BrowserAuth
from trading_db.account_keys import ReferenceKeys
from trading_db.accounts import AccountDatabase
from trading_db.completion import CompletionTransaction
from trading_db.completion_baseline import CompletionBaseline
from trading_db.completion_contracts import CompletionRequest, CompletionRow
from trading_db.completion_reconciliation import CompletionReconciliation
from trading_db.enrollment import provision_owner
from trading_db.import_contracts import StagedValue
from trading_db.imports import ImportTransaction
from trading_db.local import ROOT
from trading_db.sessions import SessionDatabase
from trading_db.workspace import WorkspaceDatabase


def get(client, headers, path, **body):
    return client.post(f"/api/v1/finance/receipts/{path}", headers=headers, json=body)


def complete(accounts, workspace, owner, **options):
    if "source" not in options:
        with accounts.transaction(owner) as unit:
            account = unit.create(definition())
            source = unit.source("hdfc_statement", "FAKE-RECEIPT-" + uuid4().hex)
            unit.map(source.id, account.id, expected_revision=0)
        options["source"] = source
    request, source = prepare(accounts, owner=owner, **options)
    with workspace.transaction(owner) as unit:
        receipt = CompletionTransaction(unit, None).complete(request)
    return dict(request=request, source=source, receipt=receipt)


@pytest.fixture
def evidence(environment, database):
    _, _, workspace, _, admin = environment
    owner = sql(
        admin,
        "SELECT owner_id FROM app.owner_identities WHERE subject=:subject",
        subject=str(SUBJECT),
    )[0][0]
    url, project = database
    accounts = AccountDatabase(url("runtime"), project, ReferenceKeys({1: b"r" * 32}, 1))
    try:
        yield owner, complete(accounts, workspace, owner), accounts
    finally:
        accounts.close()


def queries(data):
    receipt = data["receipt"]
    return [
        ("query", dict(batch_id=str(receipt.manifest.batch_id))),
        ("inspect", dict(id=str(receipt.id))),
        ("rows/query", dict(receipt_id=str(receipt.id))),
        ("scopes/query", dict(receipt_id=str(receipt.id))),
        ("scopes/inspect", dict(id=str(receipt.scopes[0].id))),
        ("inputs/query", dict(scope_id=str(receipt.scopes[0].id), side="source", part="activity")),
    ]


def test_receipt_metadata_effects_and_frozen_equations_preserve_exact_lineage(
    environment, evidence
):
    client, _, _, _, _ = environment
    owner, data, _ = evidence
    headers = login(client)
    receipt = data["receipt"]
    metadata = get(client, headers, "inspect", id=str(receipt.id))
    assert metadata.status_code == 200 and metadata.headers["cache-control"] == "no-store"
    assert metadata.json()["mode"] == "reconciled" and metadata.json()["scope_count"] == 1
    assert metadata.json()["row_count"] == 3 and metadata.json()["selection_count"] == 0
    assert metadata.json()["created_at"] == receipt.created_at.isoformat()
    effects = get(client, headers, "rows/query", receipt_id=str(receipt.id)).json()["items"]
    assert len(effects) == 3 and all(item["record_revision"] == 1 for item in effects)
    scoped = get(client, headers, "scopes/inspect", id=str(receipt.scopes[0].id)).json()
    assert scoped["scope"]["kind"] == "cash" and scoped["scope"]["currency"] == "INR"
    assert scoped["scope"]["input_count"] == 6 and scoped["scope"]["date_basis"] == "booking"
    for side in ("source", "combined"):
        result = scoped[side]
        assert result["opening"] == "100.00" and result["closing"] == "87.70"
        assert result["posted_total"] == "-12.30" and result["difference"] == "0.00"
        assert result["outcome"] == "balanced" and result["posted_count"] == 1
        for part in ("opening", "activity", "closing"):
            rows = get(
                client,
                headers,
                "inputs/query",
                scope_id=str(receipt.scopes[0].id),
                side=side,
                part=part,
            ).json()["items"]
            assert len(rows) == 1
            row = rows[0]
            assert (
                row["id"]
                == row[
                    "source_row_id"
                    if side == "source"
                    else "event_id"
                    if part == "activity"
                    else "snapshot_id"
                ]
            )
            assert row["reference_revision"] == 1 and row["currency"] == "INR"
    for path, body in queries(data):
        response = get(client, headers, path, **body)
        assert response.status_code == 200
        assert all(
            marker not in response.text
            for marker in (
                "digest",
                "fingerprint",
                "request_canonical",
                "idempotency_key",
                "owner_id",
                "encrypted_reference",
                str(owner),
                data["request"].baseline,
            )
        )


def test_frozen_receipt_remains_identical_after_later_event_correction_and_remapping(
    environment, evidence
):
    client, _, workspace, _, _ = environment
    owner, data, accounts = evidence
    headers = login(client)
    before = [get(client, headers, path, **body).json() for path, body in queries(data)]
    receipt = data["receipt"]
    recorded = next(row for row in receipt.rows if row.event_id is not None)
    with workspace.transaction(owner) as unit:
        imports = ImportTransaction(unit)
        observed = imports.observation(data["source"].id, observation("f"))
        staged = imports.stage(observed.id, batch(cash(amount="-13.00")), expected_revision=0)
        row = imports.rows(staged.id)[0]
        imports.decide(row.id, "include", expected_revision=0)
        request = CompletionRequest(
            idempotency_key=uuid4(),
            batch_id=staged.id,
            batch_revision=1,
            baseline=CompletionBaseline(unit).current(),
            mode="limited",
            rows=(
                CompletionRow(
                    row_id=row.id,
                    review_revision=1,
                    operation="correct",
                    target_kind="event",
                    target_id=recorded.event_id,
                    target_revision=1,
                    correction_reason="source_correction",
                ),
            ),
        )
        correction = CompletionTransaction(unit, None).complete(request)
        assert correction.rows[0].record_revision == 2
    corrected = get(client, headers, "rows/query", receipt_id=str(correction.id)).json()["items"][0]
    assert corrected["operation"] == "correct" and corrected["outcome"] == "corrected"
    assert corrected["record_revision"] == 2 and corrected["event_id"] == str(recorded.event_id)
    with accounts.transaction(owner) as unit:
        unit.map(data["source"].id, None, expected_revision=1)
    assert [get(client, headers, path, **body).json() for path, body in queries(data)] == before
    with workspace.transaction(owner) as unit:
        assert CompletionTransaction(unit, None).complete(data["request"]) == receipt


def test_limited_excluded_rows_do_not_invent_comparisons_or_financial_targets(
    environment, evidence
):
    client, _, workspace, _, _ = environment
    owner, data, _ = evidence
    with workspace.transaction(owner) as unit:
        imports = ImportTransaction(unit)
        observed = imports.observation(data["source"].id, observation("d"))
        staged = imports.stage(observed.id, batch(cash()), expected_revision=0)
        row = imports.rows(staged.id)[0]
        imports.decide(row.id, "exclude", expected_revision=0)
        request = CompletionRequest(
            idempotency_key=uuid4(),
            batch_id=staged.id,
            batch_revision=1,
            baseline=CompletionBaseline(unit).current(),
            mode="limited",
            rows=(CompletionRow(row_id=row.id, review_revision=1, operation="exclude"),),
        )
        receipt = CompletionTransaction(unit, None).complete(request)
    headers = login(client)
    meta = get(client, headers, "inspect", id=str(receipt.id)).json()
    assert meta["mode"] == "limited" and meta["scope_count"] == 0
    assert get(client, headers, "scopes/query", receipt_id=str(receipt.id)).json()["items"] == []
    row = get(client, headers, "rows/query", receipt_id=str(receipt.id)).json()["items"][0]
    assert row["outcome"] == "excluded" and row["event_id"] is row["record_revision"] is None


def test_owner_parent_and_browser_boundaries_cover_every_receipt_route(
    environment, evidence, database
):
    client, _, workspace, _, admin = environment
    owner, data, accounts = evidence
    url, project = database
    provision_owner(url("bootstrap"), project, ISSUER, uuid4())
    other = sql(admin, "SELECT id FROM app.owners WHERE id<>:owner", owner=owner)[0][0]
    foreign = complete(accounts, workspace, other)
    headers = login(client)
    for path, body in queries(foreign):
        for target in (
            body,
            {
                key: value if key in {"side", "part"} else str(uuid4())
                for key, value in body.items()
            },
        ):
            response = get(client, headers, path, **target)
            assert response.status_code == 404 and set(response.json()) == {"error", "request_id"}
    own = get(client, headers, "query").json()["items"]
    assert [item["id"] for item in own] == [str(data["receipt"].id)]
    for path, body in queries(data):
        assert get(client, {}, path, **body).status_code == 403
        assert get(client, headers, path + "?limit=1", **body).status_code == 403
        assert get(client, headers, path, **body, owner_id=str(other)).status_code == 422
    client.cookies.delete("trading_dev_session")
    for path, body in queries(data):
        assert get(client, headers, path, **body).status_code == 401


def test_receipt_pages_are_bounded_and_survive_application_restart(environment, evidence, database):
    client, service, workspace, stub, _ = environment
    _, data, _ = evidence
    headers = login(client)
    original = [get(client, headers, path, **body).json() for path, body in queries(data)]
    for path, body in queries(data):
        if path.endswith("inspect"):
            continue
        expected = get(client, headers, path, **body).json()["items"]
        seen, cursor = [], None
        for _ in range(len(expected) + 1):
            page = get(client, headers, path, **body, after=cursor, limit=1).json()
            seen.extend(page["items"])
            cursor = page["next_after"]
            if cursor is None:
                break
        assert seen == expected
    statements = []

    def capture(connection, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(workspace._engine, "before_cursor_execute", capture)
    try:
        for path, body in queries(data):
            assert get(client, headers, path, **body).status_code == 200
    finally:
        event.remove(workspace._engine, "before_cursor_execute", capture)
    assert any("LIMIT 1001" in statement for statement in statements)
    assert all(
        word not in statement
        for statement in statements
        for word in ("SELECT *", "request_canonical", "idempotency_key", "encrypted_reference")
    )
    url, project = database
    restarted = BrowserAuth(stub.provider(), SessionDatabase(url("auth"), project), service.vault)
    store = WorkspaceDatabase(url("runtime"), project)
    with TestClient(create_app(browser=restarted, workspace=store), base_url=ORIGIN) as other:
        other.cookies.update(client.cookies)
        assert [
            get(other, headers, path, **body).json() for path, body in queries(data)
        ] == original


def test_zero_and_pending_counts_stay_distinct_in_frozen_comparison(environment, evidence):
    client, _, workspace, _, _ = environment
    owner, _, accounts = evidence
    data = complete(
        accounts,
        workspace,
        owner,
        definitions=(
            checkpoint(1, "0.00", "before_period"),
            cash(posting_state="pending"),
            checkpoint(3, "0.00", "after_period"),
        ),
    )
    headers = login(client)
    comparison = get(client, headers, "scopes/inspect", id=str(data["receipt"].scopes[0].id)).json()
    for side in ("source", "combined"):
        assert comparison[side]["posted_total"] == "0"
        assert comparison[side]["posted_count"] == 0 and comparison[side]["pending_count"] == 1


def test_native_cash_and_fractional_units_remain_separate_comparison_scopes(environment, evidence):
    client, _, workspace, _, _ = environment
    owner, _, accounts = evidence
    _, source, position, initial = investment_seed(accounts, owner=owner)
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
    data = complete(
        accounts,
        workspace,
        owner,
        source=source,
        position_id=position.id,
        definitions=(
            checkpoint(1, "100.00", "before_period", currency="USD"),
            checkpoint(2, "1.000000000000", "before_period", currency="USD", reference=reference),
            trade,
            checkpoint(4, "87.70", "after_period", currency="USD"),
            checkpoint(5, "1.123456789012", "after_period", currency="USD", reference=reference),
        ),
    )
    headers = login(client)
    scopes = get(client, headers, "scopes/query", receipt_id=str(data["receipt"].id)).json()[
        "items"
    ]
    assert {scope["kind"] for scope in scopes} == {"cash", "units"}
    for scope in scopes:
        result = get(client, headers, "scopes/inspect", id=scope["id"]).json()
        if scope["kind"] == "units":
            assert scope["position_id"] == str(position.id) and scope["currency"] is None
            assert result["source"]["posted_total"] == "0.123456789012"
            assert result["combined"]["closing"] == "1.123456789012"
        else:
            assert scope["currency"] == "USD" and result["source"]["posted_total"] == "-12.30"


def test_corrupt_frozen_comparison_fails_closed_without_invalidating_session(
    environment, evidence, monkeypatch
):
    client, _, _, _, _ = environment
    _, data, _ = evidence
    headers = login(client)
    original = CompletionReconciliation._pair

    def inconsistent(scope, inputs):
        pair = original(scope, inputs)
        return replace(pair, source=replace(pair.source, posted_total="-12.31"))

    with monkeypatch.context() as patch:
        patch.setattr(CompletionReconciliation, "_pair", staticmethod(inconsistent))
        response = get(client, headers, "scopes/inspect", id=str(data["receipt"].scopes[0].id))
    assert response.status_code == 503 and response.json()["error"] == "financial_data_unavailable"
    assert "set-cookie" not in response.headers and "-12.31" not in response.text
    assert (
        get(client, headers, "scopes/inspect", id=str(data["receipt"].scopes[0].id)).status_code
        == 200
    )


def test_maximum_batch_inspection_records_bounded_synthetic_query_measurements(
    environment, evidence
):
    client, _, workspace, _, _ = environment
    owner, _, accounts = evidence
    data = complete(
        accounts,
        workspace,
        owner,
        definitions=(
            checkpoint(1, "0.00", "before_period"),
            *(cash(index, "-1.00") for index in range(2, 100)),
            checkpoint(100, "-98.00", "after_period"),
        ),
    )
    receipt = data["receipt"]
    headers = login(client)
    requests = [
        ("imports/rows/query", dict(batch_id=str(receipt.manifest.batch_id), limit=100), 100),
        ("receipts/rows/query", dict(receipt_id=str(receipt.id), limit=100), 100),
        (
            "receipts/inputs/query",
            dict(scope_id=str(receipt.scopes[0].id), side="combined", part="activity", limit=100),
            98,
        ),
        ("receipts/scopes/inspect", dict(id=str(receipt.scopes[0].id)), 200),
    ]
    measurements = []
    for path, body, expected in requests:
        queries = 0

        def capture(connection, cursor, statement, parameters, context, many):
            nonlocal queries
            queries += 1

        event.listen(workspace._engine, "before_cursor_execute", capture)
        tracemalloc.start()
        started = time.perf_counter()
        try:
            response = client.post(f"/api/v1/finance/{path}", headers=headers, json=body)
            elapsed = time.perf_counter() - started
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
            event.remove(workspace._engine, "before_cursor_execute", capture)
        assert response.status_code == 200
        payload = response.json()
        count = len(payload["items"]) if "items" in payload else payload["scope"]["input_count"]
        assert count == expected and queries < 30 and len(response.content) <= 262144
        measurements.append(
            dict(
                route=path,
                records_or_inputs=count,
                workspace_statements=queries,
                response_bytes=len(response.content),
                elapsed_ms=round(elapsed * 1000, 3),
                python_traced_peak_bytes=peak,
            )
        )
    target = ROOT / ".cache/operations/financial-read-sample.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            dict(
                scope="synthetic local read-only HTTP requests; not production capacity",
                maximum_batch_rows=100,
                measurements=measurements,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
