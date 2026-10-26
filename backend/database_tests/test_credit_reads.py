"""Real session, PostgreSQL, privacy and concurrency checks for four credit reads."""

import logging
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from queue import Queue
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from starlette.testclient import TestClient

from database_tests.test_accounts import definition
from database_tests.test_preferences import ORIGIN, login, sql
from database_tests.test_preferences import environment as environment
from tests.auth_support import ISSUER, SUBJECT
from tests.test_credit_read_contracts import MARKER
from trading_api import credit_reads as api_reads
from trading_api.application import create_app
from trading_api.credit_read_contracts import CreditAccountView, CreditPage
from trading_api.read_contracts import PageQuery
from trading_auth.browser import BrowserAuth
from trading_auth.models import (
    AuthenticationDenied,
    AuthenticationLimited,
    AuthenticationUnavailable,
)
from trading_auth.session_models import verifier
from trading_db.accounts import AccountTransaction
from trading_db.credit_accounts import CreditAccountDefinition, CreditAccountTransaction
from trading_db.credit_reads import CreditReadTransaction
from trading_db.credit_sources import CreditSourceTransaction
from trading_db.enrollment import provision_owner
from trading_db.sessions import SessionDatabase
from trading_db.workspace import WorkspaceDatabase

PATH = "/api/v1/finance/credit"
RESOURCES = ("accounts/query", "accounts/inspect", "sources/query", "sources/mappings/history")
TABLES = (
    "credit_billing_accounts",
    "credit_source_handles",
    "credit_source_account_mappings",
    "credit_evidence_observations",
    "credit_statement_values",
    "credit_current_values",
    "credit_entry_values",
    "financial_events",
    "cash_movements",
)


def query(client, headers, resource="accounts/query", **body):
    return client.post(f"{PATH}/{resource}", headers=headers, json=body)


def populate(workspace, owner):
    with workspace.transaction(owner) as unit:
        accounts = CreditAccountTransaction(unit)
        active, archived, empty = [
            accounts.create(CreditAccountDefinition(label=MARKER)) for _ in range(3)
        ]
        sources = CreditSourceTransaction(unit)
        pristine, linked, old, unlinked, changed = [sources.create() for _ in range(5)]
        sources.map(linked.id, active.id, expected_revision=0)
        sources.map(old.id, archived.id, expected_revision=0)
        sources.map(unlinked.id, active.id, expected_revision=0)
        sources.map(unlinked.id, None, expected_revision=1)
        sources.map(changed.id, archived.id, expected_revision=0)
        sources.map(changed.id, active.id, expected_revision=1)
        sources.map(changed.id, None, expected_revision=2)
        sources.map(changed.id, active.id, expected_revision=3)
        accounts.archive(archived.id, expected_revision=1)
        asset = AccountTransaction(unit, None).create(definition())
    return dict(
        active=active,
        archived=archived,
        empty=empty,
        pristine=pristine,
        linked=linked,
        old=old,
        unlinked=unlinked,
        changed=changed,
        asset=asset,
    )


@pytest.fixture
def seeded(environment):
    _, _, workspace, _, admin = environment
    owner = sql(
        admin,
        "SELECT owner_id FROM app.owner_identities WHERE subject=:subject",
        subject=str(SUBJECT),
    )[0][0]
    return owner, populate(workspace, owner)


def snapshot(admin):
    return {
        table: sql(admin, f"SELECT to_jsonb(t)::text FROM app.{table} t ORDER BY 1")
        for table in TABLES
    }


