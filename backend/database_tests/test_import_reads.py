"""Read-only import inspection preserves stale review context and exact source rows."""

from uuid import uuid4

import pytest
from sqlalchemy import event

from database_tests.test_accounts import definition
from database_tests.test_events import seed as security_seed
from database_tests.test_imports import batch, candidate, observation
from database_tests.test_instruments import security
from database_tests.test_preferences import environment as environment
from database_tests.test_preferences import login, sql
from tests.auth_support import ISSUER, SUBJECT
from trading_db.account_keys import ReferenceKeys
from trading_db.accounts import AccountDatabase
from trading_db.enrollment import provision_owner
from trading_db.imports import ImportTransaction, ImportUnavailable
from trading_db.instruments import InstrumentTransaction


def get(client, headers, path, **body):
    return client.post(f"/api/v1/finance/imports/{path}", headers=headers, json=body)


def populate(accounts, owner):
    with accounts.transaction(owner) as unit:
        account = unit.create(definition())
        source = unit.source("hdfc_statement", "FAKE-IMPORT-READ")
        unit.map(source.id, account.id, expected_revision=0)
        imports = ImportTransaction(unit._unit)
        observed = imports.observation(source.id, observation())
        staged = imports.stage(
            observed.id,
            batch(
                candidate(2),
                candidate(17, posting_state="pending"),
                candidate(35, values=()),
                candidate(99, kind="unsupported"),
            ),
            expected_revision=0,
        )
        rows = imports.rows(staged.id)
        imports.decide(rows[0].id, "include", expected_revision=0)
        imports.decide(rows[-1].id, "exclude", expected_revision=0, reason="duplicate_suspected")
    return dict(account=account, source=source, observation=observed, batch=staged, rows=rows)


@pytest.fixture
def evidence(environment, database):
    _, _, _, _, admin = environment
    owner = sql(
        admin,
        "SELECT owner_id FROM app.owner_identities WHERE subject=:subject",
        subject=str(SUBJECT),
    )[0][0]
    url, project = database
    accounts = AccountDatabase(url("runtime"), project, ReferenceKeys({1: b"i" * 32}, 1))
    try:
        yield owner, populate(accounts, owner), accounts
    finally:
        accounts.close()


def test_source_batch_and_rows_expose_exact_scope_and_review_state_without_posting(
    environment, evidence
):
    client, _, _, _, admin = environment
    owner, data, _ = evidence
    headers = login(client)
    observed = get(client, headers, "observations/query", source_id=str(data["source"].id))
    assert observed.status_code == 200
    item = observed.json()["items"][0]
    assert item["id"] == str(data["observation"].id) and item["coverage"] == "partial_activity"
    assert item["period_start"] == "2026-10-01" and item["is_current"]
    batches = get(client, headers, "batches/query", observation_id=item["id"]).json()["items"]
    assert len(batches) == 1 and batches[0]["row_count"] == 4 and batches[0]["source_current"]
    assert batches[0]["normalizer"] == "synthetic" and batches[0]["revision"] == 1
    response = get(client, headers, "rows/query", batch_id=str(data["batch"].id))
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    rows = response.json()["items"]
    assert [row["occurrence"] for row in rows] == [2, 17, 35, 99]
    assert [row["status"] for row in rows] == ["included", "reviewable", "blocked", "excluded"]
    assert (
        rows[0]["components"][0]["source"] == "-12.30"
        and rows[0]["components"][0]["currency"] == "INR"
    )
    assert rows[1]["posting_state"] == "pending"
    assert rows[2]["components"] == [] and rows[2]["issue"] == "not_supplied"
    assert rows[-1]["decision"]["reason"] == "duplicate_suspected" and rows[-1]["issue"] is None
    for row in rows:
        assert get(client, headers, "rows/inspect", id=row["id"]).json() == row
    assert all(
        marker not in response.text + observed.text
        for marker in (
            "digest",
            "fingerprint",
            "encrypted_reference",
            "FAKE-IMPORT-READ",
            str(owner),
        )
    )
    assert sql(admin, "SELECT count(*) FROM app.financial_events")[0][0] == 0


