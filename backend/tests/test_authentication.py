import asyncio
import io
import time
from dataclasses import replace
from unittest.mock import patch

import httpx2 as httpx
import pytest
from auth_support import FACTOR, ISSUER, OWNER, PASSWORD, SETUP, SUBJECT, IdentityStub, SupabaseStub
from pydantic import SecretStr

from trading_auth import __main__ as cli
from trading_auth.models import (
    AuthenticationDenied,
    AuthenticationLimited,
    AuthenticationUnavailable,
)
from trading_auth.service import AttemptLimiter, Authenticator


@pytest.fixture
def auth():
    upstream, identities = SupabaseStub(), IdentityStub()
    provider = upstream.provider()
    service = Authenticator(provider, identities)
    try:
        yield service, upstream, identities
    finally:
        provider.close()


def test_password_requires_mfa_and_verified_result_uses_mapping_not_email(auth):
    service, upstream, identities = auth
    with service.begin("owner@example.invalid", PASSWORD) as attempt:
        assert not hasattr(attempt, "owner_id")
        assert attempt.prepare_mfa() is None
        result = attempt.verify_mfa(SecretStr("123456"))
        assert result.owner_id == OWNER and result.identity.aal == "aal2"
        assert not hasattr(result, "access") and not hasattr(result, "refresh")
        assert str(OWNER) not in repr(result)
        with pytest.raises(AuthenticationDenied):
            attempt.verify_mfa(SecretStr("123456"))
    assert upstream.discarded == 1
    assert identities.binding.mfa_enrolled
    assert set(identities.calls) == {(ISSUER, SUBJECT)}
    with pytest.raises(AuthenticationDenied):
        attempt.prepare_mfa()


def test_first_totp_enrollment_returns_only_redacted_secret_once(auth):
    service, upstream, identities = auth
    upstream.factors = []
    with service.begin("owner@example.invalid", PASSWORD) as attempt:
        enrollment = attempt.prepare_mfa()
        assert enrollment.secret.get_secret_value() == SETUP
        assert SETUP not in repr(enrollment)
        assert not hasattr(enrollment, "qr_code") and not hasattr(enrollment, "uri")
        assert identities.binding.mfa_enrolled is False
        with pytest.raises(AuthenticationDenied):
            attempt.prepare_mfa()
        assert attempt.verify_mfa(SecretStr("123456")).owner_id == OWNER
    assert identities.binding.mfa_enrolled is True


@pytest.mark.parametrize(
    "marker,factors",
    [
        (True, []),
        (False, [dict(id=str(FACTOR), factor_type="totp", status="unverified")]),
        (False, [dict(id=str(FACTOR), factor_type="phone", status="verified")]),
    ],
)
def test_missing_or_abandoned_factors_never_become_automatic_recovery(auth, marker, factors):
    service, upstream, identities = auth
    upstream.factors = factors
    identities.binding = replace(identities.binding, mfa_enrolled=marker)
    with service.begin("owner@example.invalid", PASSWORD) as attempt:
        with pytest.raises(AuthenticationDenied):
            attempt.prepare_mfa()
    assert not any(request.url.path.endswith("/factors") for request in upstream.requests)


def test_unknown_or_disabled_owner_cannot_enroll_or_complete(auth):
    service, upstream, identities = auth
    identities.binding = None
    with pytest.raises(AuthenticationDenied):
        with service.begin("owner@example.invalid", PASSWORD):
            pytest.fail("Unknown identity accepted")
    assert upstream.discarded == 1
    assert not any("/factors" in request.url.path for request in upstream.requests)


def test_deactivation_during_attempt_denies_factor_operations(auth):
    service, upstream, identities = auth
    with service.begin("owner@example.invalid", PASSWORD) as attempt:
        attempt.prepare_mfa()
        identities.binding = None
        with pytest.raises(AuthenticationDenied):
            attempt.verify_mfa(SecretStr("123456"))
    assert not any(request.url.path.endswith("/verify") for request in upstream.requests)


