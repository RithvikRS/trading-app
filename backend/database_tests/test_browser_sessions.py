"""Real PostgreSQL and real HTTP/provider adapter with synthetic signing keys."""

import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from starlette.testclient import TestClient

from tests.auth_support import FACTOR, ISSUER, PASSWORD, SETUP, SUBJECT
from tests.browser_support import BACKUP, BrowserProviderStub
from trading_api.application import create_app
from trading_auth.browser import BrowserAuth
from trading_auth.models import (
    AuthenticationDenied,
    AuthenticationLimited,
    AuthenticationUnavailable,
)
from trading_auth.session_models import Vault, verifier
from trading_db import migrate
from trading_db.connections import engine_for
from trading_db.enrollment import provision_owner, revoke_owner
from trading_db.sessions import SessionDatabase

REQUEST = "a" * 32
CSRF = "synthetic-bound-csrf"
EMAIL = "fixture@example.invalid"


@pytest.fixture
def browser(database):
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
    admin = engine_for(url("bootstrap"), migration=True)
    try:
        yield service, stub, admin
    finally:
        service.close()
        admin.dispose()


def login(service, csrf=CSRF, factor=FACTOR):
    cookie, _ = service.start(EMAIL, PASSWORD, csrf, REQUEST)
    active, _ = service.mfa(cookie, factor, SecretStr("123456"), csrf, REQUEST)
    return active


def sql(admin, statement, **params):
    with admin.begin() as connection:
        result = connection.execute(text(statement), params)
        return result.fetchall() if result.returns_rows else None


def test_session_rotation_encryption_restart_and_non_sliding_poll(browser, database):
    service, stub, admin = browser
    pending, _ = service.start(EMAIL, PASSWORD, CSRF, REQUEST)
    with pytest.raises(AuthenticationDenied):
        service.session(pending, CSRF, REQUEST)
    active, _ = service.mfa(pending, FACTOR, SecretStr("123456"), CSRF, REQUEST)
    assert active != pending
    with pytest.raises(AuthenticationDenied):
        service.session(pending, CSRF, REQUEST)
    before = sql(admin, "SELECT * FROM app.auth_sessions")[0]
    assert bytes(before.verifier) == verifier(active)
    assert active.encode() not in bytes(before.sealed)
    assert b"synthetic-refresh" not in bytes(before.sealed) and b"eyJ" not in bytes(before.sealed)
    url, project = database
    restarted = BrowserAuth(stub.provider(), SessionDatabase(url("auth"), project), service.vault)
    try:
        result = restarted.session(active, CSRF, REQUEST)
        assert result["status"] == "authenticated"
        after = sql(admin, "SELECT * FROM app.auth_sessions")[0]
        assert after.idle_until == before.idle_until and after.expires_at == before.expires_at
        assert after.sealed != before.sealed and stub.renewals == 1
        restarted.session(active, CSRF, REQUEST, activity=True)
        final = sql(admin, "SELECT * FROM app.auth_sessions")[0]
        assert final.idle_until > before.idle_until and final.expires_at == before.expires_at
    finally:
        restarted.close()


@pytest.mark.parametrize(
    "condition",
    ["idle", "absolute", "lease", "disabled", "wrong_key", "csrf", "provider", "factor"],
)
def test_invalid_and_unavailable_sessions_fail_closed(browser, condition):
    service, stub, admin = browser
    cookie = login(service)
    if condition == "idle":
        sql(admin, "UPDATE app.auth_sessions SET idle_until=clock_timestamp()-interval '1 second'")
    elif condition == "absolute":
        sql(
            admin,
            "UPDATE app.auth_sessions SET created_at=statement_timestamp()-interval '9 hours', "
            "expires_at=statement_timestamp()-interval '1 hour'",
        )
    elif condition == "lease":
        sql(
            admin,
            "UPDATE app.auth_sessions SET lease=:lease, "
            "lease_until=clock_timestamp()-interval '1 second'",
            lease=uuid4(),
        )
    elif condition == "disabled":
        sql(admin, "UPDATE app.owners SET is_active=false")
    elif condition == "wrong_key":
        service.vault = Vault(secrets.token_bytes(32))
    elif condition == "provider":
        stub.fail_refresh = True
    elif condition == "factor":
        stub.factors = []
    with pytest.raises((AuthenticationDenied, AuthenticationUnavailable)):
        service.session(cookie, "wrong" if condition == "csrf" else CSRF, REQUEST)
    assert sql(admin, "SELECT count(*) FROM app.auth_sessions")[0][0] == 0