def test_minimal_owned_views_and_immutable_provenance(environment, seeded, caplog):
    client, _, workspace, _, admin = environment
    owner, data = seeded
    headers = login(client)
    before = snapshot(admin)
    lifetime = sql(admin, "SELECT idle_until,expires_at FROM app.auth_sessions")
    observed = []

    def capture(connection, cursor, statement, parameters, context, many):
        observed.append(statement.lower())

    event.listen(workspace._engine, "before_cursor_execute", capture)
    try:
        with caplog.at_level(logging.INFO):
            accounts = query(client, headers)
            inspected = query(client, headers, "accounts/inspect", id=str(data["archived"].id))
            sources = query(client, headers, "sources/query")
            history = query(client, headers, "sources/mappings/history", id=str(data["changed"].id))
    finally:
        event.remove(workspace._engine, "before_cursor_execute", capture)
    for response in (accounts, inspected, sources, history):
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert str(owner) not in response.text
    assert len(accounts.json()["items"]) == 3 and accounts.json()["next_after"] is None
    assert inspected.json() == dict(
        id=str(data["archived"].id),
        issuer="hdfc",
        billing_currency="INR",
        label=MARKER,
        revision=2,
        state="archived",
    )
    assert all(
        set(item) == {"id", "issuer", "billing_currency", "label", "revision", "state"}
        for item in accounts.json()["items"]
    )
    mapped = {item["id"]: item for item in sources.json()["items"]}
    assert mapped[str(data["pristine"].id)] == dict(
        id=str(data["pristine"].id),
        family="hdfc_credit_statement",
        mapping_revision=None,
        account_id=None,
        state="unmapped",
    )
    assert mapped[str(data["unlinked"].id)]["mapping_revision"] == 2
    assert mapped[str(data["unlinked"].id)]["account_id"] is None
    assert mapped[str(data["old"].id)]["state"] == "archived"
    assert mapped[str(data["old"].id)]["account_id"] == str(data["archived"].id)
    rows = history.json()["items"]
    assert [row["revision"] for row in rows] == [4, 3, 2, 1]
    assert [row["previous_revision"] for row in rows] == [3, 2, 1, None]
    assert [row["reason"] for row in rows] == ["correction", "unlinked", "correction", "initial"]
    assert [row["account_state"] for row in rows] == ["active", None, "active", "archived"]
    assert [row["is_latest_revision"] for row in rows] == [True, False, False, False]
    assert all(row["source_id"] == str(data["changed"].id) for row in rows)
    assert history.json()["next_before"] is None
    assert (
        before == snapshot(admin)
        and sql(admin, "SELECT idle_until,expires_at FROM app.auth_sessions") == lifetime
    )
    for statement in observed:
        assert "select *" not in statement
        assert all(
            name not in statement
            for name in (
                "credit_statement_values",
                "credit_current_values",
                "credit_entry_values",
                "encrypted_reference",
            )
        )
    assert MARKER not in caplog.text and str(owner) not in caplog.text


@pytest.mark.parametrize(
    "resource", ["accounts/query", "sources/query", "sources/mappings/history"]
)
def test_exact_keyset_and_revision_pagination(environment, seeded, resource):
    client, _, _, _, _ = environment
    _, data = seeded
    headers = login(client)
    history = resource.endswith("history")
    base = {"id": str(data["changed"].id)} if history else {}
    whole = query(client, headers, resource, **base).json()["items"]
    cursor = None
    seen = []
    for _ in range(len(whole) + 1):
        body = base | {("before" if history else "after"): cursor, "limit": 1}
        response = query(client, headers, resource, **body)
        assert response.status_code == 200
        page = response.json()
        seen.extend(page["items"])
        cursor = page["next_before" if history else "next_after"]
        if cursor is None:
            break
    assert seen == whole
    final = query(
        client,
        headers,
        resource,
        **(base | {("before" if history else "after"): whole[-1]["revision" if history else "id"]}),
    )
    assert final.json() == dict(items=[], **{("next_before" if history else "next_after"): None})