def test_wrong_code_and_five_attempt_limit(auth):
    service, upstream, _ = auth
    with service.begin("owner@example.invalid", PASSWORD) as attempt:
        attempt.prepare_mfa()
        for _ in range(5):
            with pytest.raises(AuthenticationDenied):
                attempt.verify_mfa(SecretStr("000000"))
        count = len(upstream.requests)
        with pytest.raises(AuthenticationDenied):
            attempt.verify_mfa(SecretStr("123456"))
        assert len(upstream.requests) == count


@pytest.mark.parametrize("code", ["", "12345", "1234567", "１２３４５６", "123 45", "<code>"])
def test_invalid_code_never_reaches_provider(auth, code):
    service, upstream, _ = auth
    with service.begin("owner@example.invalid", PASSWORD) as attempt:
        attempt.prepare_mfa()
        count = len(upstream.requests)
        with pytest.raises(AuthenticationDenied):
            attempt.verify_mfa(SecretStr(code))
        assert len(upstream.requests) == count


def test_factor_not_bound_to_attempt_is_denied(auth):
    service, upstream, _ = auth
    with service.begin("owner@example.invalid", PASSWORD) as attempt:
        with pytest.raises(AuthenticationDenied):
            attempt.verify_mfa(SecretStr("123456"))
        attempt.prepare_mfa()
        upstream.factors = []
        with pytest.raises(AuthenticationDenied):
            attempt.verify_mfa(SecretStr("123456"))


def test_expiry_and_cancellation_release_capacity_and_tokens(auth):
    service, upstream, _ = auth
    clock = [10.0]
    service._clock = lambda: clock[0]
    with service.begin("owner@example.invalid", PASSWORD) as attempt:
        attempt.prepare_mfa()
        clock[0] = 310.0
        with pytest.raises(AuthenticationDenied):
            attempt.verify_mfa(SecretStr("123456"))
    with pytest.raises(asyncio.CancelledError):
        with service.begin("owner@example.invalid", PASSWORD):
            raise asyncio.CancelledError()
    assert upstream.discarded == 2
    assert not service._owners


def test_same_owner_cannot_start_parallel_attempt(auth):
    service, upstream, _ = auth
    with service.begin("owner@example.invalid", PASSWORD):
        with pytest.raises(AuthenticationLimited):
            with service.begin("alias@example.invalid", PASSWORD):
                pytest.fail("Parallel attempt accepted")
    assert upstream.discarded == 2


def test_attempt_operation_cannot_run_concurrently(auth):
    service, _, _ = auth
    with service.begin("owner@example.invalid", PASSWORD) as attempt:
        with attempt._lock:
            with pytest.raises(AuthenticationLimited):
                attempt.prepare_mfa()


def test_rate_limit_includes_failed_passwords_and_case_variants(auth):
    service, upstream, _ = auth
    upstream.overrides["/token"] = httpx.Response(400, json={"msg": "synthetic-private-detail"})
    for _ in range(5):
        with pytest.raises(AuthenticationDenied):
            with service.begin("owner@example.invalid", PASSWORD):
                pass
    count = len(upstream.requests)
    with pytest.raises(AuthenticationLimited):
        with service.begin("OWNER@example.invalid", PASSWORD):
            pass
    assert len(upstream.requests) == count


def test_global_rate_limit_is_bounded_and_expires():
    clock = [0.0]
    limiter = AttemptLimiter(lambda: clock[0])
    for n in range(30):
        limiter.take(f"synthetic-{n}@example.invalid")
    for n in range(1000):
        with pytest.raises(AuthenticationLimited):
            limiter.take(f"blocked-{n}@example.invalid")
    assert len(limiter._buckets) <= 32
    assert "example.invalid" not in repr(limiter._buckets)
    clock[0] = 300.0
    limiter.take("new@example.invalid")
    assert len(limiter._buckets) == 2


def test_provider_timeout_and_cleanup_failure_never_restore_attempt(auth):
    service, upstream, _ = auth
    with pytest.raises(AuthenticationUnavailable) as error:
        with service.begin("owner@example.invalid", PASSWORD) as attempt:
            upstream.overrides["/logout"] = httpx.Response(503, text="synthetic-secret")
    assert "synthetic-secret" not in str(error.value)
    assert attempt._tokens is None
    assert not service._owners