def test_concurrent_refresh_has_one_provider_exchange_and_no_open_db_transaction(browser):
    service, stub, admin = browser
    cookie = login(service)
    entered, release = threading.Event(), threading.Event()

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
        assert release.wait(10)

    stub.refresh_hook = wait
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(service.session, cookie, CSRF, REQUEST)
        assert entered.wait(5)
        try:
            with pytest.raises(AuthenticationLimited):
                service.session(cookie, CSRF, REQUEST)
        finally:
            release.set()
        assert first.result()["status"] == "authenticated"
    assert stub.renewals == 1


def test_revocation_wins_against_inflight_renewal_and_new_login(browser):
    service, stub, admin = browser
    cookie = login(service)
    row = service.store.claim(verifier(cookie), ("active",), REQUEST)
    state = service.vault.open(row)
    started = datetime.now(UTC) - timedelta(seconds=1)
    service.store.revoke(row.verifier, REQUEST, all_sessions=True)
    with pytest.raises(AuthenticationDenied):
        service.store.finish(
            row, row.verifier, service.vault.seal(state, row.verifier), "active", REQUEST
        )
    with pytest.raises(AuthenticationDenied):
        service.store.create(
            row.verifier,
            row.owner,
            state.issuer,
            state.subject,
            "login",
            service.vault.seal(state, row.verifier),
            started,
            REQUEST,
            "login",
        )
    assert sql(admin, "SELECT count(*) FROM app.auth_sessions")[0][0] == 0


def test_logout_all_is_local_first_and_survives_upstream_failure(browser):
    service, stub, admin = browser
    first, second = login(service), login(service)
    stub.fail_logout = True
    result = service.logout(first, CSRF, REQUEST, all_sessions=True)
    assert result == {"status": "signed_out", "provider_cleanup": "unavailable"}
    with pytest.raises(AuthenticationDenied):
        service.session(second, CSRF, REQUEST)
    assert sql(admin, "SELECT count(*) FROM app.auth_sessions")[0][0] == 0
    assert sql(admin, "SELECT event, outcome FROM app.security_events WHERE outcome='unavailable'")


def test_durable_limiter_survives_restart_and_is_atomic(browser, database):
    service, _, admin = browser
    url, project = database
    key = service.vault.rate_key(EMAIL)
    for _ in range(4):
        service.store.admit(key)
    other = SessionDatabase(url("auth"), project)
    try:

        def take(store):
            try:
                store.admit(key)
                return True
            except AuthenticationLimited:
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(take, [service.store, other]))
        assert sorted(results) == [False, True]
        with pytest.raises(AuthenticationLimited):
            other.admit(key)
        assert sql(admin, "SELECT count(*) FROM app.auth_admissions")[0][0] == 5
        for number in range(25):
            other.admit(service.vault.rate_key(str(number)))
        with pytest.raises(AuthenticationLimited):
            other.admit(service.vault.rate_key("another"))
    finally:
        other.close()


def test_recovery_never_grants_workspace_access_and_revoke_precedes_password_change(browser):
    service, stub, admin = browser
    old = login(service)
    service.recovery_request(EMAIL, REQUEST)
    cookie, _ = service.start(EMAIL, SecretStr("654321"), CSRF, REQUEST, recovery=True)
    with pytest.raises(AuthenticationDenied):
        service.session(cookie, CSRF, REQUEST)
    ready, content = service.mfa(cookie, FACTOR, SecretStr("123456"), CSRF, REQUEST)
    assert content["status"] == "password_required"
    with pytest.raises(AuthenticationDenied):
        service.session(ready, CSRF, REQUEST)
    with pytest.raises(AuthenticationDenied):
        service.session(old, CSRF, REQUEST)
    service.password(ready, SecretStr("new-synthetic-password-value"), CSRF, REQUEST)
    assert stub.password_changes == 1
    assert sql(admin, "SELECT count(*) FROM app.auth_sessions")[0][0] == 0
    with pytest.raises(AuthenticationDenied):
        service.password(ready, SecretStr("new-synthetic-password-value"), CSRF, REQUEST)


@pytest.mark.parametrize("failure", ["wrong_email_code", "no_mfa", "password_outage", "no_marker"])
def test_recovery_failures_cannot_bypass_mfa(browser, failure):
    service, stub, admin = browser
    if failure != "no_marker":
        login(service)
    if failure == "no_mfa":
        stub.factors = []
    if failure in {"wrong_email_code", "no_mfa", "no_marker"}:
        with pytest.raises(AuthenticationDenied):
            service.start(
                EMAIL,
                SecretStr("000000" if failure == "wrong_email_code" else "654321"),
                CSRF,
                REQUEST,
                recovery=True,
            )
        assert stub.password_changes == 0
    else:
        cookie, _ = service.start(EMAIL, SecretStr("654321"), CSRF, REQUEST, recovery=True)
        ready, _ = service.mfa(cookie, FACTOR, SecretStr("123456"), CSRF, REQUEST)
        stub.overrides["/user"] = httpx.Response(503)
        with pytest.raises(AuthenticationUnavailable):
            service.password(ready, SecretStr("new-synthetic-password-value"), CSRF, REQUEST)
        assert sql(admin, "SELECT count(*) FROM app.auth_sessions")[0][0] == 0


