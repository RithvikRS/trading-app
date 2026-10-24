"""Actual restricted-role HTTP review, dry-run rollback, completion and investment reads."""

from uuid import uuid4

import pytest

from database_tests.test_events import seed
from database_tests.test_imports import batch, observation
from database_tests.test_preferences import environment as environment
from database_tests.test_preferences import login, sql
from database_tests.test_snapshots import snapshot_candidate
from tests.auth_support import SUBJECT
from trading_db.account_keys import ReferenceKeys
from trading_db.accounts import AccountDatabase
from trading_db.completion import CompletionTransaction
from trading_db.imports import ImportTransaction
from trading_db.snapshot_review import SnapshotReviewTransaction


@pytest.fixture
def evidence(environment, database):
    _, _, workspace, _, admin = environment
    owner = sql(
        admin,
        "SELECT owner_id FROM app.owner_identities WHERE subject=:subject",
        subject=str(SUBJECT),
    )[0][0]
    url, project = database
    accounts = AccountDatabase(url("runtime"), project, ReferenceKeys({1: b"h" * 32}, 1))
    try:
        account, source, position, initial = seed(accounts, owner=owner)
        with workspace.transaction(owner) as unit:
            imports = ImportTransaction(unit)
            observed = imports.observation(
                source.id, observation("b").model_copy(update={"coverage": "snapshot"})
            )
            staged = imports.stage(
                observed.id,
                batch(snapshot_candidate(initial[0].definition.instrument_identifier_id)),
                expected_revision=0,
            )
            row = imports.rows(staged.id)[0]
        yield owner, account, source, position, staged, row
    finally:
        accounts.close()


def post(client, headers, path, **body):
    return client.post("/api/v1/finance/" + path, headers=headers, json=body)


def preview_body(evidence):
    _, _, _, position, staged, row = evidence
    return dict(
        idempotency_key=str(uuid4()),
        batch_id=str(staged.id),
        batch_revision=1,
        rows=[
            dict(
                row_id=str(row.id),
                review_revision=1,
                operation="record",
                position_id=str(position.id),
                select=True,
            )
        ],
    )


def test_review_rehearsal_completion_receipt_and_connected_exact_values(environment, evidence):
    client, _, _, _, admin = environment
    _, account, _, position, staged, row = evidence
    headers = login(client)
    queue = post(client, headers, "snapshot-review/query").json()
    assert [item["id"] for item in queue["items"]] == [str(staged.id)]
    inspection = post(client, headers, "snapshot-review/inspect", id=str(staged.id))
    assert inspection.status_code == 200 and inspection.json()["rows"][0]["status"] == "reviewable"
    before = sql(admin, "SELECT count(*) FROM app.snapshot_records")[0][0]
    assert (
        post(
            client,
            headers,
            "snapshot-review/decide",
            row_id=str(row.id),
            action="include",
            expected_revision=0,
        ).status_code
        == 200
    )
    prepared = post(client, headers, "snapshot-review/preview", **preview_body(evidence))
    assert prepared.status_code == 200, prepared.text
    assert sql(admin, "SELECT count(*) FROM app.snapshot_records")[0][0] == before
    assert sql(admin, "SELECT count(*) FROM app.completion_receipts")[0][0] == 0
    completed = post(client, headers, "snapshot-review/complete", token=prepared.json()["token"])
    assert completed.status_code == 200, completed.text
    assert completed.json()["mode"] == "limited" and completed.json()["coverage"] == "snapshot"
    assert (
        post(client, headers, "snapshot-review/complete", token=prepared.json()["token"]).json()
        == completed.json()
    )
    assert sql(admin, "SELECT count(*) FROM app.snapshot_records")[0][0] == before + 1
    assert sql(admin, "SELECT count(*) FROM app.financial_events")[0][0] == 0
    result = post(client, headers, "investments/query", account_id=str(account.id))
    assert result.status_code == 200, result.text
    item = result.json()["items"][0]
    assert item["id"] == str(position.id) and item["instrument"]["name"] == "Synthetic security"
    snapshot = item["choices"][0]["snapshot"]
    assert snapshot["components"][0]["source"] == "0.123456789012"
    assert snapshot["coverage"] == "snapshot"
    assert (
        post(
            client,
            headers,
            "snapshot-review/decide",
            row_id=str(row.id),
            action="reopen",
            expected_revision=1,
        ).status_code
        == 409
    )
    assert client.get("/api/v1/auth/session", headers=headers).status_code == 200