def test_slow_provider_cannot_complete_after_attempt_expiry(auth):
    service, upstream, _ = auth
    clock = [0.0]
    service._clock = lambda: clock[0]
    original = service._provider.verify

    def delayed(*args):
        result = original(*args)
        clock[0] = 301.0
        return result

    with service.begin("owner@example.invalid", PASSWORD) as attempt:
        attempt.prepare_mfa()
        with patch.object(service._provider, "verify", side_effect=delayed):
            with pytest.raises(AuthenticationDenied):
                attempt.verify_mfa(SecretStr("123456"))
    assert upstream.discarded == 1


def test_wrong_mfa_assurance_denies_completion(auth):
    service, upstream, identities = auth
    with service.begin("owner@example.invalid", PASSWORD) as attempt:
        attempt.prepare_mfa()
        upstream.claim_changes["aal"] = "aal1"
        with pytest.raises(AuthenticationDenied):
            attempt.verify_mfa(SecretStr("123456"))
    assert not identities.binding.mfa_enrolled


def test_cli_refuses_redirected_terminal_before_secrets_or_network(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["trading_auth", "smoke"])
    with (
        patch.object(sys_stdin := io.StringIO(), "isatty", return_value=False),
        patch("sys.stdin", sys_stdin),
        patch("trading_auth.__main__.load_settings") as config,
        patch("trading_auth.__main__.configure_logging"),
    ):
        assert cli.main() == 1
    config.assert_not_called()
    assert "Authentication operation failed" in capsys.readouterr().err


def test_structured_logs_never_echo_auth_secrets():
    import logging

    from trading_api.logging import SafeFormatter

    for value in (PASSWORD.get_secret_value(), SETUP, "123456", "synthetic-refresh-token-value"):
        record = logging.LogRecord("httpx", logging.ERROR, "", 0, value, (), None)
        assert value not in SafeFormatter().format(record)


def test_expired_provider_token_is_rejected_before_next_operation(auth):
    service, _, _ = auth
    with service.begin("owner@example.invalid", PASSWORD) as attempt:
        attempt._tokens = replace(
            attempt._tokens,
            identity=replace(attempt._tokens.identity, expires_at=int(time.time()) - 1),
        )
        with pytest.raises(AuthenticationDenied):
            attempt.prepare_mfa()


def test_deactivation_after_totp_verification_cannot_produce_completed_owner(auth):
    service, _, identities = auth
    original = service._provider.verify

    def deactivate(*args):
        result = original(*args)
        identities.binding = None
        return result

    with service.begin("owner@example.invalid", PASSWORD) as attempt:
        attempt.prepare_mfa()
        with patch.object(service._provider, "verify", side_effect=deactivate):
            with pytest.raises(AuthenticationDenied):
                attempt.verify_mfa(SecretStr("123456"))


def test_full_capacity_denies_before_password_provider_request(auth):
    service, upstream, _ = auth
    for _ in range(4):
        assert service._capacity.acquire(blocking=False)
    try:
        with pytest.raises(AuthenticationLimited):
            with service.begin("owner@example.invalid", PASSWORD):
                pass
        assert upstream.requests == []
    finally:
        for _ in range(4):
            service._capacity.release()


@pytest.mark.parametrize("case", ["subject", "session", "missing_totp", "stale_totp"])
def test_mfa_result_cannot_switch_identity_or_omit_fresh_factor_proof(auth, case):
    service, upstream, identities = auth
    with service.begin("owner@example.invalid", PASSWORD) as attempt:
        attempt.prepare_mfa()
        if case == "subject":
            upstream.claim_changes["sub"] = "20000000-0000-4000-8000-000000000099"
        elif case == "session":
            upstream.claim_changes["session_id"] = "30000000-0000-4000-8000-000000000099"
        else:
            methods = [{"method": "password", "timestamp": int(time.time())}]
            if case == "stale_totp":
                methods.append({"method": "totp", "timestamp": int(time.time()) - 301})
            upstream.claim_changes["amr"] = methods
        with pytest.raises(AuthenticationDenied):
            attempt.verify_mfa(SecretStr("123456"))
    assert not identities.binding.mfa_enrolled
