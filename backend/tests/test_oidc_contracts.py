import base64
import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from pydantic import SecretStr

from trading_auth.models import AuthenticationDenied, AuthenticationUnavailable
from trading_oidc.authorization import authorization_url, create_attempt
from trading_oidc.callback import ParsedCallback, check_callback_binding, parse_callback
from trading_oidc.contracts import IdentityAnchor, LoginAttempt, OidcClient


@pytest.fixture
def client():
    return OidcClient(
        issuer="https://identity.example.test",
        client_id="trading-personal",
        authorization_endpoint="https://identity.example.test/api/oidc/authorization",
        token_endpoint="https://identity.example.test/api/oidc/token",
        jwks_uri="https://identity.example.test/jwks.json",
        redirect_uri="https://trading.example.test/api/v1/auth/oidc/callback",
    )


@pytest.fixture
def attempt(client):
    return LoginAttempt(
        client=client,
        state=SecretStr("s" * 43),
        nonce=SecretStr("n" * 43),
        pkce_verifier=SecretStr("v" * 43),
        browser_binding=SecretStr("b" * 43),
        admitted_at=1_800_000_000,
        expires_at=1_800_000_300,
        max_age=300,
    )


def query(attempt, **changes):
    values = {
        "state": attempt.state.get_secret_value(),
        "iss": attempt.client.issuer,
        "code": "private-authorization-code",
    } | changes
    return urlencode(values).encode("ascii")


def test_authorization_request_is_fixed_bounded_code_flow(attempt):
    prepared = authorization_url(attempt, attempt.admitted_at).get_secret_value()
    url = urlsplit(prepared)
    assert url.scheme == "https" and url.netloc == "identity.example.test"
    assert url.path == "/api/oidc/authorization" and not url.fragment
    params = parse_qs(url.query)
    assert set(params) == {
        "client_id",
        "redirect_uri",
        "response_type",
        "response_mode",
        "scope",
        "state",
        "nonce",
        "code_challenge",
        "code_challenge_method",
        "max_age",
        "claims",
    }
    assert all(len(values) == 1 for values in params.values())
    assert params["response_type"] == ["code"]
    assert params["response_mode"] == ["query"]
    assert params["scope"] == ["openid"]
    assert params["client_id"] == [attempt.client.client_id]
    assert params["redirect_uri"] == [attempt.client.redirect_uri]
    assert params["state"] == [attempt.state.get_secret_value()]
    assert params["nonce"] == [attempt.nonce.get_secret_value()]
    assert params["max_age"] == ["300"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] == [
        base64.urlsafe_b64encode(
            hashlib.sha256(attempt.pkce_verifier.get_secret_value().encode()).digest()
        )
        .rstrip(b"=")
        .decode()
    ]
    assert json.loads(params["claims"][0]) == {
        "id_token": {"amr": {"essential": True}, "auth_time": {"essential": True}}
    }
    assert attempt.pkce_verifier.get_secret_value() not in prepared
    assert attempt.browser_binding.get_secret_value() not in prepared
    assert parse_qs(
        urlsplit(
            authorization_url(replace(attempt, max_age=0), attempt.admitted_at).get_secret_value()
        ).query
    )["max_age"] == ["0"]