def test_backup_factor_can_recover_access_replace_lost_factor_and_revoke_old_sessions(browser):
    service, stub, admin = browser
    first = login(service)
    pending, content = service.backup(first, CSRF, REQUEST)
    assert content["setup_key"] == SETUP
    with pytest.raises(AuthenticationDenied):
        service.session(pending, CSRF, REQUEST)
    service.backup_verify(pending, SecretStr("123456"), CSRF, REQUEST)
    assert sql(admin, "SELECT count(*) FROM app.auth_sessions")[0][0] == 0
    recovered = login(service, factor=BACKUP)
    service.remove(recovered, FACTOR, CSRF, REQUEST)
    assert [f["id"] for f in stub.factors] == [str(BACKUP)]
    assert sql(admin, "SELECT count(*) FROM app.auth_sessions")[0][0] == 0
    assert (
        service.session(login(service, factor=BACKUP), CSRF, REQUEST)["status"] == "authenticated"
    )


def test_last_factor_and_stale_authentication_cannot_change_factors(browser):
    service, _, admin = browser
    cookie = login(service)
    with pytest.raises(AuthenticationDenied):
        service.remove(cookie, FACTOR, CSRF, REQUEST)
    cookie = login(service)
    row = service.store.claim(verifier(cookie), ("active",), REQUEST)
    state = service.vault.open(row).model_copy(update={"fresh_until": 1})
    service.store.finish(
        row, row.verifier, service.vault.seal(state, row.verifier), "active", REQUEST
    )
    with pytest.raises(AuthenticationDenied):
        service.backup(cookie, CSRF, REQUEST)


def test_first_enrollment_and_safe_resume_of_unverified_factor(browser):
    service, stub, _ = browser
    stub.factors = []
    pending, content = service.start(EMAIL, PASSWORD, CSRF, REQUEST)
    assert content["setup_key"] == SETUP
    service.logout(pending, CSRF, REQUEST)
    resumed, content = service.start(EMAIL, PASSWORD, CSRF, REQUEST)
    assert "setup_key" not in content
    cookie, _ = service.mfa(resumed, FACTOR, SecretStr("123456"), CSRF, REQUEST)
    assert service.session(cookie, CSRF, REQUEST)["status"] == "authenticated"


def test_event_privileges_and_payload_redaction(browser, database):
    service, _, admin = browser
    cookie = login(service)
    service.logout(cookie, CSRF, REQUEST)
    rows = sql(admin, "SELECT * FROM app.security_events")
    assert {row.event for row in rows} >= {"login", "mfa", "logout"}
    combined = str(rows)
    for value in (cookie, CSRF, EMAIL, PASSWORD.get_secret_value(), "123456", "synthetic-refresh"):
        assert value not in combined
    url, _ = database
    for role, statements in {
        "runtime": [
            "SELECT * FROM app.auth_sessions",
            "SELECT * FROM app.security_events",
            "INSERT INTO app.auth_admissions (key) VALUES (decode(repeat('aa',32),'hex'))",
        ],
        "auth": [
            "DELETE FROM app.security_events",
            "UPDATE app.security_events SET outcome='success'",
            "TRUNCATE app.auth_sessions",
            "SELECT * FROM app.workspace_preferences",
        ],
    }.items():
        engine = engine_for(url(role))
        try:
            for statement in statements:
                with engine.begin() as connection, pytest.raises(DBAPIError) as error:
                    connection.execute(text(statement))
                assert error.value.orig.sqlstate == "42501"
        finally:
            engine.dispose()


def test_browser_http_roundtrip_and_cookie_rotation(browser):
    service, _, _ = browser
    with TestClient(create_app(browser=service), base_url="http://127.0.0.1:8000") as client:
        response = client.get("/api/v1/auth/bootstrap")
        assert response.status_code == 200
        headers = {
            "Origin": "http://127.0.0.1:8000",
            "X-CSRFToken": client.cookies["trading_dev_csrf"],
        }
        response = client.post(
            "/api/v1/auth/login",
            json={"email": EMAIL, "password": PASSWORD.get_secret_value()},
            headers=headers,
        )
        assert response.status_code == 200
        pending = client.cookies["trading_dev_session"]
        response = client.post(
            "/api/v1/auth/mfa/verify",
            json={"factor_id": str(FACTOR), "code": "123456"},
            headers=headers,
        )
        assert response.status_code == 200
        assert pending != client.cookies["trading_dev_session"]
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        assert "Domain=" not in response.headers["set-cookie"]
        assert client.get("/api/v1/auth/session", headers=headers).status_code == 200
        response = client.post("/api/v1/auth/logout", json={}, headers=headers)
        assert response.status_code == 200 and "trading_dev_session" not in client.cookies
        assert client.get("/api/v1/auth/session", headers=headers).status_code == 401


