"""Authenticated, owner-scoped identity queries through real PostgreSQL and HTTP."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.testclient import TestClient

from database_tests.test_accounts import definition
from database_tests.test_instruments import security
from database_tests.test_preferences import ORIGIN, login, sql
from database_tests.test_preferences import environment as environment
from tests.auth_support import ISSUER, SUBJECT
from trading_api import financial_reads as api_reads
from trading_api.application import create_app
from trading_auth.browser import BrowserAuth
from trading_auth.session_models import verifier
from trading_db.account_keys import ReferenceKeys
from trading_db.accounts import AccountTransaction
from trading_db.enrollment import provision_owner
from trading_db.financial_reads import FinancialReadTransaction
from trading_db.instruments import InstrumentTransaction, SchemeDefinition
from trading_db.sessions import SessionDatabase
from trading_db.workspace import WorkspaceDatabase

PATH = "/api/v1/finance"
RESOURCES = ("accounts", "sources", "instruments", "positions")
PRIVATE_REFERENCE = "FAKE-PRIVATE-SOURCE-READ-001"


def query(client, headers, resource="accounts", **body):
    return client.post(f"{PATH}/{resource}/query", headers=headers, json=body)


def populate(workspace, owner):
    with workspace.transaction(owner) as unit:
        accounts = AccountTransaction(unit, ReferenceKeys({1: b"f" * 32}, 1))
        bank = accounts.create(definition())
        investment = accounts.create(definition("brokerage", "indmoney", "US", ("USD", "INR")))
        fund = accounts.create(definition("mutual_fund", "fund_registrar"))
        sources = []
        for namespace, target in (
            ("hdfc_statement", bank),
            ("indmoney_us", investment),
            ("cas", fund),
        ):
            source = accounts.source(namespace, PRIVATE_REFERENCE)
            accounts.map(source.id, target.id, expected_revision=0)
            sources.append(source)
        unlinked = accounts.source("advisor", PRIVATE_REFERENCE)
        accounts.map(unlinked.id, fund.id, expected_revision=0)
        accounts.map(unlinked.id, None, expected_revision=1)
        pristine = accounts.source("sbi_statement", PRIVATE_REFERENCE)
        identities = InstrumentTransaction(unit)
        equity = identities.create(security())
        scheme = identities.scheme(SchemeDefinition(name="Synthetic scheme"))
        variants = [
            identities.create(
                security(
                    index + 1,
                    "mutual_fund",
                    fund_scheme_id=scheme.id,
                    fund_plan=plan,
                    fund_option="growth",
                    fund_currency="INR",
                )
            )
            for index, plan in enumerate(("direct", "regular"))
        ]
        positions = [identities.position(investment.id, equity.id, "custody")]
        positions.extend(
            identities.position(fund.id, item.id, form)
            for item in variants
            for form in ("folio", "demat")
        )
        accounts.archive(investment.id, expected_revision=1)
    return dict(
        bank=bank,
        investment=investment,
        fund=fund,
        sources=sources,
        unlinked=unlinked,
        pristine=pristine,
        instruments=[equity, *variants],
        positions=positions,
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


def test_owned_allowlisted_pages_and_mapping_states(environment, seeded, caplog):
    client, _, workspace, _, admin = environment
    owner, data = seeded
    headers = login(client)
    lifetime = sql(admin, "SELECT idle_until, expires_at FROM app.auth_sessions")
    statements = []

    def capture(connection, cursor, statement, parameters, context, many):
        statements.append(statement.lower())

    event.listen(workspace._engine, "before_cursor_execute", capture)
    try:
        with caplog.at_level(logging.INFO):
            accounts = query(client, headers)
            sources = query(client, headers, "sources")
            instruments = query(client, headers, "instruments")
            positions = query(client, headers, "positions", account_id=str(data["investment"].id))
    finally:
        event.remove(workspace._engine, "before_cursor_execute", capture)
    for response in (accounts, sources, instruments, positions):
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert set(response.json()) == {"items", "next_after"}
        assert response.json()["next_after"] is None
        assert str(owner) not in response.text and PRIVATE_REFERENCE not in response.text
    owned = {item["id"]: item for item in accounts.json()["items"]}
    assert len(owned) == 3
    archived = owned[str(data["investment"].id)]
    assert archived["currencies"] == ["INR", "USD"] and archived["state"] == "archived"
    assert archived["revision"] == 2
    assert set(archived) == {
        "id",
        "kind",
        "institution",
        "market",
        "label",
        "currencies",
        "revision",
        "state",
    }
    mapped = {item["id"]: item for item in sources.json()["items"]}
    assert mapped[str(data["sources"][1].id)]["state"] == "archived"
    assert mapped[str(data["unlinked"].id)] == dict(
        id=str(data["unlinked"].id),
        namespace="advisor",
        mapping_revision=2,
        account_id=None,
        state="unmapped",
    )
    assert mapped[str(data["pristine"].id)]["mapping_revision"] is None
    assert {item["fund_plan"] for item in instruments.json()["items"]} == {
        None,
        "direct",
        "regular",
    }
    assert {item["holding_form"] for item in positions.json()["items"]} == {"custody"}
    assert all(item["account_state"] == "archived" for item in positions.json()["items"])
    assert sql(admin, "SELECT idle_until, expires_at FROM app.auth_sessions") == lifetime
    assert all(
        term not in statement
        for statement in statements
        for term in ("encrypted_reference", "fingerprint", "key_check", "select *")
    )
    assert PRIVATE_REFERENCE not in caplog.text and str(owner) not in caplog.text
    assert str(data["investment"].id) not in caplog.text and "Synthetic account" not in caplog.text


@pytest.mark.parametrize("resource", RESOURCES)
def test_keyset_pages_are_complete_and_do_not_duplicate(environment, seeded, resource):
    client, _, _, _, _ = environment
    _, data = seeded
    headers = login(client)
    body = {"account_id": str(data["fund"].id)} if resource == "positions" else {}
    whole = query(client, headers, resource, **body).json()["items"]
    expected = {
        "accounts": [data[key].id for key in ("bank", "investment", "fund")],
        "sources": [item.id for item in (*data["sources"], data["unlinked"], data["pristine"])],
        "instruments": [item.id for item in data["instruments"]],
        "positions": [item.id for item in data["positions"] if item.account_id == data["fund"].id],
    }[resource]
    assert {item["id"] for item in whole} == {str(item) for item in expected}
    seen, after = [], None
    for _ in range(len(whole) + 1):
        response = query(client, headers, resource, limit=1, after=after, **body)
        assert response.status_code == 200
        page = response.json()
        seen.extend(page["items"])
        after = page["next_after"]
        if after is None:
            break
    assert seen == whole and len({item["id"] for item in seen}) == len(whole)
    last = query(client, headers, resource, after=seen[-1]["id"], **body)
    assert last.json() == {"items": [], "next_after": None}


def test_foreign_owner_and_unknown_parent_have_identical_results(environment, seeded, database):
    client, _, workspace, _, admin = environment
    own, own_data = seeded
    url, project = database
    provision_owner(url("bootstrap"), project, ISSUER, uuid4())
    other = sql(admin, "SELECT id FROM app.owners WHERE id<>:owner", owner=own)[0][0]
    foreign = populate(workspace, other)
    headers = {**login(client), "X-Owner-ID": str(other)}
    assert {item["id"] for item in query(client, headers).json()["items"]} == {
        str(own_data[key].id) for key in ("bank", "investment", "fund")
    }
    for parent in (foreign["investment"].id, uuid4()):
        response = query(client, headers, "positions", account_id=str(parent))
        assert response.status_code == 404 and response.json()["error"] == "not_found"
        assert set(response.json()) == {"error", "request_id"}
    for resource in ("sources", "instruments"):
        assert str(foreign[resource][0].id) not in query(client, headers, resource).text
    assert query(client, headers, "positions", account_id=str(own_data["bank"].id)).json() == {
        "items": [],
        "next_after": None,
    }
    with workspace._engine.connect() as connection:
        assert connection.execute(
            text("SELECT current_setting('app.owner_id',true)")
        ).scalar_one() in (None, "")
        assert (
            connection.execute(text("SELECT count(*) FROM app.financial_accounts")).scalar_one()
            == 0
        )


@pytest.mark.parametrize(
    "state", ["anonymous", "pending", "recovery", "expired", "disabled", "revoked", "provider"]
)
def test_only_active_mfa_sessions_reach_financial_reads(environment, monkeypatch, state):
    client, service, _, stub, admin = environment
    headers = login(client, mfa=state != "pending")
    called = []
    monkeypatch.setattr(FinancialReadTransaction, "accounts", lambda *args: called.append(True))
    if state == "anonymous":
        client.cookies.delete("trading_dev_session")
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
        FinancialReadTransaction,
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
    original = FinancialReadTransaction.accounts

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

    monkeypatch.setattr(FinancialReadTransaction, "accounts", failing)
    response = query(client, headers)
    assert response.status_code == (503 if failure == "sql" else 401)
    assert set(response.json()) == {"error", "request_id"}
    assert "Synthetic" not in response.text and "private" not in response.text
    if failure == "sql":
        assert response.json()["error"] == "financial_data_unavailable"
        assert client.cookies["trading_dev_session"] == cookie
        assert "set-cookie" not in response.headers
        monkeypatch.setattr(FinancialReadTransaction, "accounts", original)
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
    original = FinancialReadTransaction.accounts

    def paused(reads, body):
        result = original(reads, body)
        entered.set()
        assert release.wait(10)
        return result

    def revoke():
        revoking.set()
        service.store.revoke(key, "a" * 32)

    monkeypatch.setattr(FinancialReadTransaction, "accounts", paused)
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


def test_http_schema_boundary_and_read_only_methods(environment, seeded):
    client, _, _, _, _ = environment
    _, data = seeded
    headers = login(client)
    for resource in RESOURCES:
        body = {"account_id": str(data["bank"].id)} if resource == "positions" else {}
        path = f"{PATH}/{resource}/query"
        for extra in (
            {"limit": True},
            {"limit": "1"},
            {"limit": 101},
            {"limit": 1.5},
            {"after": "invalid"},
            {"owner_id": str(uuid4())},
            {"amount": "100.00"},
        ):
            response = client.post(path, headers=headers, json={**body, **extra})
            assert response.status_code == 422 and set(response.json()) == {"error", "request_id"}
        assert client.post(path, headers={"Origin": ORIGIN}, json=body).status_code == 403
        assert client.post(path + "?limit=1", headers=headers, json=body).status_code == 403
        assert (
            client.post(
                path, headers={**headers, "Origin": "https://untrusted.invalid"}, json=body
            ).status_code
            == 403
        )
        assert client.get(path, headers=headers).status_code == 405
        assert client.put(path, headers=headers, json=body).status_code == 405
        assert client.delete(path, headers=headers).status_code == 415
    assert query(client, headers, "positions").status_code == 422
    with TestClient(create_app(), base_url=ORIGIN) as locked:
        assert query(locked, {}, "accounts").status_code == 404


def test_maximum_page_uses_bounded_sql_and_explicit_continuation(environment):
    client, _, workspace, _, admin = environment
    owner = sql(admin, "SELECT id FROM app.owners")[0][0]
    with workspace.transaction(owner) as unit:
        accounts = AccountTransaction(unit, None)
        created = [accounts.create(definition()) for _ in range(101)]
    headers = login(client)
    observed_limits = []

    def capture(connection, cursor, statement, parameters, context, many):
        if "AS currencies" in statement:
            observed_limits.append(parameters["limit"])

    event.listen(workspace._engine, "before_cursor_execute", capture)
    try:
        first = query(client, headers, limit=100).json()
        second = query(client, headers, limit=100, after=first["next_after"]).json()
    finally:
        event.remove(workspace._engine, "before_cursor_execute", capture)
    assert observed_limits == [101, 101]
    assert len(first["items"]) == 100 and first["next_after"] == first["items"][-1]["id"]
    assert len(second["items"]) == 1 and second["next_after"] is None
    assert {item["id"] for item in first["items"] + second["items"]} == {
        str(item.id) for item in created
    }


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


def test_database_read_only_mode_blocks_accidental_mutation_and_resets_pool(
    environment, monkeypatch
):
    client, _, workspace, _, admin = environment
    headers = login(client)
    modes = []

    def accidental_write(reads, body):
        modes.append(reads._execute("SELECT current_setting('transaction_read_only')").scalar_one())
        reads._accounts.create(definition())

    with monkeypatch.context() as patch:
        patch.setattr(FinancialReadTransaction, "accounts", accidental_write)
        response = query(client, headers)
    assert modes == ["on"]
    assert response.status_code == 503 and response.json()["error"] == "financial_data_unavailable"
    assert "set-cookie" not in response.headers
    assert sql(admin, "SELECT count(*) FROM app.financial_accounts")[0][0] == 0
    assert query(client, headers).json() == {"items": [], "next_after": None}
    owner = sql(admin, "SELECT id FROM app.owners")[0][0]
    with workspace.transaction(owner) as unit:
        assert AccountTransaction(unit, None).create(definition())
