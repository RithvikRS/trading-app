"""Real protected typed credit reads: exact history, privacy, ownership and waits."""

import copy
import warnings
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from queue import Queue
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from database_tests import test_credit_current as current_sql
from database_tests.test_credit_reads import populate, query, snapshot
from database_tests.test_credit_reads import seeded as seeded
from database_tests.test_preferences import ORIGIN, login, sql
from database_tests.test_preferences import environment as environment
from tests.auth_support import ISSUER
from tests.test_credit_evidence_read_contracts import KINDS, PRIVATE, cash, values
from trading_api.credit_cards import CardCurrentValues, CardEntryValues, CardStatementValues
from trading_api.credit_evidence_contracts import CreditEvidenceQuery
from trading_api.finance import FinancialDate, FinancialInstant, FinancialValue
from trading_auth.models import (
    AuthenticationDenied,
    AuthenticationLimited,
    AuthenticationUnavailable,
    WorkspaceContextChanged,
)
from trading_db import credit_evidence_reads as projections
from trading_db.credit_accounts import CreditAccountTransaction
from trading_db.credit_current import CreditCurrentTransaction
from trading_db.credit_entries import CreditEntryTransaction
from trading_db.credit_reads import CreditReadTransaction
from trading_db.credit_sources import CreditSourceTransaction
from trading_db.credit_statements import CreditStatementTransaction
from trading_db.enrollment import provision_owner

READS = projections.CreditEvidenceReadTransaction
SERVICES = {
    "statement": CreditStatementTransaction,
    "current": CreditCurrentTransaction,
    "entry": CreditEntryTransaction,
}
RESOURCES = ("evidence/query", "evidence/history", "evidence/inspect")


def native(kind, payload):
    fields = {}
    for name, value in payload.items():
        if isinstance(value, dict):
            fields[name] = FinancialValue(
                "cash",
                value["source"],
                currency=value["currency"],
                missing_reason=value["missing_reason"],
            )
        elif name.endswith("_date") or name in ("period_start", "period_end"):
            fields[name] = FinancialDate(value) if value is not None else None
        elif name == "as_of_instant":
            fields[name] = FinancialInstant(value) if value is not None else None
        else:
            fields[name] = value
    return {
        "statement": CardStatementValues,
        "current": CardCurrentValues,
        "entry": CardEntryValues,
    }[kind](**fields)


def evidence(workspace, owner, account, alternate):
    payloads = {}
    roots = {}
    with workspace.transaction(owner) as unit:
        sources = CreditSourceTransaction(unit)
        stream = sources.create()
        sources.map(stream.id, account, expected_revision=0)
        for kind in KINDS:
            roots[kind] = uuid4()
            first = values(kind)
            second = copy.deepcopy(first)
            if kind == "statement":
                second["total_due"] = cash("-0.00")
            elif kind == "current":
                second.update(
                    as_of_date="2026-10-02", as_of_instant="2026-10-02T00:15:00.000001-04:00"
                )
            else:
                second.update(
                    role="posted_credit",
                    treatment="unsupported",
                    posting_date="2026-10-02",
                    original_amount=None,
                )
            payloads[kind] = [first, second]
            store = SERVICES[kind](unit)
            store.record(roots[kind], stream.id, 1, native(kind, first))
            store.record(roots[kind], stream.id, 1, native(kind, second), expected_revision=1)
        sources.map(stream.id, alternate, expected_revision=1)
        sources.map(stream.id, account, expected_revision=2)
        for kind in KINDS:
            third = copy.deepcopy(payloads[kind][-1])
            third[
                {
                    "statement": "closing_liability",
                    "current": "outstanding",
                    "entry": "billing_amount",
                }[kind]
            ] = cash("0.00")
            payloads[kind].append(third)
            SERVICES[kind](unit).record(
                roots[kind], stream.id, 3, native(kind, third), expected_revision=2
            )
    return dict(source=stream.id, roots=roots, values=payloads, account=account)


