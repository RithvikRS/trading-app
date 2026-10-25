"""Real PostgreSQL ownership, HTTP callback and revocation races; synthetic provider only."""

import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx2 as httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from starlette.testclient import TestClient

from database_tests.conftest import reset_database
from database_tests.test_browser_sessions import CSRF, REQUEST, login, sql
from database_tests.test_browser_sessions import browser as browser
from tests.auth_support import FACTOR, ISSUER, PASSWORD
from tests.indmoney_support import ACCESS, CODE, REFRESH, IndmoneyStub
from trading_api.application import create_app
from trading_api.config import Settings
from trading_api.indmoney import CALLBACK_COOKIE
from trading_auth.models import AuthenticationDenied, WorkspaceContextChanged
from trading_auth.session_models import verifier
from trading_connectors.indmoney_keys import ConnectorKeys
from trading_connectors.indmoney_models import (
    PREFIX,
    ConnectorBusy,
    ConnectorRejected,
    ConnectorUnavailable,
)
from trading_connectors.indmoney_service import IndmoneyService
from trading_db import migrate, recovery
from trading_db.connections import engine_for
from trading_db.enrollment import provision_owner
from trading_db.indmoney import IndmoneyDatabase
from trading_db.recovery import HEAD


@pytest.fixture
def connector(browser, database):
    auth, _, admin = browser
    url, project = database
    provider = IndmoneyStub()
    client = provider.provider()
    keys = ConnectorKeys({1: secrets.token_bytes(32)}, 1)
    store = IndmoneyDatabase(url("auth"), project, keys=keys, binding=client.binding)
    service = IndmoneyService(auth, store, client)
    cookie = login(auth)
    context = auth.vault.workspace_context(verifier(cookie))
    try:
        yield service, provider, admin, (cookie, CSRF, context, REQUEST)
    finally:
        store.close()


def receive(service, inputs, *, issuer=None):
    url, binding = service.begin(*inputs)
    state = parse_qs(urlsplit(url).query)["state"][0]
    service.store.receive(state, binding, SecretStr(CODE), issuer, REQUEST)
    return state, binding


def test_authorization_renewal_disconnect_restart_and_event_privacy(connector, database):
    service, provider, admin, inputs = connector
    assert service.status(*inputs)["status"] == "disconnected"
    state, binding = receive(service, inputs)
    assert service.status(*inputs)["can_complete"]
    attempt = sql(admin, "SELECT * FROM app.indmoney_attempts")[0]
    assert state.encode() not in bytes(attempt.state_hash)
    assert binding.encode() not in bytes(attempt.browser_hash)
    assert CODE.encode() not in bytes(attempt.sealed)
    service.complete(*inputs)
    assert service.status(*inputs)["status"] == "authorized"
    assert not service.status(*inputs)["financial_access_enabled"]
    assert sql(admin, "SELECT count(*) FROM app.indmoney_attempts")[0][0] == 0
    row = sql(admin, "SELECT * FROM app.indmoney_connections")[0]
    assert ACCESS.encode() not in bytes(row.sealed) and REFRESH.encode() not in bytes(row.sealed)
    url, project = database
    restarted = IndmoneyDatabase(
        url("auth"), project, keys=service.store.keys, binding=service.provider.binding
    )
    try:
        assert restarted.status(row.owner_id, verifier(inputs[0]))["status"] == "authorized"
    finally:
        restarted.close()
    service.complete(*inputs, refresh=True)
    assert provider.refreshes == 1
    assert service.disconnect(*inputs)["provider_cleanup"] == "confirmed"
    assert provider.revocations == 2
    assert sql(admin, "SELECT sealed FROM app.indmoney_connections")[0][0] is None
    events = repr(sql(admin, "SELECT * FROM app.indmoney_events"))
    for value in (state, binding, CODE, ACCESS, REFRESH, inputs[0]):
        assert value not in events
    with pytest.raises(ConnectorRejected):
        service.complete(*inputs, refresh=True)