def test_review_history_and_live_mapping_state_match_the_domain_service(environment, evidence):
    client, _, workspace, _, _ = environment
    owner, data, accounts = evidence
    row = data["rows"][0]
    headers = login(client)
    with workspace.transaction(owner) as unit:
        imports = ImportTransaction(unit)
        imports.decide(row.id, "exclude", expected_revision=1)
        imports.decide(row.id, "reopen", expected_revision=2)
        imports.decide(row.id, "include", expected_revision=3)
    history = get(client, headers, "reviews/history", id=str(row.id)).json()["items"]
    assert [item["revision"] for item in history] == [4, 3, 2, 1]
    assert [item["is_current"] for item in history] == [True, False, False, False]
    with accounts.transaction(owner) as unit:
        unit.map(data["source"].id, None, expected_revision=1)
    result = get(client, headers, "rows/inspect", id=str(row.id)).json()
    with workspace.transaction(owner) as unit:
        expected = ImportTransaction(unit).get_row(row.id)
    assert (
        (result["status"], result["issue"])
        == (expected.status, expected.issue)
        == ("blocked", "stale_mapping")
    )
    assert (
        result["decision"]["account_mapping_revision"] == 1 and result["decision"]["revision"] == 4
    )
    assert get(client, headers, "reviews/history", id=str(row.id)).json()["items"] == history


def test_superseded_normalization_and_source_evidence_keep_distinct_currentness(
    environment, evidence
):
    client, _, workspace, _, _ = environment
    owner, data, _ = evidence
    headers = login(client)
    with workspace.transaction(owner) as unit:
        imports = ImportTransaction(unit)
        second = imports.stage(
            data["observation"].id,
            data["batch"].definition.model_copy(update={"normalizer_version": "2"}),
            expected_revision=1,
        )
    batches = get(
        client, headers, "batches/query", observation_id=str(data["observation"].id)
    ).json()["items"]
    assert [item["revision"] for item in batches] == [2, 1]
    assert [item["is_current"] for item in batches] == [True, False]
    old = get(client, headers, "rows/query", batch_id=str(data["batch"].id)).json()["items"]
    assert all(
        item["status"] == "superseded" and item["issue"] == "revised_evidence" for item in old
    )
    with workspace.transaction(owner) as unit:
        replacement = ImportTransaction(unit).observation(
            data["source"].id, observation("b"), previous_id=data["observation"].id
        )
    old_batches = get(
        client, headers, "batches/query", observation_id=str(data["observation"].id)
    ).json()["items"]
    assert old_batches[0]["is_current"] and not old_batches[0]["source_current"]
    assert all(
        item["status"] == "superseded"
        for item in get(client, headers, "rows/query", batch_id=str(second.id)).json()["items"]
    )
    assert get(client, headers, "batches/query", observation_id=str(replacement.id)).json() == {
        "items": [],
        "next_before": None,
    }


def test_security_mapping_revisions_are_bound_without_exposing_provider_identifiers(
    environment, evidence
):
    client, _, workspace, _, _ = environment
    owner, _, accounts = evidence
    _, _, _, rows = security_seed(accounts, owner=owner)
    row = rows[0]
    headers = login(client)
    before = get(client, headers, "rows/inspect", id=str(row.id)).json()
    assert before["status"] == "included" and before["decision"]["instrument_mapping_revision"] == 1
    with workspace.transaction(owner) as unit:
        identities = InstrumentTransaction(unit)
        alternate = identities.create(security(1))
        identities.map(row.definition.instrument_identifier_id, alternate.id, expected_revision=1)
    stale = get(client, headers, "rows/inspect", id=str(row.id)).json()
    with workspace.transaction(owner) as unit:
        imports = ImportTransaction(unit)
        expected = imports.get_row(row.id)
        assert (stale["status"], stale["issue"]) == (expected.status, expected.issue)
        imports.decide(row.id, "include", expected_revision=1)
    current = get(client, headers, "rows/inspect", id=str(row.id)).json()
    assert (
        current["status"] == "included" and current["decision"]["instrument_mapping_revision"] == 2
    )
    assert current["instrument_identifier_id"] == str(row.definition.instrument_identifier_id)


