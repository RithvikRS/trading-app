"""Authenticated preferences against real PostgreSQL and synthetic provider HTTP."""

import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from starlette.testclient import TestClient

from tests.auth_support import FACTOR, ISSUER, PASSWORD, SUBJECT
from tests.browser_support import BrowserProviderStub
from trading_api.application import create_app
from trading_auth.browser import BrowserAuth
from trading_auth.session_models import Vault, verifier
from trading_db import migrate
from trading_db.connections import engine_for
from trading_db.enrollment import provision_owner
from trading_db.sessions import SessionDatabase
from trading_db.workspace import PreferenceUpdate, WorkspaceDatabase, WorkspaceTransaction

PATH = "/api/v1/preferences"
DEFAULT = dict(theme="light", display_currency="INR", amount_masked=True, revision=0)
UPDATE = dict(theme="dark", display_currency="USD", amount_masked=False, revision=0)
ORIGIN = "http://127.0.0.1:8000"


@pytest.fixture
def environment(database):
    url, project = database
    migrate.apply(url(), project)
    provision_owner(url("bootstrap"), project, ISSUER, SUBJECT)
    stub = BrowserProviderStub()
    service = BrowserAuth(
        stub.provider(),
        SessionDatabase(url("auth"), project),
        Vault(secrets.token_bytes(32)),
        recovery_email=True,
    )
    workspace = WorkspaceDatabase(url("runtime"), project)
    admin = engine_for(url("bootstrap"), migration=True)
    with TestClient(create_app(browser=service, workspace=workspace), base_url=ORIGIN) as client:
        try:
            yield client, service, workspace, stub, admin
        finally:
            admin.dispose()


def login(client, *, mfa=True):
    assert client.get("/api/v1/auth/bootstrap").status_code == 200
    headers = {"Origin": ORIGIN, "X-CSRFToken": client.cookies["trading_dev_csrf"]}
    assert (
        client.post(
            "/api/v1/auth/login",
            headers=headers,
            json=dict(email="fixture@example.invalid", password=PASSWORD.get_secret_value()),
        ).status_code
        == 200
    )
    if mfa:
        assert (
            client.post(
                "/api/v1/auth/mfa/verify",
                headers=headers,
                json=dict(factor_id=str(FACTOR), code="123456"),
            ).status_code
            == 200
        )
    return headers


def sql(admin, statement, **params):
    with admin.begin() as connection:
        result = connection.execute(text(statement), params)
        return result.fetchall() if result.returns_rows else None


def test_defaults_do_not_insert_and_saved_preferences_survive_restart(environment, database):
    client, service, _, stub, admin = environment
    headers = login(client)
    before = sql(admin, "SELECT idle_until, expires_at FROM app.auth_sessions")[0]
    response = client.get(PATH, headers=headers)
    assert response.json() == DEFAULT and response.headers["cache-control"] == "no-store"
    assert sql(admin, "SELECT count(*) FROM app.workspace_preferences")[0][0] == 0
    response = client.put(PATH, headers=headers, json=UPDATE)
    assert response.status_code == 200 and response.json() == {**UPDATE, "revision": 1}
    assert sql(admin, "SELECT idle_until, expires_at FROM app.auth_sessions")[0] == before
    url, project = database
    restarted = BrowserAuth(stub.provider(), SessionDatabase(url("auth"), project), service.vault)
    store = WorkspaceDatabase(url("runtime"), project)
    with TestClient(create_app(browser=restarted, workspace=store), base_url=ORIGIN) as other:
        other.cookies.update(client.cookies)
        assert other.get(PATH, headers=headers).json() == {**UPDATE, "revision": 1}
        assert other.put(PATH, headers=headers, json={**DEFAULT, "revision": 1}).json() == {
            **DEFAULT,
            "revision": 2,
        }


def test_stale_insert_and_update_return_conflict_without_revoking_session(environment):
    client, _, _, _, admin = environment
    headers = login(client)
    assert client.put(PATH, headers=headers, json=UPDATE).status_code == 200
    for stale in [DEFAULT, {**DEFAULT, "revision": 99}]:
        result = client.put(PATH, headers=headers, json=stale)
        assert result.status_code == 409
        assert set(result.json()) == {"error", "request_id"}
        assert "set-cookie" not in result.headers
        assert client.get(PATH, headers=headers).json() == {**UPDATE, "revision": 1}
    assert sql(admin, "SELECT count(*) FROM app.auth_sessions")[0][0] == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"revision": 0},
        {**UPDATE, "owner_id": str(SUBJECT)},
        {**UPDATE, "updated_at": "now"},
        {**UPDATE, "theme": "system"},
        {**UPDATE, "theme": 1},
        {**UPDATE, "display_currency": "EUR"},
        {**UPDATE, "amount_masked": "false"},
        {**UPDATE, "amount_masked": 0},
        {**UPDATE, "revision": "0"},
        {**UPDATE, "revision": True},
        {**UPDATE, "revision": -1},
        {**UPDATE, "revision": 1.5},
        {**UPDATE, "revision": 9007199254740992},
        {k: v for k, v in UPDATE.items() if k != "theme"},
        {k: v for k, v in UPDATE.items() if k != "display_currency"},
        {k: v for k, v in UPDATE.items() if k != "amount_masked"},
    ],
)
def test_invalid_preferences_are_generic_and_cannot_write(environment, body):
    client, _, _, _, admin = environment
    headers = login(client)
    result = client.put(PATH, headers=headers, json=body)
    assert result.status_code == 422 and set(result.json()) == {"error", "request_id"}
    assert sql(admin, "SELECT count(*) FROM app.workspace_preferences")[0][0] == 0