def test_unknown_foreign_and_asset_parents_do_not_reveal_other_identity_spaces(
    environment, seeded, database
):
    client, _, workspace, _, admin = environment
    own, data = seeded
    url, project = database
    provision_owner(url("bootstrap"), project, ISSUER, uuid4())
    other = sql(admin, "SELECT id FROM app.owners WHERE id<>:owner", owner=own)[0][0]
    foreign = populate(workspace, other)
    headers = login(client) | {"X-Owner-ID": str(other)}
    for resource, ids in (
        ("accounts/inspect", (foreign["active"].id, data["asset"].id, uuid4())),
        ("sources/mappings/history", (foreign["changed"].id, data["active"].id, uuid4())),
    ):
        for root in ids:
            response = query(client, headers, resource, id=str(root))
            assert response.status_code == 404 and response.json()["error"] == "not_found"
            assert set(response.json()) == {"error", "request_id"}
    assert query(
        client, headers, "sources/mappings/history", id=str(data["pristine"].id)
    ).json() == dict(items=[], next_before=None)
    for resource in ("accounts/query", "sources/query"):
        result = query(client, headers, resource)
        assert (
            str(foreign["active"].id) not in result.text
            and str(foreign["changed"].id) not in result.text
        )
    with workspace.transaction(own, read_only=True) as unit:
        for table in TABLES[:3]:
            assert set(
                unit._connection.execute(text(f"SELECT owner_id FROM app.{table}")).scalars()
            ) == {own}
    with workspace._engine.connect() as connection:
        assert connection.execute(
            text("SELECT current_setting('app.owner_id',true)")
        ).scalar_one() in (None, "")
        assert (
            connection.execute(
                text("SELECT count(*) FROM app.credit_billing_accounts")
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize(
    "state",
    [
        "anonymous",
        "pending",
        "factor",
        "password",
        "recovery",
        "expired",
        "disabled",
        "revoked",
        "provider",
    ],
)
def test_only_active_mfa_sessions_reach_financial_reads(environment, monkeypatch, state):
    client, service, _, stub, admin = environment
    headers = login(client, mfa=state != "pending")
    called = []
    monkeypatch.setattr(CreditReadTransaction, "accounts", lambda *args: called.append(True))
    if state == "anonymous":
        client.cookies.delete("trading_dev_session")
    elif state in {"factor", "password"}:
        sql(admin, "UPDATE app.auth_sessions SET stage=:stage", stage=state)
    elif state == "recovery":
        assert (
            client.post(
                "/api/v1/auth/recovery/verify",
                headers=headers,
                json=dict(email="fixture@example.invalid", code="654321"),
            ).status_code
            == 200
        )
    elif state == "expired":
        sql(admin, "UPDATE app.auth_sessions SET idle_until=clock_timestamp()-interval '1 second'")
    elif state == "disabled":
        sql(admin, "UPDATE app.owners SET is_active=false")
    elif state == "revoked":
        service.store.revoke(verifier(client.cookies["trading_dev_session"]), "a" * 32)
    elif state == "provider":
        stub.fail_refresh = True
    response = query(client, headers)
    assert response.status_code == (503 if state == "provider" else 401)
    assert not called


def test_revoke_between_refresh_and_guard_prevents_query(environment, monkeypatch):
    client, service, _, _, _ = environment
    headers = login(client)
    original = service.store.workspace_guard

    @contextmanager
    def revoked(key, owner):
        service.store.revoke(key, "a" * 32)
        with original(key, owner) as validate:
            yield validate

    monkeypatch.setattr(service.store, "workspace_guard", revoked)
    monkeypatch.setattr(
        CreditReadTransaction,
        "accounts",
        lambda *args: pytest.fail("Query admitted after revocation"),
    )
    assert query(client, headers).status_code == 401


@pytest.mark.parametrize("failure", ["disabled", "expired", "sql"])
def test_failure_after_query_never_discloses_data_and_resets_context(
    environment, seeded, monkeypatch, failure
):
    client, _, workspace, _, admin = environment
    headers = login(client)
    cookie = client.cookies["trading_dev_session"]
    original = CreditReadTransaction.accounts

    def failing(reads, body):
        result = original(reads, body)
        if failure == "sql":
            raise SQLAlchemyError("synthetic-private-diagnostic")
        if failure == "disabled":
            sql(admin, "UPDATE app.owners SET is_active=false")
        else:
            sql(
                admin,
                "UPDATE app.auth_sessions SET idle_until=clock_timestamp()-interval '1 second'",
            )
        return result

    monkeypatch.setattr(CreditReadTransaction, "accounts", failing)
    response = query(client, headers)
    assert response.status_code == (503 if failure == "sql" else 401)
    assert set(response.json()) == {"error", "request_id"}
    assert "Synthetic" not in response.text and "private" not in response.text
    if failure == "sql":
        assert response.json()["error"] == "financial_data_unavailable"
        assert client.cookies["trading_dev_session"] == cookie
        assert "set-cookie" not in response.headers
        monkeypatch.setattr(CreditReadTransaction, "accounts", original)
        assert query(client, headers).status_code == 200
    with workspace._engine.connect() as connection:
        assert connection.execute(
            text("SELECT current_setting('app.owner_id',true)")
        ).scalar_one() in (None, "")


def test_logout_serializes_after_admitted_read_and_blocks_next(environment, seeded, monkeypatch):
    client, service, _, _, _ = environment
    headers = login(client)
    key = verifier(client.cookies["trading_dev_session"])
    entered, release, revoking = threading.Event(), threading.Event(), threading.Event()
    original = CreditReadTransaction.accounts

    def paused(reads, body):
        result = original(reads, body)
        entered.set()
        assert release.wait(10)
        return result

    def revoke():
        revoking.set()
        service.store.revoke(key, "a" * 32)

    monkeypatch.setattr(CreditReadTransaction, "accounts", paused)
    with ThreadPoolExecutor(max_workers=2) as executor:
        reading = executor.submit(query, client, headers)
        assert entered.wait(5)
        revocation = executor.submit(revoke)
        try:
            assert revoking.wait(5) and not revocation.done()
        finally:
            release.set()
        assert reading.result().status_code == 200
        revocation.result()
    assert query(client, headers).status_code == 401


def test_reads_survive_application_restart(environment, seeded, database):
    client, service, _, stub, _ = environment
    headers = login(client)
    before = query(client, headers).json()
    url, project = database
    restarted = BrowserAuth(stub.provider(), SessionDatabase(url("auth"), project), service.vault)
    store = WorkspaceDatabase(url("runtime"), project)
    with TestClient(create_app(browser=restarted, workspace=store), base_url=ORIGIN) as other:
        other.cookies.update(client.cookies)
        assert query(other, headers).json() == before


def test_response_size_failure_is_not_a_truncated_success_or_logout(
    environment, seeded, monkeypatch
):
    client, _, _, _, _ = environment
    headers = login(client)
    with monkeypatch.context() as patch:
        patch.setattr(api_reads, "MAX_RESPONSE_BYTES", 1)
        response = query(client, headers)
    assert response.status_code == 503 and response.json()["error"] == "financial_data_unavailable"
    assert "items" not in response.json() and "set-cookie" not in response.headers
    assert query(client, headers).status_code == 200


@pytest.mark.parametrize("resource", RESOURCES)
def test_each_http_route_requires_body_and_current_workspace_context(
    environment, seeded, monkeypatch, resource
):
    client, _, _, _, _ = environment
    _, data = seeded
    headers = login(client)
    body = (
        {"id": str(data["active" if resource == "accounts/inspect" else "changed"].id)}
        if resource.endswith(("inspect", "history"))
        else {}
    )
    path = f"{PATH}/{resource}"
    for extra in ({"owner_id": str(uuid4())}, {"amount": "123.45"}, {"last_four": "1234"}):
        response = client.post(path, headers=headers, json=body | extra)
        assert response.status_code == 422 and set(response.json()) == {"error", "request_id"}
    for method in ("get", "put"):
        assert (
            getattr(client, method)(
                path, headers=headers, **({"json": body} if method == "put" else {})
            ).status_code
            == 405
        )
    assert client.post(path, headers={"Origin": ORIGIN}, json=body).status_code == 403
    assert client.post(path + "?id=private", headers=headers, json=body).status_code == 403
    assert (
        client.post(
            path, headers=headers | {"Origin": "https://untrusted.invalid"}, json=body
        ).status_code
        == 403
    )
    called = []
    monkeypatch.setattr(CreditReadTransaction, "_execute", lambda *args, **kw: called.append(True))
    cookie = client.cookies["trading_dev_session"]
    response = client.post(path, headers=headers | {"X-Workspace-Context": "0" * 64}, json=body)
    assert response.status_code == 412 and response.json()["error"] == "workspace_context_changed"
    assert (
        not called
        and client.cookies["trading_dev_session"] == cookie
        and "set-cookie" not in response.headers
    )


def test_read_uses_active_mfa_without_an_extra_freshness_challenge(
    environment, seeded, monkeypatch
):
    client, service, _, stub, _ = environment
    headers = login(client)
    monkeypatch.setattr(
        service, "_fresh", lambda *args: pytest.fail("Read requested unrelated fresh-MFA challenge")
    )
    assert query(client, headers).status_code == 200
    called = []
    monkeypatch.setattr(CreditReadTransaction, "accounts", lambda *args: called.append(True))
    stub.factors = []
    assert query(client, headers).status_code == 401 and not called


@pytest.mark.parametrize(
    "failure,expected,error",
    [
        (AuthenticationDenied, 401, "authentication_required"),
        (AuthenticationLimited, 429, "try_later"),
        (AuthenticationUnavailable, 503, "authentication_unavailable"),
    ],
)
def test_final_validator_authentication_denial_keeps_auth_status(
    environment, seeded, monkeypatch, failure, expected, error
):
    client, service, _, _, _ = environment
    headers = login(client)
    cookie = client.cookies["trading_dev_session"]
    original = service.store.workspace_guard
    calls = []

    @contextmanager
    def rejecting(key, owner):
        with original(key, owner) as validate:

            def final():
                validate()
                calls.append("final")
                raise failure()

            yield final

    monkeypatch.setattr(service.store, "workspace_guard", rejecting)
    response = query(client, headers)
    assert calls == ["final"] and response.status_code == expected
    assert response.json()["error"] == error and set(response.json()) == {"error", "request_id"}
    assert MARKER not in response.text
    if expected == 429:
        assert response.headers["retry-after"] == "5"
        assert (
            client.cookies["trading_dev_session"] == cookie and "set-cookie" not in response.headers
        )
    else:
        assert "trading_dev_session" not in client.cookies


@pytest.mark.parametrize(
    "attack", ["construct", "copy", "extra", "nested", "missing", "oversized", "cycle"]
)
def test_counterfeit_response_fails_privately_after_normal_auth_guard_exit(
    environment, seeded, monkeypatch, caplog, capsys, attack
):
    client, service, _, _, _ = environment
    headers = login(client)
    cookie = client.cookies["trading_dev_session"]
    original = CreditReadTransaction.accounts
    guard = service.store.workspace_guard
    exits = []

    @contextmanager
    def observed(key, owner):
        with guard(key, owner) as validate:
            yield validate
        exits.append("normal")

    def malformed(reads, body):
        value = original(reads, body)
        item = value.items[0]
        if attack == "construct":
            item = CreditAccountView.model_construct(
                **(item.model_dump() | {"label": {"secret": MARKER}})
            )
        elif attack == "copy":
            item = item.model_copy(update={"label": 123})
        elif attack == "extra":
            item = item.model_copy(update={"private": MARKER})
        elif attack == "missing":
            item = item.model_copy()
            del item.__dict__["label"]
        elif attack == "cycle":
            item = item.model_copy()
            item.__dict__["label"] = item
        elif attack == "nested":
            return value.model_copy(update={"items": (item.model_copy(update={"issuer": MARKER}),)})
        else:
            return CreditPage[CreditAccountView].model_construct(
                items=(item,) * 101, next_after=None
            )
        return CreditPage[CreditAccountView].model_construct(items=(item,), next_after=None)

    monkeypatch.setattr(service.store, "workspace_guard", observed)
    with monkeypatch.context() as patch:
        patch.setattr(CreditReadTransaction, "accounts", malformed)
        with warnings.catch_warnings(record=True) as caught, caplog.at_level(logging.INFO):
            warnings.simplefilter("always")
            response = query(client, headers)
    output = capsys.readouterr()
    assert response.status_code == 503 and response.json()["error"] == "financial_data_unavailable"
    assert exits == ["normal"] and not caught
    assert MARKER not in response.text + caplog.text + output.out + output.err
    assert "set-cookie" not in response.headers and client.cookies["trading_dev_session"] == cookie
    assert query(client, headers).status_code == 200


@pytest.mark.parametrize(
    "resource", ["accounts/query", "sources/query", "sources/mappings/history"]
)
def test_maximum_pages_probe_101_without_widening_service_caps(environment, resource):
    client, _, workspace, _, admin = environment
    owner = sql(admin, "SELECT id FROM app.owners")[0][0]
    with workspace.transaction(owner) as unit:
        accounts = CreditAccountTransaction(unit)
        sources = CreditSourceTransaction(unit)
        if resource == "accounts/query":
            expected = [
                str(accounts.create(CreditAccountDefinition(label=MARKER)).id) for _ in range(101)
            ]
            body = {}
        elif resource == "sources/query":
            expected = [str(sources.create().id) for _ in range(101)]
            body = {}
        else:
            targets = [accounts.create(CreditAccountDefinition(label=MARKER)).id for _ in range(2)]
            source = sources.create()
            for revision in range(101):
                sources.map(source.id, targets[revision % 2], expected_revision=revision)
            expected = list(range(101, 0, -1))
            body = {"id": str(source.id)}
    headers = login(client)
    limits = []

    def capture(connection, cursor, statement, parameters, context, many):
        if "LIMIT %(limit)s" in statement:
            limits.append(parameters["limit"])

    event.listen(workspace._engine, "before_cursor_execute", capture)
    try:
        first = query(client, headers, resource, limit=100, **body).json()
        history = resource.endswith("history")
        cursor = first["next_before" if history else "next_after"]
        second = query(
            client,
            headers,
            resource,
            limit=100,
            **(body | {("before" if history else "after"): cursor}),
        ).json()
    finally:
        event.remove(workspace._engine, "before_cursor_execute", capture)
    assert limits == [101, 101]
    assert len(first["items"]) == 100 and len(second["items"]) == 1
    assert second["next_before" if history else "next_after"] is None
    assert [row["revision" if history else "id"] for row in first["items"] + second["items"]] == (
        expected if history else sorted(expected)
    )


def test_injected_write_is_read_only_failure_and_pool_state_resets(
    environment, seeded, monkeypatch
):
    client, _, workspace, _, admin = environment
    owner, _ = seeded
    headers = login(client)
    before = snapshot(admin)
    modes = []
    states = []

    def write(reads, body):
        modes.append(reads._execute("SELECT current_setting('transaction_read_only')").scalar_one())
        try:
            reads._execute(
                "UPDATE app.credit_billing_accounts SET label=label WHERE owner_id=:owner"
            )
        except DBAPIError as error:
            states.append(error.orig.sqlstate)
            raise

    with monkeypatch.context() as patch:
        patch.setattr(CreditReadTransaction, "accounts", write)
        response = query(client, headers)
    assert response.status_code == 503 and response.json()["error"] == "financial_data_unavailable"
    assert modes == ["on"] and states == ["25006"] and before == snapshot(admin)
    assert "set-cookie" not in response.headers and query(client, headers).status_code == 200
    with workspace.transaction(owner) as unit:
        assert (
            unit._connection.execute(
                text("SELECT current_setting('transaction_read_only')")
            ).scalar_one()
            == "off"
        )
        CreditAccountTransaction(unit).create(CreditAccountDefinition(label=MARKER))
    with workspace._engine.connect() as connection:
        assert connection.execute(
            text("SELECT current_setting('app.owner_id',true)")
        ).scalar_one() in (None, "")


@pytest.mark.parametrize("change", ["deactivate", "remap"])
def test_read_rechecks_owner_and_mapping_after_observed_credit_lock_wait(
    environment, seeded, database, monkeypatch, change
):
    client, _, workspace, _, admin = environment
    own, data = seeded
    url, project = database
    provision_owner(url("bootstrap"), project, ISSUER, uuid4())
    other = sql(admin, "SELECT id FROM app.owners WHERE id<>:owner", owner=own)[0][0]
    foreign = populate(workspace, other)
    headers = login(client)
    pending = Queue()
    original = CreditReadTransaction._execute

    def report(reads, statement, **parameters):
        if "pg_advisory_xact_lock" in statement and reads._unit._owner_id == own:
            pending.put(
                reads._unit._connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
            )
        return original(reads, statement, **parameters)

    monkeypatch.setattr(CreditReadTransaction, "_execute", report)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with admin.begin() as blocker:
            blocker_pid = blocker.execute(text("SELECT pg_backend_pid()")).scalar_one()
            blocker.execute(
                text(
                    "SELECT pg_advisory_xact_lock(hashtextextended("
                    "'credit-accounts/v1:' || CAST(:owner AS text),0))"
                ),
                dict(owner=own),
            )
            future = pool.submit(query, client, headers, "sources/query")
            pid = pending.get(timeout=5)
            deadline = monotonic() + 3
            while monotonic() < deadline:
                with admin.connect() as observer:
                    waiting = observer.execute(
                        text(
                            "SELECT EXISTS(SELECT 1 FROM pg_locks "
                            "WHERE pid=:pid AND locktype='advisory' AND NOT granted) "
                            "AND :blocker=ANY(pg_blocking_pids(:pid))"
                        ),
                        dict(pid=pid, blocker=blocker_pid),
                    ).scalar_one()
                if waiting:
                    break
                assert not future.done()
                sleep(0.01)
            else:
                pytest.fail("Read did not reach the expected owner advisory wait")
            with workspace.transaction(other, read_only=True) as unit:
                reads = CreditReadTransaction(unit)
                with reads.consistent():
                    assert str(foreign["active"].id) in {
                        item.id for item in reads.accounts(PageQuery()).items
                    }
            if change == "deactivate":
                blocker.execute(
                    text("UPDATE app.owners SET is_active=false WHERE id=:owner"), dict(owner=own)
                )
            else:
                blocker.execute(
                    text(
                        "INSERT INTO app.credit_source_account_mappings "
                        "(owner_id,source_id,revision,previous_revision,account_id,reason) "
                        "VALUES(:owner,:source,2,1,:account,'correction')"
                    ),
                    dict(owner=own, source=data["linked"].id, account=data["empty"].id),
                )
        result = future.result(timeout=10)
    if change == "deactivate":
        assert result.status_code == 401 and "items" not in result.json()
    else:
        assert result.status_code == 200
        mapped = next(
            item for item in result.json()["items"] if item["id"] == str(data["linked"].id)
        )
        assert mapped["account_id"] == str(data["empty"].id) and mapped["mapping_revision"] == 2
        history = query(
            client, headers, "sources/mappings/history", id=str(data["linked"].id)
        ).json()["items"]
        assert [item["account_id"] for item in history] == [
            str(data["empty"].id),
            str(data["active"].id),
        ]
    assert (
        sql(
            admin,
            "SELECT count(*) FROM app.credit_billing_accounts WHERE owner_id=:owner",
            owner=own,
        )[0][0]
        == 3
    )


def test_account_lifecycle_is_observed_now_without_changing_mapping_history(environment, seeded):
    client, _, workspace, _, _ = environment
    owner, data = seeded
    headers = login(client)
    first = query(client, headers, "sources/mappings/history", id=str(data["linked"].id)).json()[
        "items"
    ][0]
    with workspace.transaction(owner) as unit:
        CreditAccountTransaction(unit).archive(data["active"].id, expected_revision=1)
    latest = query(client, headers, "sources/mappings/history", id=str(data["linked"].id)).json()[
        "items"
    ][0]
    assert first["account_state"] == "active" and latest == first | {"account_state": "archived"}
    assert (
        query(client, headers, "accounts/inspect", id=str(data["active"].id)).json()["state"]
        == "archived"
    )


def test_no_credit_mutation_routes_are_mounted(environment, seeded):
    client, _, _, _, _ = environment
    headers = login(client)
    for path in (
        "accounts/create",
        "accounts/archive",
        "sources/create",
        "sources/map",
    ):
        assert query(client, headers, path).status_code == 404
    with TestClient(create_app(), base_url=ORIGIN) as locked:
        for path in RESOURCES:
            assert query(locked, {}, path).status_code == 404