@pytest.mark.parametrize(
    "failure",
    ["state", "browser", "issuer", "required_issuer", "denied", "expiry", "logout", "disabled"],
)
def test_callback_cannot_complete_invalid_or_expired_attempt(connector, failure):
    service, provider, admin, inputs = connector
    provider.issuer_required = failure == "required_issuer"
    url, binding = service.begin(*inputs)
    state = parse_qs(urlsplit(url).query)["state"][0]
    if failure == "state":
        state = "a" * 43
    if failure == "browser":
        binding = "b" * 43
    if failure == "expiry":
        sql(
            admin,
            "UPDATE app.indmoney_attempts SET "
            "created_at=statement_timestamp()-interval '6 minutes', "
            "expires_at=statement_timestamp()-interval '1 minute'",
        )
    if failure == "logout":
        service.browser.logout(inputs[0], inputs[1], REQUEST)
    if failure == "disabled":
        sql(admin, "UPDATE app.owners SET is_active=false")
    try:
        service.store.receive(
            state,
            binding,
            None if failure == "denied" else SecretStr(CODE),
            "https://attacker.invalid" if failure == "issuer" else None,
            REQUEST,
        )
    except ConnectorRejected:
        pass
    assert (
        sql(admin, "SELECT count(*) FROM app.indmoney_attempts WHERE stage='received'")[0][0] == 0
    )
    assert not any(request.method == "POST" for request in provider.requests)


def test_callback_is_single_use_and_replacement_session_cannot_complete(connector):
    service, _, admin, inputs = connector
    state, binding = receive(service, inputs)
    with pytest.raises(ConnectorRejected):
        service.store.receive(state, binding, SecretStr("different-code"), None, REQUEST)
    replacement = login(service.browser)
    with pytest.raises(WorkspaceContextChanged):
        service.complete(replacement, inputs[1], inputs[2], REQUEST)
    context = service.browser.vault.workspace_context(verifier(replacement))
    with pytest.raises(ConnectorRejected):
        service.complete(replacement, inputs[1], context, REQUEST)
    assert sql(admin, "SELECT sealed FROM app.indmoney_connections")[0][0] is None
    service.complete(*inputs)
    with pytest.raises(ConnectorRejected):
        service.complete(*inputs)


@pytest.mark.parametrize("interruption", ["disconnect", "logout", "revoke_all", "disabled"])
def test_inflight_exchange_cannot_publish_after_revocation(connector, interruption):
    service, provider, admin, inputs = connector
    receive(service, inputs)
    entered, released = threading.Event(), threading.Event()

    def wait():
        assert (
            sql(
                admin,
                "SELECT count(*) FROM pg_stat_activity WHERE usename='trading_auth' "
                "AND state='idle in transaction'",
            )[0][0]
            == 0
        )
        entered.set()
        assert released.wait(10)

    provider.hook = wait
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(service.complete, *inputs)
        assert entered.wait(5)
        try:
            if interruption == "disconnect":
                assert service.disconnect(*inputs)["provider_cleanup"] == "unavailable"
            elif interruption == "disabled":
                sql(admin, "UPDATE app.owners SET is_active=false")
            else:
                service.browser.logout(
                    inputs[0], inputs[1], REQUEST, all_sessions=interruption == "revoke_all"
                )
        finally:
            released.set()
        with pytest.raises((AuthenticationDenied, ConnectorRejected)):
            result.result()
    assert sql(admin, "SELECT sealed FROM app.indmoney_connections")[0][0] is None
    assert provider.revocations == 2