def test_logout_interrupts_renewal_without_resurrection(browser):
    service, stub, _ = browser
    cookie = login(service)
    entered, release = threading.Event(), threading.Event()

    def wait():
        entered.set()
        assert release.wait(10)

    stub.refresh_hook = wait
    with ThreadPoolExecutor(max_workers=1) as executor:
        renewal = executor.submit(service.session, cookie, CSRF, REQUEST)
        assert entered.wait(5)
        try:
            assert service.logout(cookie, CSRF, REQUEST)["status"] == "signed_out"
        finally:
            release.set()
        with pytest.raises(AuthenticationDenied):
            renewal.result()
    with pytest.raises(AuthenticationDenied):
        service.session(cookie, CSRF, REQUEST)


def test_revoked_request_cannot_authorize_a_credential_mutation(browser):
    service, _, _ = browser
    cookie = login(service)
    row = service.store.claim(verifier(cookie), ("active",), REQUEST)
    service.store.revoke(row.verifier, REQUEST)
    with pytest.raises(AuthenticationDenied):
        service.store.revoke(row.verifier, REQUEST, all_sessions=True, lease=row.lease)


def test_abandoned_backup_can_be_removed_only_after_fresh_existing_factor(browser):
    service, stub, _ = browser
    pending, result = service.backup(login(service), CSRF, REQUEST)
    assert result["factor_id"] == str(BACKUP)
    service.logout(pending, CSRF, REQUEST)
    cookie = login(service)
    assert service.session(cookie, CSRF, REQUEST)["unverified_factors"] == [str(BACKUP)]
    service.remove(cookie, BACKUP, CSRF, REQUEST)
    assert [f["id"] for f in stub.factors] == [str(FACTOR)]
    assert service.backup(login(service), CSRF, REQUEST)[1]["status"] == "backup_code_required"


def test_admin_revocation_preserves_identity_marker_and_preferences(browser, database):
    service, _, admin = browser
    cookie = login(service)
    url, project = database
    revoke_owner(url("bootstrap"), project, ISSUER, SUBJECT)
    assert service.store.lookup(ISSUER, SUBJECT).mfa_enrolled
    with pytest.raises(AuthenticationDenied):
        service.session(cookie, CSRF, REQUEST)
    assert sql(admin, "SELECT count(*) FROM app.owner_identities")[0][0] == 1


def test_wrong_mfa_consumes_pending_attempt_and_never_creates_active_session(browser):
    service, _, admin = browser
    pending, _ = service.start(EMAIL, PASSWORD, CSRF, REQUEST)
    with pytest.raises(AuthenticationDenied):
        service.mfa(pending, FACTOR, SecretStr("000000"), CSRF, REQUEST)
    with pytest.raises(AuthenticationDenied):
        service.mfa(pending, FACTOR, SecretStr("123456"), CSRF, REQUEST)
    assert sql(admin, "SELECT count(*) FROM app.auth_sessions")[0][0] == 0


def test_session_cannot_change_owner_by_relabeling_encrypted_record(browser, database):
    service, _, admin = browser
    cookie = login(service)
    url, project = database
    other_subject = uuid4()
    provision_owner(url("bootstrap"), project, ISSUER, other_subject)
    other = service.store.lookup(ISSUER, other_subject)
    sql(
        admin,
        "UPDATE app.auth_sessions SET owner_id=:owner, subject=:subject",
        owner=other.owner_id,
        subject=str(other_subject),
    )
    with pytest.raises(AuthenticationDenied):
        service.session(cookie, CSRF, REQUEST)


@pytest.mark.parametrize("status", [400, 404, 429, 503])
def test_recovery_request_is_generic_but_reports_throttling_and_outages(browser, status):
    service, stub, _ = browser
    stub.overrides["/recover"] = httpx.Response(status)
    if status in (400, 404):
        assert service.recovery_request(EMAIL, REQUEST) is None
    else:
        with pytest.raises(AuthenticationLimited if status == 429 else AuthenticationUnavailable):
            service.recovery_request(EMAIL, REQUEST)


def test_unavailable_session_registry_never_falls_back_to_provider_identity(browser):
    service, stub, admin = browser
    cookie = login(service)
    sql(admin, "REVOKE SELECT ON app.auth_sessions FROM trading_auth")
    try:
        with pytest.raises(AuthenticationUnavailable):
            service.session(cookie, CSRF, REQUEST)
        assert stub.renewals == 0
    finally:
        sql(admin, "GRANT SELECT ON app.auth_sessions TO trading_auth")