def queries(data):
    return [
        ("observations/query", dict(source_id=str(data["source"].id))),
        ("batches/query", dict(observation_id=str(data["observation"].id))),
        ("rows/query", dict(batch_id=str(data["batch"].id))),
        ("rows/inspect", dict(id=str(data["rows"][0].id))),
        ("reviews/history", dict(id=str(data["rows"][0].id))),
    ]


def test_foreign_unknown_parent_and_browser_boundaries_cover_all_import_routes(
    environment, evidence, database
):
    client, _, _, _, admin = environment
    owner, data, accounts = evidence
    url, project = database
    provision_owner(url("bootstrap"), project, ISSUER, uuid4())
    other = sql(admin, "SELECT id FROM app.owners WHERE id<>:owner", owner=owner)[0][0]
    foreign = populate(accounts, other)
    headers = login(client)
    for path, body in queries(foreign):
        for target in (body, {key: str(uuid4()) for key in body}):
            response = get(client, headers, path, **target)
            assert response.status_code == 404 and set(response.json()) == {"error", "request_id"}
    for path, body in queries(data):
        assert get(client, {}, path, **body).status_code == 403
        assert get(client, headers, path + "?limit=1", **body).status_code == 403
        assert get(client, headers, path, **body, owner_id=str(other)).status_code == 422
    client.cookies.delete("trading_dev_session")
    for path, body in queries(data):
        assert get(client, headers, path, **body).status_code == 401


def test_occurrence_and_revision_pagination_preserve_every_retained_record(environment, evidence):
    client, _, _, _, _ = environment
    _, data, _ = evidence
    headers = login(client)
    for path, body in queries(data):
        if path.endswith("inspect"):
            continue
        field = (
            "after_occurrence"
            if path == "rows/query"
            else "before"
            if path in ("batches/query", "reviews/history")
            else "after"
        )
        whole = get(client, headers, path, **body).json()["items"]
        seen, cursor = [], None
        for _ in range(len(whole) + 1):
            page = get(client, headers, path, **body, **{field: cursor}, limit=1).json()
            seen.extend(page["items"])
            cursor = page["next_" + field]
            if cursor is None:
                break
        assert seen == whole


def test_maximum_row_page_uses_constant_bounded_queries_and_retains_checksum_validation(
    environment, evidence, monkeypatch
):
    client, _, workspace, _, _ = environment
    owner, data, _ = evidence
    with workspace.transaction(owner) as unit:
        imports = ImportTransaction(unit)
        observed = imports.observation(data["source"].id, observation("c"))
        large = imports.stage(
            observed.id, batch(*(candidate(index) for index in range(1, 101))), expected_revision=0
        )
    headers = login(client)
    counts = []
    statements = []

    def capture(connection, cursor, statement, parameters, context, many):
        statements.append(statement)

    for limit in (1, 100):
        statements.clear()
        event.listen(workspace._engine, "before_cursor_execute", capture)
        try:
            response = get(client, headers, "rows/query", batch_id=str(large.id), limit=limit)
        finally:
            event.remove(workspace._engine, "before_cursor_execute", capture)
        assert response.status_code == 200 and len(response.json()["items"]) == limit
        assert any("LIMIT 801" in statement for statement in statements)
        assert all(
            term not in statement
            for statement in statements
            for term in ("encrypted_reference", "fingerprint")
        )
        counts.append(len(statements))
    assert counts[0] == counts[1] and counts[1] < 30

    def invalid(store, batch_id):
        raise ImportUnavailable()

    with monkeypatch.context() as patch:
        patch.setattr(ImportTransaction, "get_batch", invalid)
        failed = get(client, headers, "rows/query", batch_id=str(large.id))
    assert failed.status_code == 503 and failed.json()["error"] == "financial_data_unavailable"
    assert "set-cookie" not in failed.headers
    assert get(client, headers, "rows/query", batch_id=str(large.id)).status_code == 200