@pytest.mark.parametrize(
    "state",
    ["anonymous", "pending", "recovery", "expired", "disabled", "unmapped", "remapped", "provider"],
)
def test_only_active_verified_sessions_can_write(environment, state):
    client, _, _, stub, admin = environment
    headers = login(client, mfa=state != "pending")
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
    elif state == "unmapped":
        sql(admin, "DELETE FROM app.auth_sessions")
        sql(admin, "DELETE FROM app.owner_identities")
    elif state == "remapped":
        other = uuid4()
        sql(admin, "INSERT INTO app.owners (id, is_active) VALUES (:id, true)", id=other)
        sql(admin, "UPDATE app.owner_identities SET owner_id=:id", id=other)
    elif state == "provider":
        stub.fail_refresh = True
    result = client.put(PATH, headers=headers, json=UPDATE)
    assert result.status_code == (503 if state == "provider" else 401)
    assert sql(admin, "SELECT count(*) FROM app.workspace_preferences")[0][0] == 0


@pytest.mark.parametrize(
    "attack,expected",
    [
        ("csrf", 403),
        ("origin", 403),
        ("bearer", 403),
        ("query", 403),
        ("cross_site", 403),
        ("duplicate", 403),
        ("type", 415),
        ("large", 413),
    ],
)
def test_preferences_share_the_browser_boundary(environment, attack, expected):
    client, _, _, _, admin = environment
    headers = login(client)
    path = PATH
    body = None
    if attack == "csrf":
        headers.pop("X-CSRFToken")
    if attack == "origin":
        headers["Origin"] = "https://untrusted.invalid"
    if attack == "bearer":
        headers["Authorization"] = "Bearer synthetic"
    if attack == "query":
        path += "?owner=another"
    if attack == "cross_site":
        headers["Sec-Fetch-Site"] = "same-site"
    if attack == "duplicate":
        headers = [*headers.items(), ("Origin", ORIGIN)]
    if attack == "type":
        headers["Content-Type"] = "text/plain"
    if attack == "large":
        body = " " * 4097
        headers["Content-Type"] = "application/json"
    result = client.put(path, headers=headers, json=UPDATE if body is None else None, content=body)
    assert result.status_code == expected
    assert sql(admin, "SELECT count(*) FROM app.workspace_preferences")[0][0] == 0


def test_read_requires_bound_csrf_and_rejects_cross_site(environment):
    client, _, _, _, _ = environment
    headers = login(client)
    assert (
        client.get(PATH, headers={**headers, "Origin": "https://untrusted.invalid"}).status_code
        == 403
    )
    assert client.get(PATH).status_code == 401


def test_other_owner_is_isolated_and_client_owner_header_is_ignored(environment, database):
    client, _, workspace, _, admin = environment
    url, project = database
    provision_owner(url("bootstrap"), project, ISSUER, uuid4())
    own = sql(
        admin,
        "SELECT owner_id FROM app.owner_identities WHERE subject=:subject",
        subject=str(SUBJECT),
    )[0][0]
    other = sql(admin, "SELECT id FROM app.owners WHERE id<>:owner", owner=own)[0][0]
    with workspace.transaction(other) as unit:
        assert unit.compare_preferences(PreferenceUpdate(**UPDATE))
    headers = {**login(client), "X-Owner-ID": str(other)}
    assert client.get(PATH, headers=headers).json() == DEFAULT
    assert client.put(PATH, headers=headers, json=DEFAULT).json() == {**DEFAULT, "revision": 1}
    with workspace.transaction(other) as unit:
        assert unit.preference_snapshot().model_dump() == {**UPDATE, "revision": 1}
    with workspace._engine.connect() as connection:
        assert connection.execute(
            text("SELECT current_setting('app.owner_id',true)")
        ).scalar_one() in (None, "")
        assert (
            connection.execute(text("SELECT count(*) FROM app.workspace_preferences")).scalar_one()
            == 0
        )