def test_stale_preview_and_wrong_context_never_publish(environment, evidence):
    client, _, workspace, _, admin = environment
    owner, _, _, _, _, row = evidence
    headers = login(client)
    assert (
        post(
            client,
            headers,
            "snapshot-review/decide",
            row_id=str(row.id),
            action="include",
            expected_revision=0,
        ).status_code
        == 200
    )
    prepared = post(client, headers, "snapshot-review/preview", **preview_body(evidence))
    assert prepared.status_code == 200, prepared.text
    with workspace.transaction(owner) as unit:
        ImportTransaction(unit).decide(row.id, "reopen", expected_revision=1)
    assert (
        post(
            client, headers, "snapshot-review/complete", token=prepared.json()["token"]
        ).status_code
        == 409
    )
    assert (
        post(
            client,
            {**headers, "X-Workspace-Context": "b" * 64},
            "snapshot-review/complete",
            token=prepared.json()["token"],
        ).status_code
        == 412
    )
    assert sql(admin, "SELECT count(*) FROM app.snapshot_records")[0][0] == 0
    assert sql(admin, "SELECT count(*) FROM app.completion_receipts")[0][0] == 0


def test_exclusions_reopen_and_failed_position_keep_whole_batch_atomic(environment, evidence):
    client, _, _, _, admin = environment
    _, _, _, _, staged, row = evidence
    headers = login(client)
    for revision, action in enumerate(("exclude", "reopen", "include")):
        assert (
            post(
                client,
                headers,
                "snapshot-review/decide",
                row_id=str(row.id),
                action=action,
                expected_revision=revision,
            ).status_code
            == 200
        )
    body = preview_body(evidence)
    body["rows"][0].update(review_revision=3, position_id=str(uuid4()))
    assert post(client, headers, "snapshot-review/preview", **body).status_code == 409
    assert sql(admin, "SELECT count(*) FROM app.snapshot_records")[0][0] == 0
    assert (
        post(
            client,
            headers,
            "snapshot-review/decide",
            row_id=str(row.id),
            action="exclude",
            expected_revision=3,
        ).status_code
        == 200
    )
    body["rows"] = [dict(row_id=str(row.id), review_revision=4, operation="exclude")]
    prepared = post(client, headers, "snapshot-review/preview", **body)
    assert prepared.status_code == 200
    result = post(client, headers, "snapshot-review/complete", token=prepared.json()["token"])
    assert result.status_code == 200 and result.json()["selection_count"] == 0
    assert sql(admin, "SELECT count(*) FROM app.snapshot_records")[0][0] == 0
    assert (
        post(client, headers, "snapshot-review/inspect", id=str(staged.id)).json()["receipt"]["id"]
        == result.json()["id"]
    )


@pytest.mark.parametrize("failure", ["expired", "disabled"])
def test_session_or_owner_failure_after_completion_rolls_back_receipt(
    environment, evidence, monkeypatch, failure
):
    client, _, _, _, admin = environment
    row = evidence[-1]
    headers = login(client)
    assert (
        post(
            client,
            headers,
            "snapshot-review/decide",
            row_id=str(row.id),
            action="include",
            expected_revision=0,
        ).status_code
        == 200
    )
    prepared = post(client, headers, "snapshot-review/preview", **preview_body(evidence))
    original = CompletionTransaction.complete

    def interrupted(unit, command):
        result = original(unit, command)
        sql(
            admin,
            "UPDATE app.owners SET is_active=false"
            if failure == "disabled"
            else "UPDATE app.auth_sessions SET idle_until=clock_timestamp()-interval '1 second'",
        )
        return result

    monkeypatch.setattr(CompletionTransaction, "complete", interrupted)
    assert (
        post(
            client, headers, "snapshot-review/complete", token=prepared.json()["token"]
        ).status_code
        == 401
    )
    assert sql(admin, "SELECT count(*) FROM app.snapshot_records")[0][0] == 0
    assert sql(admin, "SELECT count(*) FROM app.completion_receipts")[0][0] == 0