def test_renewal_is_serialized_and_uncertain_result_requires_reconnect(connector):
    service, provider, admin, inputs = connector
    receive(service, inputs)
    service.complete(*inputs)
    entered, released = threading.Event(), threading.Event()
    provider.hook = lambda: (entered.set(), released.wait(10))
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(service.complete, *inputs, refresh=True)
        assert entered.wait(5)
        try:
            with pytest.raises(ConnectorBusy):
                service.complete(*inputs, refresh=True)
        finally:
            released.set()
        result.result()
    assert provider.refreshes == 1
    provider.hook = None
    provider.override = lambda _: httpx.Response(
        503, stream=httpx.ByteStream(b"private-provider-error")
    )
    with pytest.raises(ConnectorUnavailable):
        service.complete(*inputs, refresh=True)
    assert provider.refreshes == 2

    assert service.status(*inputs)["status"] == "reconnect_required"
    assert sql(admin, "SELECT sealed FROM app.indmoney_connections")[0][0] is None
    with pytest.raises(ConnectorRejected):
        service.complete(*inputs, refresh=True)
    assert provider.refreshes == 2

    with pytest.raises((ConnectorRejected, ConnectorBusy)):
        service.begin(*inputs)
    assert service.disconnect(*inputs)["provider_cleanup"] == "unavailable"


def test_disconnect_local_first_with_provider_outage_or_missing_key(connector):
    service, provider, admin, inputs = connector
    receive(service, inputs)
    service.complete(*inputs)
    provider.fail_revoke = True
    assert service.disconnect(*inputs)["provider_cleanup"] == "unavailable"
    assert sql(admin, "SELECT sealed FROM app.indmoney_connections")[0][0] is None
    receive(service, inputs)
    service.complete(*inputs)
    service.store.keys = ConnectorKeys({2: secrets.token_bytes(32)}, 2)
    assert service.disconnect(*inputs)["provider_cleanup"] == "unavailable"
    assert sql(admin, "SELECT sealed FROM app.indmoney_connections")[0][0] is None


def test_client_metadata_substitution_cannot_rebind_saved_tokens(connector):
    service, provider, admin, inputs = connector
    receive(service, inputs)
    service.complete(*inputs)
    service.store.binding = "a" * 64
    sql(admin, "UPDATE app.indmoney_connections SET client_binding='" + "a" * 64 + "'")
    with pytest.raises(ConnectorUnavailable):
        service.complete(*inputs, refresh=True)
    assert provider.refreshes == 0
    assert service.disconnect(*inputs)["provider_cleanup"] == "unavailable"
    assert sql(admin, "SELECT sealed FROM app.indmoney_connections")[0][0] is None


def test_expiry_never_extends_with_exchange_latency(connector):
    from dataclasses import replace
    from datetime import timedelta

    service, _, admin, inputs = connector
    receive(service, inputs)
    service.complete(*inputs)
    owner = sql(admin, "SELECT owner_id FROM app.indmoney_connections")[0][0]
    with service.browser.store.workspace_guard(verifier(inputs[0]), owner) as validate:
        operation = service.store.claim(owner, verifier(inputs[0]), refresh=True)
        earlier = replace(operation, expires=operation.expires - timedelta(seconds=5))
        tokens = operation.tokens.model_copy(update={"expires_in": 1})
        with pytest.raises(ConnectorRejected):
            service.store.publish(earlier, tokens, REQUEST, validate=validate)
    assert sql(admin, "SELECT status FROM app.indmoney_connections")[0][0] == "refreshing"


