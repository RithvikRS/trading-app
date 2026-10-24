"""Exact current/history API evidence over real PostgreSQL and synthetic source rows."""

import logging
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from database_tests.test_events import seed
from database_tests.test_lots_corrections import cancellation, lot_candidate, reviewed
from database_tests.test_preferences import environment as environment
from database_tests.test_preferences import login, sql
from tests.auth_support import ISSUER, SUBJECT
from trading_db.account_keys import ReferenceKeys
from trading_db.accounts import AccountDatabase, AccountTransaction
from trading_db.enrollment import provision_owner
from trading_db.events import EventTransaction
from trading_db.evidence_reads import EvidenceReadTransaction
from trading_db.lots import LotTransaction

BASE = "/api/v1/finance"


def get(client, headers, route, **body):
    return client.post(f"{BASE}/{route}", headers=headers, json=body)


def populate(accounts, workspace, owner):
    account, source, position, initial = seed(accounts, owner=owner, states=("pending", "posted"))
    with workspace.transaction(owner) as unit:
        events = EventTransaction(unit)
        originals = [
            events.record(row.id, expected_review_revision=1, position_id=position.id)
            for row in initial
        ]
    changed = tuple(
        value.model_copy(update={"source": "-15.00"}) if value.role == "net_cash" else value
        for value in initial[0].definition.values
    )
    definition = initial[0].definition
    event_rows = reviewed(
        accounts,
        source.id,
        definition.model_copy(update={"posting_state": "posted"}),
        definition.model_copy(
            update={"occurrence": 2, "posting_state": "posted", "values": changed}
        ),
        cancellation(3),
        definition.model_copy(
            update={"occurrence": 4, "posting_state": "posted", "values": changed}
        ),
        cancellation(5),
        owner=owner,
    )
    for index, reason in enumerate(
        ("posting_update", "source_correction", "cancellation", "reinstatement"), 1
    ):
        with workspace.transaction(owner) as unit:
            EventTransaction(unit).correct(
                originals[0].id,
                event_rows[index - 1].id,
                expected_revision=index,
                expected_review_revision=1,
                reason=reason,
            )
    with workspace.transaction(owner) as unit:
        EventTransaction(unit).correct(
            originals[1].id,
            event_rows[4].id,
            expected_revision=1,
            expected_review_revision=1,
            reason="cancellation",
        )
    reference = initial[0].definition.instrument_identifier_id
    lot_rows = reviewed(
        accounts,
        source.id,
        lot_candidate(reference, scope="lot_acquisition", quantity="10.000000000001"),
        lot_candidate(reference, occurrence=2),
        lot_candidate(reference, occurrence=3, quantity="0"),
        cancellation(4),
        lot_candidate(reference, occurrence=5, quantity="2.000000000001"),
        lot_candidate(reference, occurrence=6, quantity="3.000000000001"),
        owner=owner,
    )
    with workspace.transaction(owner) as unit:
        lots = LotTransaction(unit)
        acquired = lots.record(lot_rows[0].id, position.id, expected_review_revision=1)
        remaining = lots.record(
            lot_rows[1].id,
            position.id,
            expected_review_revision=1,
            lot_id=acquired.lot_id,
        )
        separate = lots.record(lot_rows[5].id, position.id, expected_review_revision=1)
    for index, reason in enumerate(("source_correction", "cancellation", "reinstatement"), 1):
        with workspace.transaction(owner) as unit:
            LotTransaction(unit).correct(
                remaining.id,
                lot_rows[index + 1].id,
                expected_revision=index,
                expected_review_revision=1,
                reason=reason,
            )
    bank, _, _, cash_rows = seed(
        accounts, owner=owner, kind="cash_movement", states=("posted", "pending")
    )
    with workspace.transaction(owner) as unit:
        cash_events = [
            EventTransaction(unit).record(row.id, expected_review_revision=1) for row in cash_rows
        ]
    return dict(
        account=account,
        source=source,
        position=position,
        event=originals[0],
        cancelled=originals[1],
        acquired=acquired,
        remaining=remaining,
        separate=separate,
        bank=bank,
        cash=cash_events,
    )


@pytest.fixture
def evidence(environment, database):
    _, _, workspace, _, admin = environment
    own = sql(
        admin,
        "SELECT owner_id FROM app.owner_identities WHERE subject=:subject",
        subject=str(SUBJECT),
    )[0][0]
    url, project = database
    accounts = AccountDatabase(url("runtime"), project, ReferenceKeys({1: b"g" * 32}, 1))
    try:
        yield own, populate(accounts, workspace, own), accounts
    finally:
        accounts.close()


def values(record):
    return {value["role"]: value for value in record["components"]}