def test_pkce_matches_rfc7636_appendix_b(attempt):
    sample = replace(
        attempt, pkce_verifier=SecretStr("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
    )
    params = parse_qs(
        urlsplit(authorization_url(sample, sample.admitted_at).get_secret_value()).query
    )
    assert params["code_challenge"] == ["E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"]


def test_random_attempts_have_independent_secrets_and_fixed_deadline(client):
    first = create_attempt(client, 1000)
    second = create_attempt(client, 1000)
    private = [
        value.get_secret_value()
        for item in (first, second)
        for value in (item.state, item.nonce, item.pkce_verifier, item.browser_binding)
    ]
    assert len(set(private)) == 8 and all(len(value) == 43 for value in private)
    assert first.version == 1 and first.expires_at == 1300 and first.max_age == 300
    with pytest.raises(FrozenInstanceError):
        first.expires_at = 1600


@pytest.mark.parametrize("value", [True, "1000", 1000.0, -1, 253402300500])
def test_create_attempt_rejects_invalid_admission(client, value):
    with pytest.raises(AuthenticationDenied):
        create_attempt(client, value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("issuer", "http://identity.example.test"),
        ("issuer", "https://user@identity.example.test"),
        ("issuer", "https://identity.example.test?x=y"),
        ("issuer", "https://identity.example.test#fragment"),
        ("issuer", "https://identity.example.test/%2e%2e"),
        ("issuer", "https://identity.example.test/../other"),
        ("issuer", "https://identity.example.test/./other"),
        ("issuer", "https://identity.example.test//other"),
        ("issuer", "https://Identity.example.test"),
        ("issuer", "HTTPS://identity.example.test"),
        ("issuer", " https://identity.example.test"),
        ("issuer", "https://identity.example.test\n"),
        ("issuer", "https://identity.example.test\\@evil.test"),
        ("issuer", "https://identity..example.test"),
        ("issuer", "https://identity.example.test."),
        ("issuer", "https://-identity.example.test"),
        ("issuer", "https://identity.example.test:"),
        ("issuer", "https://identity.example.test:0"),
        ("issuer", "https://identity.example.test:65536"),
        ("issuer", "https://identity.example.test:0443"),
        ("issuer", "https://[::1]"),
        ("issuer", "https://127.1"),
        ("issuer", "https://2130706433"),
        ("issuer", "https://127.000.0.1"),
        ("issuer", "https://999.0.0.1"),
        ("issuer", "https://\u0430.example.test"),
        ("issuer", None),
        ("client_id", ""),
        ("client_id", "has space"),
        ("client_id", "x" * 257),
        ("client_id", 7),
        ("authorization_endpoint", "https://evil.test/api/oidc/authorization"),
        ("token_endpoint", "https://identity.example.test/api/oidc/token?redirect=evil"),
        ("token_endpoint", "https://identity.example.test/api/oidc/authorization"),
        ("jwks_uri", "https://identity.example.test"),
        ("redirect_uri", "http://127.0.0.1/callback"),
        ("redirect_uri", "https://trading.example.test"),
        ("redirect_uri", "https://trading.example.test/callback?return_to=evil"),
    ],
)
def test_unsafe_configuration_fails_without_input_in_errors(client, field, value):
    with pytest.raises(AuthenticationUnavailable) as error:
        replace(client, **{field: value})
    assert str(error.value) == "Authentication is temporarily unavailable."


def test_exact_https_issuer_and_callback_are_preserved(client):
    changed = replace(
        client,
        issuer=client.issuer + "/issuer/",
        redirect_uri=("https://127.0.0.1:8443/api/v1/auth/oidc/callback"),
    )
    assert changed.issuer.endswith("/issuer/")
    assert changed.redirect_uri.startswith("https://127.0.0.1:8443/")


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", 2),
        ("version", True),
        ("version", "1"),
        ("admitted_at", True),
        ("admitted_at", -1),
        ("admitted_at", 1.0),
        ("expires_at", 1_800_000_299),
        ("expires_at", 1_800_000_301),
        ("expires_at", True),
        ("max_age", -1),
        ("max_age", 301),
        ("max_age", True),
        ("max_age", "300"),
        ("client", None),
        ("state", "s" * 43),
        ("state", SecretStr("s" * 42)),
        ("nonce", SecretStr("s" * 43)),
        ("pkce_verifier", SecretStr("v" * 44)),
        ("browser_binding", SecretStr("\u00e9" * 43)),
    ],
)
def test_invalid_attempt_state_fails_closed(attempt, field, value):
    with pytest.raises(AuthenticationDenied):
        replace(attempt, **{field: value})


@pytest.mark.parametrize("offset", [-1, 300, 301])
def test_attempt_is_not_valid_before_admission_or_at_expiry(attempt, offset):
    with pytest.raises(AuthenticationDenied):
        authorization_url(attempt, attempt.admitted_at + offset)


@pytest.mark.parametrize("now", [True, "1800000001", 1800000001.0, None])
def test_clock_inputs_are_strict(attempt, now):
    with pytest.raises(AuthenticationDenied):
        attempt.require_live(now)


def test_callback_success_only_parses_and_correlates(attempt):
    callback = parse_callback(query(attempt))
    assert callback.code.get_secret_value() == "private-authorization-code"
    assert callback.issuer == attempt.client.issuer
    # Pure checks are intentionally repeatable; durable atomic claiming belongs
    # to the later store and this helper cannot provide replay protection.
    for now in (attempt.admitted_at, attempt.expires_at - 1):
        assert check_callback_binding(attempt, callback, attempt.browser_binding, now) is None


def test_callback_denial_does_not_retain_provider_error_content(attempt):
    raw = urlencode(
        {
            "state": attempt.state.get_secret_value(),
            "iss": attempt.client.issuer,
            "error": "access_denied",
            "error_description": "private provider details",
            "error_uri": "https://do-not-follow.example.test/private",
        }
    ).encode()
    callback = parse_callback(raw)
    assert callback.code is None
    assert vars(callback).keys() == {"state", "issuer", "code"}
    check_callback_binding(attempt, callback, attempt.browser_binding, attempt.admitted_at)