def test_owned_rls_minimal_grants_and_pool_cleanup(connector, database):
    service, _, admin, inputs = connector
    receive(service, inputs)
    service.complete(*inputs)
    url, project = database
    second_subject = uuid4()
    provision_owner(url("bootstrap"), project, ISSUER, second_subject)
    second = service.browser.store.lookup(ISSUER, second_subject).owner_id
    with service.store.owned(second) as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM app.indmoney_connections")).scalar_one()
            == 0
        )
    with service.store._transaction() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM app.indmoney_connections")).scalar_one()
            == 0
        )
        connection.execute(
            text("SELECT set_config('app.owner_id', :owner, false)"), {"owner": str(second)}
        )
    with service.store._transaction() as connection:
        assert (
            connection.execute(
                text("SELECT nullif(current_setting('app.owner_id', true), '')")
            ).scalar_one()
            is None
        )
    runtime = engine_for(url("runtime"))
    try:
        for table in ("indmoney_connections", "indmoney_attempts", "indmoney_events"):
            with pytest.raises(DBAPIError), runtime.begin() as connection:
                connection.execute(text(f"SELECT * FROM app.{table}"))
    finally:
        runtime.dispose()
    for query in (
        "DELETE FROM app.indmoney_events",
        "UPDATE app.indmoney_events SET outcome='success'",
        "TRUNCATE app.indmoney_connections",
        "UPDATE app.indmoney_connections SET owner_id=:owner",
    ):
        auth_engine = engine_for(url("auth"))
        try:
            with pytest.raises(DBAPIError), auth_engine.begin() as connection:
                connection.execute(text(query), dict(owner=second))
        finally:
            auth_engine.dispose()
    assert (
        sql(
            admin,
            "SELECT count(*) FROM pg_class WHERE relnamespace='app'::regnamespace "
            "AND relname LIKE 'indmoney_%' AND relkind='r' "
            "AND (NOT relrowsecurity OR NOT relforcerowsecurity)",
        )[0][0]
        == 0
    )


def test_rotation_and_commit_validation_roll_back_on_failure(connector):
    service, _, admin, inputs = connector
    receive(service, inputs)
    service.complete(*inputs)
    original = sql(admin, "SELECT * FROM app.indmoney_connections")[0]
    new_key = secrets.token_bytes(32)
    service.store.keys = ConnectorKeys(dict(service.store.keys._keys) | {2: new_key}, 2)
    with service.browser.store.workspace_guard(verifier(inputs[0]), original.owner_id):
        service.store.rotate(original.owner_id, REQUEST)
    rotated = sql(admin, "SELECT * FROM app.indmoney_connections")[0]
    assert rotated.revision == original.revision and bytes(rotated.sealed)[:4] == (2).to_bytes(
        4, "big"
    )
    service.store.keys = ConnectorKeys({2: new_key}, 2)
    service.complete(*inputs, refresh=True)
    with service.browser.store.workspace_guard(verifier(inputs[0]), original.owner_id):
        operation = service.store.claim(original.owner_id, verifier(inputs[0]), refresh=True)

        def invalid():
            raise AuthenticationDenied()

        with pytest.raises(AuthenticationDenied):
            service.store.publish(operation, operation.tokens, REQUEST, validate=invalid)
    assert sql(admin, "SELECT status FROM app.indmoney_connections")[0][0] == "refreshing"


def test_durable_admission_fresh_mfa_and_no_implicit_reconnect(connector):
    service, _, admin, inputs = connector
    for _ in range(5):
        service.begin(*inputs)
    with pytest.raises(ConnectorBusy):
        service.begin(*inputs)
    assert sql(admin, "SELECT count(*) FROM app.indmoney_attempts")[0][0] == 1
    assert sql(admin, "SELECT count(*) FROM app.indmoney_events WHERE event='start'")[0][0] == 5


def test_stale_authentication_cannot_initiate_provider_authorization(connector):
    service, provider, admin, inputs = connector
    auth = service.browser
    row = auth.store.claim(verifier(inputs[0]), ("active",), REQUEST)
    state = auth.vault.open(row).model_copy(update={"fresh_until": 1})
    auth.store.finish(row, row.verifier, auth.vault.seal(state, row.verifier), "active", REQUEST)
    with pytest.raises(AuthenticationDenied):
        service.begin(*inputs)
    assert not provider.requests
    assert sql(admin, "SELECT count(*) FROM app.indmoney_attempts")[0][0] == 0