def test_latest_event_economics_and_all_historical_revisions_are_explicit(
    environment, evidence, caplog
):
    client, _, _, _, _ = environment
    own, data, _ = evidence
    headers = login(client)
    with caplog.at_level(logging.INFO):
        latest = get(client, headers, "events/query", account_id=str(data["account"].id))
        history = get(client, headers, "events/history", id=str(data["event"].id))
    assert latest.status_code == history.status_code == 200
    assert latest.headers["cache-control"] == "no-store"
    records = {item["id"]: item for item in latest.json()["items"]}
    assert set(records) == {str(data["event"].id), str(data["cancelled"].id)}
    current = records[str(data["event"].id)]
    assert current["revision"] == 5 and current["is_current"] and current["status"] == "active"
    assert current["posting_state"] == "posted" and current["correction_reason"] == "reinstatement"
    assert current["trade_date"] == "2026-10-21" and current["settlement_date"] == "2026-10-23"
    assert current["source_id"] == str(data["source"].id)
    assert current["coverage"] == "partial_activity" and current["period_start"] == "2026-10-01"
    assert values(current)["net_cash"] == dict(
        role="net_cash", source="-15.00", currency="USD", missing_reason=None
    )
    assert values(current)["quantity"]["source"] == "0.123456789012"
    assert (
        values(current)["fee"]["source"] is None
        and values(current)["fee"]["missing_reason"] == "not_supplied"
    )
    assert values(current)["withholding"]["source"] == "0.00000000"
    assert records[str(data["cancelled"].id)]["components"] == []
    assert records[str(data["cancelled"].id)]["status"] == "cancelled"
    versions = history.json()["items"]
    assert [item["revision"] for item in versions] == [5, 4, 3, 2, 1]
    assert [item["is_current"] for item in versions] == [
        True,
        False,
        False,
        False,
        False,
    ]
    assert versions[1]["status"] == "cancelled" and versions[1]["components"] == []
    assert (
        versions[-1]["posting_state"] == "pending"
        and values(versions[-1])["net_cash"]["source"] == "-12.30"
    )
    assert str(own) not in latest.text + history.text
    assert all(
        marker not in latest.text + history.text
        for marker in ("digest", "fingerprint", "encrypted_reference", "FAKE-EVENT")
    )
    assert "-15.00" not in caplog.text and str(data["account"].id) not in caplog.text


def test_native_cash_and_pending_are_not_combined_into_balances(environment, evidence):
    client, _, _, _, _ = environment
    _, data, _ = evidence
    response = get(client, login(client), "events/query", account_id=str(data["bank"].id))
    assert response.status_code == 200
    items = response.json()["items"]
    assert {item["id"] for item in items} == {str(event.id) for event in data["cash"]}
    assert {item["posting_state"] for item in items} == {"posted", "pending"}
    assert all(values(item)["net_cash"]["currency"] == "INR" for item in items)
    assert all(item["position_id"] is None and item["instrument_id"] is None for item in items)
    assert set(response.json()) == {"items", "next_after"}


def test_lot_identity_acquisition_remaining_and_basis_are_independent(environment, evidence):
    client, _, _, _, _ = environment
    _, data, _ = evidence
    headers = login(client)
    lots = get(client, headers, "lots/query", position_id=str(data["position"].id))
    assert lots.status_code == 200
    assert {item["id"] for item in lots.json()["items"]} == {
        str(data["acquired"].lot_id),
        str(data["separate"].lot_id),
    }
    observations = get(
        client, headers, "lots/observations/query", lot_id=str(data["acquired"].lot_id)
    )
    assert observations.status_code == 200
    records = {item["scope"]: item for item in observations.json()["items"]}
    assert set(records) == {"lot_acquisition", "lot_remaining"}
    assert values(records["lot_acquisition"])["quantity"]["source"] == "10.000000000001"
    assert records["lot_acquisition"]["acquisition_date"] == "2026-09-01"
    remaining = records["lot_remaining"]
    assert (
        remaining["revision"] == 4
        and remaining["is_current"]
        and remaining["acquisition_date"] is None
    )
    assert values(remaining)["quantity"]["source"] == "2.000000000001"
    assert values(remaining)["reported_tax_basis"] == dict(
        role="reported_tax_basis",
        source=None,
        currency="INR",
        missing_reason="incomplete_history",
    )
    assert values(remaining)["acquisition_cost"]["source"] == "12.00000000"
    assert values(remaining)["discount_amount"]["source"] == "0.30000000"
    history = get(
        client, headers, "lots/observations/history", id=str(data["remaining"].id)
    ).json()["items"]
    assert [item["revision"] for item in history] == [4, 3, 2, 1]
    assert history[1]["status"] == "cancelled" and history[1]["components"] == []
    assert values(history[2])["quantity"]["source"] == "0"
    assert values(history[3])["quantity"]["source"] == "0.123456789012"