@pytest.fixture
def records(environment, seeded):
    _, _, workspace, _, _ = environment
    owner, parents = seeded
    return owner, parents, evidence(workspace, owner, parents["active"].id, parents["empty"].id)


def body(data, kind, resource):
    result = dict(account_id=str(data["account"]), kind=kind)
    if resource != "evidence/query":
        result["id"] = str(data["roots"][kind])
    if resource == "evidence/inspect":
        result["at_revision"] = 1
    return result


@pytest.mark.parametrize("kind", KINDS)
def test_typed_reads_preserve_exact_history_and_leave_all_durable_records_unchanged(
    environment, records, kind, caplog
):
    client, _, workspace, _, admin = environment
    owner, parents, data = records
    headers = login(client)
    before = snapshot(admin)
    observed = []

    def capture(connection, cursor, statement, parameters, context, many):
        observed.append(statement.lower())

    event.listen(workspace._engine, "before_cursor_execute", capture)
    try:
        responses = {
            route: query(client, headers, route, **body(data, kind, route)) for route in RESOURCES
        }
    finally:
        event.remove(workspace._engine, "before_cursor_execute", capture)
    for response in responses.values():
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert (
            response.headers["referrer-policy"] == "no-referrer" and str(owner) not in response.text
        )
    latest = responses["evidence/query"].json()["items"]
    history = responses["evidence/history"].json()["items"]
    exact = responses["evidence/inspect"].json()
    assert len(latest) == 1 and latest[0] == history[0]
    assert [item["revision"] for item in history] == [3, 2, 1]
    assert [item["mapping_revision"] for item in history] == [3, 1, 1]
    assert [item["is_latest_revision"] for item in history] == [True, False, False]
    assert [item["values"] for item in history] == list(reversed(data["values"][kind]))
    assert exact == history[-1] and exact["source_id"] == str(data["source"])
    assert set(exact) == {
        "id",
        "kind",
        "revision",
        "previous_revision",
        "source_id",
        "mapping_revision",
        "account_id",
        "account_state",
        "is_latest_revision",
        "values",
    }
    assert snapshot(admin) == before and PRIVATE not in caplog.text
    assert all(
        "select *" not in statement and "for update" not in statement for statement in observed
    )
    with workspace._engine.connect() as connection:
        assert connection.execute(
            text("SELECT current_setting('app.owner_id',true)")
        ).scalar_one() in (None, "")
        assert (
            connection.execute(text("SELECT current_setting('transaction_read_only')")).scalar_one()
            == "off"
        )


@pytest.mark.parametrize("kind", KINDS)
def test_history_cursor_exact_inspection_and_archived_remapped_provenance(
    environment, records, kind
):
    client, _, workspace, _, _ = environment
    owner, parents, data = records
    headers = login(client)
    request = body(data, kind, "evidence/history")
    seen = []
    before = None
    for _ in range(4):
        page = query(client, headers, "evidence/history", **request, before=before, limit=1).json()
        seen += page["items"]
        before = page["next_before"]
        if before is None:
            break
    assert [item["revision"] for item in seen] == [3, 2, 1]
    assert query(client, headers, "evidence/history", **request, before=1).json() == dict(
        items=[], next_before=None
    )
    with workspace.transaction(owner) as unit:
        CreditSourceTransaction(unit).map(data["source"], parents["empty"].id, expected_revision=3)
        CreditAccountTransaction(unit).archive(parents["active"].id, expected_revision=1)
    history = query(client, headers, "evidence/history", **request).json()["items"]
    assert history == [item | {"account_state": "archived"} for item in seen]
    exact = query(client, headers, "evidence/inspect", **body(data, kind, "evidence/inspect"))
    assert exact.json() == history[-1]
    if kind == "entry":
        assert (
            history[0]["values"]["treatment"] == "unsupported"
            and history[0]["values"]["original_amount"] is None
        )