@pytest.mark.parametrize(
    "tail",
    [
        b"&state=other",
        b"&%73tate=other",
        b"&code=other",
        b"&iss=other",
        b"&unknown=value",
        b"&error=access_denied",
        b"&error_description=details",
        b"&error_uri=https%3A%2F%2Fevil.test",
        b"&",
        b"&invalid",
        b"&x=%",
        b"&x=%0Z",
        b"&x=%FF",
        b"&x=\xff",
        b"&x=1&y=2&z=3&extra=4",
    ],
)
def test_callback_rejects_ambiguous_and_unsupported_query(attempt, tail):
    with pytest.raises(AuthenticationDenied):
        parse_callback(query(attempt) + tail)


@pytest.mark.parametrize(
    "values",
    [
        {"state": ""},
        {"state": "s" * 44},
        {"state": "\u00e9" * 43},
        {"code": ""},
        {"code": "a b"},
        {"code": "x" * 2049},
        {"code": "\r\n"},
        {"code": "\u00e9"},
        {"iss": "http://identity.example.test"},
        {"iss": ""},
    ],
)
def test_callback_values_are_bounded(attempt, values):
    with pytest.raises(AuthenticationDenied):
        parse_callback(query(attempt, **values))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"x" * 8193,
        "state=s",
        bytearray(b"state=s"),
        None,
        b"state=x&code=y",
        b"state=x&iss=https://id.test",
    ],
)
def test_callback_requires_exact_profile_and_raw_bytes(raw):
    with pytest.raises(AuthenticationDenied):
        parse_callback(raw)


@pytest.mark.parametrize("error", ["", "access denied", "access_denied\n", "x" * 65])
def test_invalid_provider_denials_fail(attempt, error):
    with pytest.raises(AuthenticationDenied):
        parse_callback(
            urlencode(
                {
                    "state": attempt.state.get_secret_value(),
                    "iss": attempt.client.issuer,
                    "error": error,
                }
            ).encode()
        )


@pytest.mark.parametrize("change", ["state", "browser", "issuer", "expired", "type"])
def test_wrong_attempt_binding_fails(attempt, change):
    callback = parse_callback(
        query(
            attempt,
            **(
                {"state": "t" * 43}
                if change == "state"
                else {"iss": "https://other.test"}
                if change == "issuer"
                else {}
            ),
        )
    )
    binding = SecretStr("x" * 43) if change == "browser" else attempt.browser_binding
    now = attempt.expires_at if change == "expired" else attempt.admitted_at
    with pytest.raises(AuthenticationDenied):
        check_callback_binding(None if change == "type" else attempt, callback, binding, now)


def test_identity_anchor_preserves_opaque_case_and_is_not_uuid_or_owner(client):
    identity = IdentityAnchor(client.issuer, "Opaque.subject_Not-a-UUID")
    assert identity.subject == "Opaque.subject_Not-a-UUID"
    assert identity != IdentityAnchor(client.issuer, identity.subject.lower())
    assert vars(identity).keys() == {"issuer", "subject"}
    assert IdentityAnchor(client.issuer + "/", identity.subject) != identity


@pytest.mark.parametrize(
    "subject", ["", " subject", "subject ", "\t", "\u00e9", "a" * 256, None, 1, True]
)
def test_unsupported_identity_anchors_are_not_normalized(client, subject):
    with pytest.raises(AuthenticationDenied):
        IdentityAnchor(client.issuer, subject)


def test_private_values_do_not_leak_in_representations(attempt):
    callback = parse_callback(query(attempt))
    identity = IdentityAnchor(attempt.client.issuer, "private-subject")
    prepared = authorization_url(attempt, attempt.admitted_at)
    rendered = " ".join(
        repr(value) + str(value)
        for value in (attempt, attempt.client, callback, identity, prepared)
    )
    for value in (
        attempt.state,
        attempt.nonce,
        attempt.pkce_verifier,
        attempt.browser_binding,
        callback.code,
    ):
        assert value.get_secret_value() not in rendered
    assert "private-subject" not in rendered
    assert attempt.client.issuer not in rendered


def test_direct_callback_construction_enforces_bounds(attempt):
    with pytest.raises(AuthenticationDenied):
        ParsedCallback(attempt.state, attempt.client.issuer, "plain-code")