def test_overlap_requires_explicit_correction_and_never_adds_quantities(environment, evidence):
    client, _, workspace, _, admin = environment
    owner, account, source, position, _, row = evidence
    headers = login(client)
    assert (
        post(
            client,
            headers,
            "snapshot-review/decide",
            row_id=str(row.id),
            action="include",
            expected_revision=0,
        ).status_code
        == 200
    )
    first = post(client, headers, "snapshot-review/preview", **preview_body(evidence)).json()
    assert (
        post(client, headers, "snapshot-review/complete", token=first["token"]).status_code == 200
    )
    original = post(client, headers, "investments/query", account_id=str(account.id)).json()[
        "items"
    ][0]["choices"][0]["snapshot"]
    with workspace.transaction(owner) as unit:
        imports = ImportTransaction(unit)
        observed = imports.observation(
            source.id, observation("c").model_copy(update={"coverage": "snapshot"})
        )
        staged = imports.stage(
            observed.id,
            batch(
                snapshot_candidate(row.definition.instrument_identifier_id, amount="2.000000000001")
            ),
            expected_revision=0,
        )
        correction = imports.rows(staged.id)[0]
    assert (
        post(
            client,
            headers,
            "snapshot-review/decide",
            row_id=str(correction.id),
            action="include",
            expected_revision=0,
        ).status_code
        == 200
    )
    body = dict(
        idempotency_key=str(uuid4()),
        batch_id=str(staged.id),
        batch_revision=1,
        rows=[
            dict(
                row_id=str(correction.id),
                review_revision=1,
                operation="record",
                position_id=str(position.id),
                select=True,
                selection_revision=1,
            )
        ],
    )
    assert post(client, headers, "snapshot-review/preview", **body).status_code == 409
    assert sql(admin, "SELECT count(*) FROM app.snapshot_records")[0][0] == 1
    body["rows"] = [
        dict(
            row_id=str(correction.id),
            review_revision=1,
            operation="correct",
            target_id=original["id"],
            target_revision=1,
            correction_reason="source_correction",
            select=True,
            selection_revision=1,
        )
    ]
    prepared = post(client, headers, "snapshot-review/preview", **body)
    assert prepared.status_code == 200, prepared.text
    assert (
        post(
            client, headers, "snapshot-review/complete", token=prepared.json()["token"]
        ).status_code
        == 200
    )
    result = post(client, headers, "investments/query", account_id=str(account.id)).json()
    assert len(result["items"]) == 1
    selected = result["items"][0]["choices"][0]["snapshot"]
    assert selected["revision"] == 2 and selected["components"][0]["source"] == "2.000000000001"
    assert sql(admin, "SELECT count(*) FROM app.financial_events")[0][0] == 0


def test_unknown_and_other_owner_objects_cannot_be_reviewed(environment, evidence, database):
    from tests.auth_support import ISSUER
    from trading_db.enrollment import provision_owner

    client, _, workspace, _, admin = environment
    url, project = database
    subject = uuid4()
    provision_owner(url("bootstrap"), project, ISSUER, subject)
    other = sql(
        admin,
        "SELECT owner_id FROM app.owner_identities WHERE subject=:subject",
        subject=str(subject),
    )[0][0]
    with workspace.transaction(other) as unit:
        review = SnapshotReviewTransaction(unit)
        from trading_api.read_contracts import PageQuery

        assert not review.queue(PageQuery()).items
    headers = login(client)
    for path, body in [
        ("snapshot-review/inspect", dict(id=str(uuid4()))),
        (
            "snapshot-review/decide",
            dict(row_id=str(uuid4()), action="include", expected_revision=0),
        ),
        (
            "snapshot-review/account-mapping",
            dict(source_id=str(evidence[2].id), account_id=str(uuid4()), expected_revision=1),
        ),
        (
            "snapshot-review/position",
            dict(
                account_id=str(uuid4()),
                instrument_id=str(evidence[3].instrument_id),
                holding_form="custody",
            ),
        ),
    ]:
        result = post(client, headers, path, **body)
        assert result.status_code == 409 and set(result.json()) == {"error", "request_id"}
    assert client.get("/api/v1/auth/session", headers=headers).status_code == 200