@pytest.mark.parametrize("kind", KINDS)
def test_unknown_foreign_wrong_account_kind_root_and_revision_are_indistinguishable(
    environment, records, database, kind
):
    client, _, workspace, _, admin = environment
    owner, parents, data = records
    url, project = database
    provision_owner(url("bootstrap"), project, ISSUER, uuid4())
    foreign_owner = sql(admin, "SELECT id FROM app.owners WHERE id<>:owner", owner=owner)[0][0]
    foreign_parents = populate(workspace, foreign_owner)
    foreign = evidence(
        workspace, foreign_owner, foreign_parents["active"].id, foreign_parents["empty"].id
    )
    headers = login(client)
    for resource in RESOURCES:
        valid = body(data, kind, resource)
        changes = [
            {"account_id": str(uuid4())},
            {"account_id": str(foreign["account"])},
            {"account_id": str(parents["asset"].id)},
        ]
        if resource != "evidence/query":
            changes.extend(
                [
                    {"account_id": str(parents["empty"].id)},
                    {"id": str(uuid4())},
                    {"id": str(foreign["roots"][kind])},
                    {"kind": next(value for value in KINDS if value != kind)},
                ]
            )
        if resource == "evidence/inspect":
            changes.append({"at_revision": 4})
        for change in changes:
            result = query(client, headers, resource, **(valid | change))
            assert result.status_code == 404 and set(result.json()) == {"error", "request_id"}
            assert PRIVATE not in result.text and str(owner) not in result.text
    empty = query(client, headers, "evidence/query", account_id=str(parents["empty"].id), kind=kind)
    assert empty.json() == dict(items=[], next_after=None)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("resource", ["evidence/query", "evidence/history"])
def test_query_and_history_probe_101_rows_without_widening_storage_caps(
    environment, seeded, kind, resource
):
    client, _, workspace, _, _ = environment
    owner, parents = seeded
    with workspace.transaction(owner) as unit:
        sources = CreditSourceTransaction(unit)
        stream = sources.create()
        sources.map(stream.id, parents["active"].id, expected_revision=0)
        store = SERVICES[kind](unit)
        root = uuid4()
        expected = []
        for revision in range(101):
            identity = root if resource.endswith("history") else uuid4()
            payload = values(kind)
            role = {"statement": "total_due", "current": "outstanding", "entry": "billing_amount"}[
                kind
            ]
            payload[role] = cash(str(revision))
            store.record(
                identity,
                stream.id,
                1,
                native(kind, payload),
                expected_revision=revision if resource.endswith("history") else 0,
            )
            expected.append(str(identity))
    headers = login(client)
    limits = []

    def capture(connection, cursor, statement, parameters, context, many):
        if "LIMIT %(limit)s" in statement:
            limits.append(parameters["limit"])

    event.listen(workspace._engine, "before_cursor_execute", capture)
    request = dict(account_id=str(parents["active"].id), kind=kind, limit=100)
    history = resource.endswith("history")
    if history:
        request["id"] = str(root)
    try:
        first = query(client, headers, resource, **request)
        assert first.status_code == 200
        first = first.json()
        second = query(
            client,
            headers,
            resource,
            **request,
            **{"before" if history else "after": first["next_before" if history else "next_after"]},
        )
        assert second.status_code == 200
        second = second.json()
    finally:
        event.remove(workspace._engine, "before_cursor_execute", capture)
    assert limits == [101, 101] and len(first["items"]) == 100 and len(second["items"]) == 1
    assert second["next_before" if history else "next_after"] is None
    assert [item["revision" if history else "id"] for item in first["items"] + second["items"]] == (
        list(range(101, 0, -1)) if history else sorted(expected)
    )