@pytest.mark.parametrize("initial", [0, 1])
def test_concurrent_runtime_writes_have_exactly_one_winner(environment, initial):
    client, _, workspace, _, admin = environment
    login(client)
    owner = sql(admin, "SELECT id FROM app.owners")[0][0]
    if initial:
        with workspace.transaction(owner) as unit:
            unit.compare_preferences(PreferenceUpdate(**DEFAULT))
    barrier = threading.Barrier(2)

    def save(theme):
        with workspace.transaction(owner) as unit:
            barrier.wait(5)
            return unit.compare_preferences(
                PreferenceUpdate(**{**UPDATE, "theme": theme, "revision": initial})
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, ("light", "dark")))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1 and winners[0].revision == initial + 1


def test_revocation_between_refresh_and_guard_prevents_write(environment, monkeypatch):
    client, service, _, _, admin = environment
    headers = login(client)
    original = service.store.workspace_guard

    @contextmanager
    def revoked(key, owner):
        service.store.revoke(key, "a" * 32, all_sessions=True)
        with original(key, owner) as validate:
            yield validate

    monkeypatch.setattr(service.store, "workspace_guard", revoked)
    assert client.put(PATH, headers=headers, json=UPDATE).status_code == 401
    assert sql(admin, "SELECT count(*) FROM app.workspace_preferences")[0][0] == 0


@pytest.mark.parametrize("failure", ["disabled", "expired", "sql"])
def test_failure_after_sql_rolls_back_and_resets_context(environment, monkeypatch, failure):
    client, _, workspace, _, admin = environment
    headers = login(client)
    original = WorkspaceTransaction.compare_preferences

    def failing(unit, update):
        result = original(unit, update)
        if failure == "sql":
            raise RuntimeError("synthetic-private-diagnostic")
        if failure == "disabled":
            sql(admin, "UPDATE app.owners SET is_active=false")
        if failure == "expired":
            sql(
                admin,
                "UPDATE app.auth_sessions SET idle_until=clock_timestamp()-interval '1 second'",
            )
        return result

    monkeypatch.setattr(WorkspaceTransaction, "compare_preferences", failing)
    result = client.put(PATH, headers=headers, json=UPDATE)
    assert result.status_code == (503 if failure == "sql" else 401)
    assert "synthetic-private" not in result.text
    assert sql(admin, "SELECT count(*) FROM app.workspace_preferences")[0][0] == 0
    with workspace._engine.connect() as connection:
        assert connection.execute(
            text("SELECT current_setting('app.owner_id',true)")
        ).scalar_one() in (None, "")


def test_logout_waits_for_inflight_commit_then_blocks_later_access(environment, monkeypatch):
    client, service, _, _, admin = environment
    headers = login(client)
    key = verifier(client.cookies["trading_dev_session"])
    entered, release, revoking = threading.Event(), threading.Event(), threading.Event()
    original = WorkspaceTransaction.compare_preferences

    def paused(unit, update):
        result = original(unit, update)
        entered.set()
        assert release.wait(10)
        return result

    def revoke():
        revoking.set()
        service.store.revoke(key, "a" * 32)

    monkeypatch.setattr(WorkspaceTransaction, "compare_preferences", paused)
    with ThreadPoolExecutor(max_workers=2) as executor:
        saving = executor.submit(client.put, PATH, headers=headers, json=UPDATE)
        assert entered.wait(5)
        revocation = executor.submit(revoke)
        try:
            assert revoking.wait(5)
            assert not revocation.done()
        finally:
            release.set()
        assert saving.result().status_code == 200
        revocation.result()
    assert sql(admin, "SELECT revision FROM app.workspace_preferences")[0][0] == 1
    assert client.get(PATH, headers=headers).status_code == 401


def test_runtime_cannot_assign_revision_and_max_revision_cannot_wrap(environment):
    client, _, workspace, _, admin = environment
    headers = login(client)
    assert client.put(PATH, headers=headers, json=UPDATE).status_code == 200
    with workspace._engine.begin() as connection, pytest.raises(DBAPIError) as error:
        connection.execute(text("UPDATE app.workspace_preferences SET revision=1"))
    assert error.value.orig.sqlstate == "42501"
    sql(admin, "ALTER TABLE app.workspace_preferences DISABLE TRIGGER USER")
    sql(admin, "UPDATE app.workspace_preferences SET revision=9007199254740991")
    sql(admin, "ALTER TABLE app.workspace_preferences ENABLE TRIGGER USER")
    assert (
        client.put(PATH, headers=headers, json={**UPDATE, "revision": 9007199254740991}).status_code
        == 409
    )