def routes(data):
    return [
        (
            "events/query",
            {"account_id": str(data["account"].id)},
            "next_after",
            "after",
        ),
        ("events/history", {"id": str(data["event"].id)}, "next_before", "before"),
        (
            "lots/query",
            {"position_id": str(data["position"].id)},
            "next_after",
            "after",
        ),
        (
            "lots/observations/query",
            {"lot_id": str(data["acquired"].lot_id)},
            "next_after",
            "after",
        ),
        (
            "lots/observations/history",
            {"id": str(data["remaining"].id)},
            "next_before",
            "before",
        ),
    ]


def test_all_current_and_history_pages_preserve_complete_ordered_records(environment, evidence):
    client, _, _, _, _ = environment
    _, data, _ = evidence
    headers = login(client)
    for route, body, cursor_field, query_field in routes(data):
        all_items = get(client, headers, route, **body).json()["items"]
        seen, cursor = [], None
        for _ in range(len(all_items) + 1):
            response = get(client, headers, route, **body, **{query_field: cursor}, limit=1)
            assert response.status_code == 200
            page = response.json()
            seen.extend(page["items"])
            cursor = page[cursor_field]
            if cursor is None:
                break
        assert seen == all_items
        last = seen[-1]["revision" if query_field == "before" else "id"]
        assert get(client, headers, route, **body, **{query_field: last}).json() == {
            "items": [],
            cursor_field: None,
        }


def test_foreign_and_unknown_parents_are_uniform_and_owner_header_is_ignored(
    environment, evidence, database
):
    client, _, workspace, _, admin = environment
    own, data, accounts = evidence
    url, project = database
    provision_owner(url("bootstrap"), project, ISSUER, uuid4())
    other = sql(admin, "SELECT id FROM app.owners WHERE id<>:own", own=own)[0][0]
    foreign = populate(accounts, workspace, other)
    headers = {**login(client), "X-Owner-ID": str(other)}
    for route, body, _, _ in routes(foreign):
        for target in (body, {key: str(uuid4()) for key in body}):
            response = get(client, headers, route, **target)
            assert response.status_code == 404 and response.json()["error"] == "not_found"
            assert set(response.json()) == {"error", "request_id"}
    assert (
        get(client, headers, "events/query", account_id=str(data["account"].id)).status_code == 200
    )


def test_archived_accounts_preserve_evidence_with_explicit_state(environment, evidence):
    client, _, workspace, _, _ = environment
    own, data, _ = evidence
    with workspace.transaction(own) as unit:
        AccountTransaction(unit, None).archive(data["account"].id, expected_revision=1)
    headers = login(client)
    for route, body, _, _ in routes(data):
        response = get(client, headers, route, **body)
        assert response.status_code == 200
        assert all(item["account_state"] == "archived" for item in response.json()["items"])


def test_new_routes_inherit_csrf_authentication_and_strict_request_schemas(environment, evidence):
    client, _, _, _, _ = environment
    _, data, _ = evidence
    headers = login(client)
    for route, body, _, field in routes(data):
        assert get(client, {}, route, **body).status_code == 403
        assert get(client, headers, route + "?limit=1", **body).status_code == 403
        for update in (
            {"owner_id": str(uuid4())},
            {"limit": True},
            {"limit": 101},
            {field: "bad"},
        ):
            response = get(client, headers, route, **body, **update)
            assert response.status_code == 422 and set(response.json()) == {
                "error",
                "request_id",
            }
    client.cookies.delete("trading_dev_session")
    for route, body, _, _ in routes(data):
        assert get(client, headers, route, **body).status_code == 401


def test_data_failure_preserves_session_and_queries_are_bounded_without_private_columns(
    environment, evidence, monkeypatch
):
    client, _, workspace, _, _ = environment
    _, data, _ = evidence
    headers = login(client)
    statements = []

    def capture(connection, cursor, statement, parameters, context, many):
        statements.append((statement, parameters))

    event.listen(workspace._engine, "before_cursor_execute", capture)
    try:
        response = get(client, headers, "events/query", account_id=str(data["account"].id), limit=1)
    finally:
        event.remove(workspace._engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    projections = [
        (statement, params) for statement, params in statements if "AS components" in statement
    ]
    assert len(projections) == 1 and projections[0][1]["limit"] == 2
    assert "LIMIT 9" in projections[0][0]
    assert all(
        term not in statement.lower()
        for statement, _ in statements
        for term in ("select *", "encrypted_reference", "fingerprint", "digest")
    )

    def fail(reads, query):
        raise SQLAlchemyError("synthetic-private-economics")

    with monkeypatch.context() as patch:
        patch.setattr(EvidenceReadTransaction, "events", fail)
        failed = get(client, headers, "events/query", account_id=str(data["account"].id))
    assert failed.status_code == 503 and "set-cookie" not in failed.headers
    assert failed.json()["error"] == "financial_data_unavailable" and "private" not in failed.text
    assert (
        get(client, headers, "events/query", account_id=str(data["account"].id)).status_code == 200
    )