@pytest.mark.parametrize("resource", RESOURCES)
@pytest.mark.parametrize(
    "failure,status,error",
    [
        (AuthenticationDenied, 401, "authentication_required"),
        (AuthenticationLimited, 429, "try_later"),
        (AuthenticationUnavailable, 503, "authentication_unavailable"),
        # Context is checked before this registry guard. Injecting it inside the
        # validator is an unknown internal fault and retains the auth-outage policy.
        (WorkspaceContextChanged, 503, "authentication_unavailable"),
    ],
)
def test_final_session_validator_keeps_authentication_status_and_withholds_financial_payload(
    environment, records, monkeypatch, resource, failure, status, error
):
    client, service, _, _, _ = environment
    _, _, data = records
    headers = login(client)
    cookie = client.cookies["trading_dev_session"]
    guard = service.store.workspace_guard
    calls = []

    @contextmanager
    def rejecting(key, owner):
        with guard(key, owner) as validate:

            def final():
                validate()
                calls.append(True)
                raise failure()

            yield final

    monkeypatch.setattr(service.store, "workspace_guard", rejecting)
    response = query(client, headers, resource, **body(data, "current", resource))
    assert calls == [True] and response.status_code == status and response.json()["error"] == error
    assert set(response.json()) == {"error", "request_id"} and PRIVATE not in response.text
    if status == 429:
        assert (
            client.cookies["trading_dev_session"] == cookie and "set-cookie" not in response.headers
        )
    else:
        assert "trading_dev_session" not in client.cookies


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "attack", ["missing_row", "wrong_cash", "cycle", "wrong_binding", "empty_history"]
)
def test_malformed_financial_projection_fails_privately_after_normal_auth_guard_exit(
    environment, records, monkeypatch, kind, attack, caplog, capsys
):
    client, service, _, _, _ = environment
    _, _, data = records
    headers = login(client)
    cookie = client.cookies["trading_dev_session"]
    guard = service.store.workspace_guard
    exits = []
    project = projections.project
    execute = READS._execute

    @contextmanager
    def observed(key, owner):
        with guard(key, owner) as validate:
            yield validate
        exits.append("normal")

    def malformed(row, **kwargs):
        if attack == "missing_row":
            row = dict(row)
            del row["kind"]
            return project(row, **kwargs)
        result = project(row, **kwargs)
        if attack == "wrong_binding":
            return result.model_copy(update={"account_id": str(uuid4())})
        payload = result.values.model_copy()
        role = {"statement": "total_due", "current": "outstanding", "entry": "billing_amount"}[kind]
        amount = getattr(payload, role).model_copy()
        amount.__dict__["source"] = amount if attack == "cycle" else {"private": PRIVATE}
        payload.__dict__[role] = amount
        return result.model_copy(update={"values": payload})

    def empty(reads, statement, **parameters):
        if "ORDER BY o.revision DESC" in statement:
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: []))
        return execute(reads, statement, **parameters)

    monkeypatch.setattr(service.store, "workspace_guard", observed)
    with monkeypatch.context() as patch:
        patch.setattr(READS, "_execute", empty) if attack == "empty_history" else patch.setattr(
            projections, "project", malformed
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            response = query(
                client, headers, "evidence/history", **body(data, kind, "evidence/history")
            )
    captured = capsys.readouterr()
    assert response.status_code == 503 and response.json()["error"] == "financial_data_unavailable"
    assert (
        exits == ["normal"]
        and not caught
        and PRIVATE not in response.text + caplog.text + captured.out + captured.err
    )
    assert client.cookies["trading_dev_session"] == cookie and "set-cookie" not in response.headers
    assert (
        query(
            client, headers, "evidence/history", **body(data, kind, "evidence/history")
        ).status_code
        == 200
    )


@pytest.mark.parametrize("resource", RESOURCES)
def test_all_financial_routes_require_active_auth_context_and_csrf_before_sql(
    environment, records, monkeypatch, resource
):
    client, _, _, _, _ = environment
    _, _, data = records
    headers = login(client)
    request = body(data, "entry", resource)
    path = "/api/v1/finance/credit/" + resource
    monkeypatch.setattr(
        READS, "_execute", lambda *args, **kwargs: pytest.fail("SQL reached before valid admission")
    )
    cookie = client.cookies["trading_dev_session"]
    stale = query(client, headers | {"X-Workspace-Context": "0" * 64}, resource, **request)
    assert stale.status_code == 412 and stale.json()["error"] == "workspace_context_changed"
    assert client.cookies["trading_dev_session"] == cookie and "set-cookie" not in stale.headers
    assert client.post(path, headers={"Origin": ORIGIN}, json=request).status_code == 403
    assert (
        client.post(
            path, headers=headers | {"Origin": "https://untrusted.invalid"}, json=request
        ).status_code
        == 403
    )
    assert (
        query(client, headers, resource, **(request | {"owner_id": str(uuid4())})).status_code
        == 422
    )
    client.cookies.delete("trading_dev_session")
    assert query(client, headers, resource, **request).status_code == 401


@pytest.mark.parametrize("change", ["deactivate", "correction"])
def test_evidence_read_rechecks_after_actual_owner_lock_wait(
    environment, records, database, monkeypatch, change
):
    client, _, workspace, _, admin = environment
    owner, parents, data = records
    url, project = database
    provision_owner(url("bootstrap"), project, ISSUER, uuid4())
    other = sql(admin, "SELECT id FROM app.owners WHERE id<>:owner", owner=owner)[0][0]
    foreign = populate(workspace, other)
    headers = login(client)
    pending = Queue()
    execute = CreditReadTransaction._execute

    def report(reads, statement, **parameters):
        if "pg_advisory_xact_lock" in statement and reads._unit._owner_id == owner:
            pending.put(
                reads._unit._connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
            )
        return execute(reads, statement, **parameters)

    monkeypatch.setattr(CreditReadTransaction, "_execute", report)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with admin.begin() as blocker:
            blocker_pid = blocker.execute(text("SELECT pg_backend_pid()")).scalar_one()
            blocker.execute(
                text(
                    "SELECT pg_advisory_xact_lock(hashtextextended("
                    "'credit-accounts/v1:' || CAST(:owner AS text),0))"
                ),
                dict(owner=owner),
            )
            future = pool.submit(
                query, client, headers, "evidence/query", **body(data, "current", "evidence/query")
            )
            pid = pending.get(timeout=5)
            deadline = monotonic() + 3
            while monotonic() < deadline:
                with admin.connect() as observer:
                    waiting = observer.execute(
                        text(
                            "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=:pid "
                            "AND locktype='advisory' AND NOT granted) "
                            "AND :blocker=ANY(pg_blocking_pids(:pid))"
                        ),
                        dict(pid=pid, blocker=blocker_pid),
                    ).scalar_one()
                if waiting:
                    break
                assert not future.done()
                sleep(0.01)
            else:
                pytest.fail("Evidence read did not reach expected owner wait")
            with workspace.transaction(other, read_only=True) as unit:
                reads = READS(unit)
                with reads.consistent():
                    assert (
                        reads.evidence_query(
                            CreditEvidenceQuery(
                                account_id=str(foreign["active"].id), kind="current"
                            )
                        ).items
                        == ()
                    )
            if change == "deactivate":
                blocker.execute(
                    text("UPDATE app.owners SET is_active=false WHERE id=:owner"), dict(owner=owner)
                )
            else:
                payload = values("current") | dict(outstanding=cash("42.00"))
                current_sql.pair(
                    blocker,
                    current_sql.parameters(
                        data["source"],
                        data["account"],
                        owner=owner,
                        root=data["roots"]["current"],
                        revision=4,
                        mapping=3,
                        values=native("current", payload),
                    ),
                )
        response = future.result(timeout=10)
    if change == "deactivate":
        assert response.status_code == 401 and "items" not in response.json()
    else:
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["revision"] == 4 and item["values"]["outstanding"]["source"] == "42.00"
        retained = query(
            client, headers, "evidence/inspect", **body(data, "current", "evidence/inspect")
        ).json()
        assert retained["revision"] == 1 and retained["values"] == data["values"]["current"][0]