def test_recovery_omits_every_live_connector_and_old_session(connector, database):
    service, _, admin, inputs = connector
    receive(service, inputs)
    service.complete(*inputs)
    url, project = database
    key = Fernet.generate_key()
    encrypted = recovery.export_snapshot(url("bootstrap"), project, key)
    rows = recovery.decode_snapshot(encrypted, key)
    assert "indmoney_connections" not in rows and "indmoney_attempts" not in rows
    assert rows["indmoney_events"]
    assert ACCESS not in repr(rows) and REFRESH not in repr(rows)
    reset_database(admin, project)
    migrate.apply(url(), project)
    recovery.restore_snapshot(url("bootstrap"), project, encrypted, key)
    assert sql(admin, "SELECT count(*) FROM app.indmoney_connections")[0][0] == 0
    with pytest.raises(AuthenticationDenied):
        service.status(*inputs)


def test_http_callback_preserves_strict_session_and_csrf_and_scrubs_redirect(connector, caplog):
    service, provider, _, _ = connector
    app = create_app(
        Settings(environment="test", port=8443, https_enabled=True),
        browser=service.browser,
        indmoney=service,
    )
    with TestClient(app, base_url="https://127.0.0.1:8443", follow_redirects=False) as client:
        client.get("/api/v1/auth/bootstrap")
        csrf = client.cookies["__Host-portfolio-csrf"]
        headers = {"Origin": "https://127.0.0.1:8443", "X-CSRFToken": csrf}
        assert (
            client.post(
                "/api/v1/auth/login",
                headers=headers,
                json={"email": "fixture@example.invalid", "password": PASSWORD.get_secret_value()},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/v1/auth/mfa/verify",
                headers=headers,
                json={"factor_id": str(FACTOR), "code": "123456"},
            ).status_code
            == 200
        )
        session = client.get("/api/v1/auth/session", headers=headers).json()
        headers["X-Workspace-Context"] = session["workspace_context"]
        started = client.post(PREFIX + "/authorize", headers=headers, json={})
        assert started.status_code == 200
        assert (
            "SameSite=lax" in started.headers["set-cookie"]
            and "HttpOnly" in started.headers["set-cookie"]
        )
        state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]
        session_cookie = client.cookies["__Host-portfolio-session"]
        binding = client.cookies[CALLBACK_COOKIE]
        # A real cross-site navigation has only the separate Lax callback cookie.
        client.cookies.clear()
        client.cookies.set(CALLBACK_COOKIE, binding)
        returned = client.get(
            PREFIX + "/callback?state=" + state + "&code=" + CODE,
            headers={
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Site": "cross-site",
            },
        )
        assert returned.status_code == 303 and returned.headers["location"] == "/"
        assert "__Host-portfolio-csrf" not in returned.headers.get("set-cookie", "")
        assert CODE not in returned.text and returned.headers["referrer-policy"] == "no-referrer"
        client.cookies.clear()
        client.cookies.set("__Host-portfolio-session", session_cookie)
        client.cookies.set("__Host-portfolio-csrf", csrf)
        assert client.post(PREFIX + "/complete", headers=headers, json={}).json() == {
            "status": "authorized"
        }
        assert (
            client.post(
                PREFIX + "/refresh",
                headers=headers | {"Origin": "https://attacker.invalid"},
                json={},
            ).status_code
            == 403
        )
        assert client.post(
            PREFIX + "/refresh", headers=headers, content='{"x":1,"x":2}'
        ).status_code in {400, 415}
        assert client.get(PREFIX + "?unexpected=1", headers=headers).status_code == 403
        assert provider.refreshes == 0
        assert CODE not in caplog.text and ACCESS not in caplog.text


def test_migration_preserves_earlier_records_and_refuses_destructive_downgrade(connector, database):
    service, _, admin, inputs = connector
    receive(service, inputs)
    url, project = database
    migrate.apply(url(), project)
    assert sql(admin, "SELECT count(*) FROM app.indmoney_attempts")[0][0] == 1
    with pytest.raises(DBAPIError):
        migrate.apply(url(), project, direction="downgrade", target="0017_reconciled_completion")
    assert migrate.revision(url(), project) == HEAD
