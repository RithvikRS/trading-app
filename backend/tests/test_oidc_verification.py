import base64
import json
from dataclasses import FrozenInstanceError, replace

import pytest
from authlib.oidc.core.util import create_half_hash
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from joserfc import jwt
from joserfc.jwk import RSAKey
from pydantic import SecretStr

from trading_auth.models import AuthenticationDenied, AuthenticationUnavailable
from trading_oidc.authorization import create_attempt
from trading_oidc.contracts import OidcClient
from trading_oidc.verification import VerifiedTokenEvidence, verify_id_token

NOW = 1_800_000_100


def encoded(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def document(value):
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def public(private, kid="key-1"):
    return RSAKey.import_key(private.public_key()).as_dict() | {
        "kid": kid,
        "alg": "RS256",
        "use": "sig",
        "key_ops": ["verify"],
    }


def raw_token(private, header, payload):
    # Independent test signing also permits deliberately duplicate/malformed JSON.
    body = (encoded(header) + "." + encoded(payload)).encode("ascii")
    signature = private.sign(body, padding.PKCS1v15(), hashes.SHA256())
    return SecretStr(body.decode("ascii") + "." + encoded(signature))


def token(private, claims, **header):
    return raw_token(private, document({"alg": "RS256", "kid": "key-1"} | header), document(claims))


@pytest.fixture(scope="module")
def private():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def rotated():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def attempt():
    return create_attempt(
        OidcClient(
            "https://identity.example.test",
            "trading-personal",
            "https://identity.example.test/api/oidc/authorization",
            "https://identity.example.test/api/oidc/token",
            "https://identity.example.test/jwks.json",
            "https://trading.example.test/api/v1/auth/oidc/callback",
        ),
        NOW - 100,
    )


@pytest.fixture
def claims(attempt):
    return {
        "iss": attempt.client.issuer,
        "sub": "opaque_Subject.NOT-a-UUID",
        "aud": attempt.client.client_id,
        "exp": NOW + 600,
        "iat": NOW - 10,
        "auth_time": NOW - 20,
        "nonce": attempt.nonce.get_secret_value(),
        "amr": ["pwd", "otp", "mfa"],
    }


@pytest.fixture
def jwks(private):
    return document({"keys": [public(private)]})


def test_signed_token_produces_only_verified_identity_evidence(private, claims, jwks, attempt):
    compact = jwt.encode(
        {"alg": "RS256", "kid": "key-1", "typ": "JWT"}, claims, RSAKey.import_key(private)
    )
    result = verify_id_token(SecretStr(compact), jwks, attempt, NOW)
    assert result.identity.issuer == claims["iss"] and result.identity.subject == claims["sub"]
    assert result.audience == attempt.client.client_id
    assert (result.issued_at, result.expires_at, result.authenticated_at) == (
        claims["iat"],
        claims["exp"],
        claims["auth_time"],
    )
    assert result.amr == ("pwd", "otp", "mfa")
    assert set(vars(result)) == {
        "identity",
        "audience",
        "issued_at",
        "expires_at",
        "authenticated_at",
        "amr",
    }
    with pytest.raises(FrozenInstanceError):
        result.expires_at = NOW + 9999
    with pytest.raises(TypeError):
        VerifiedTokenEvidence()
    rendered = repr(result) + str(result) + repr(result.identity)
    for value in (compact, claims["sub"], claims["iss"], claims["nonce"]):
        assert value not in rendered


@pytest.mark.parametrize("size", [3072, 4096])
def test_supported_stronger_rsa_keys(size, claims, attempt):
    private = rsa.generate_private_key(public_exponent=65537, key_size=size)
    result = verify_id_token(
        token(private, claims), document({"keys": [public(private)]}), attempt, NOW
    )
    assert result.identity.subject == claims["sub"]


def test_explicit_rotation_accepts_old_and_new_keys_without_refetch(
    private, rotated, claims, attempt
):
    old, new = public(private), public(rotated, "key-2")
    snapshot = document({"keys": [old, new]})
    for key, key_id in ((private, "key-1"), (rotated, "key-2")):
        assert verify_id_token(token(key, claims, kid=key_id), snapshot, attempt, NOW)
    with pytest.raises(AuthenticationDenied):
        verify_id_token(token(private, claims), document({"keys": [new]}), attempt, NOW)
    with pytest.raises(AuthenticationDenied):
        verify_id_token(token(rotated, claims, kid="unknown"), snapshot, attempt, NOW)
    with pytest.raises(AuthenticationDenied):
        verify_id_token(token(rotated, claims), snapshot, attempt, NOW)


@pytest.mark.parametrize(
    "header",
    [
        {"alg": "none"},
        {"alg": "HS256"},
        {"alg": "RS384"},
        {"alg": "ES256"},
        {"alg": None},
        {"kid": ""},
        {"kid": 1},
        {"kid": "x" * 129},
        {"kid": "\u00e9"},
        {"typ": "at+jwt"},
        {"typ": None},
        {"typ": ["JWT"]},
        {"jwk": {}},
        {"jku": "https://evil.test/keys"},
        {"x5u": "https://evil.test/cert"},
        {"x5c": ["fake"]},
        {"crit": ["b64"]},
        {"b64": False},
        {"zip": "DEF"},
        {"unknown": "ignored-by-many-libraries"},
    ],
)
def test_unsupported_header_cannot_choose_algorithms_or_keys(
    private, claims, jwks, attempt, header
):
    with pytest.raises(AuthenticationDenied) as error:
        verify_id_token(token(private, claims, **header), jwks, attempt, NOW)
    assert str(error.value) == "Authentication could not be completed."


@pytest.mark.parametrize("remove", ["alg", "kid"])
def test_header_required_values(private, claims, jwks, attempt, remove):
    header = {"alg": "RS256", "kid": "key-1"}
    del header[remove]
    with pytest.raises(AuthenticationDenied):
        verify_id_token(raw_token(private, document(header), document(claims)), jwks, attempt, NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("iss", "https://other.test"),
        ("iss", "https://identity.example.test/"),
        ("iss", None),
        ("sub", ""),
        ("sub", 7),
        ("sub", "with trailing "),
        ("sub", "\u00e9"),
        ("aud", "another-client"),
        ("aud", []),
        ("aud", ["trading-personal", "other"]),
        ("aud", ["trading-personal", "trading-personal"]),
        ("aud", True),
        ("azp", "other"),
        ("azp", ""),
        ("azp", None),
        ("azp", True),
        ("nonce", "n" * 43),
        ("nonce", ""),
        ("nonce", None),
        ("nonce", ["n" * 43]),
        ("exp", NOW),
        ("exp", NOW - 1),
        ("exp", NOW - 10),
        ("exp", NOW + 3591),
        ("exp", True),
        ("exp", float(NOW + 600)),
        ("exp", str(NOW + 600)),
        ("iat", NOW + 31),
        ("iat", NOW - 131),
        ("iat", True),
        ("iat", -1),
        ("auth_time", NOW - 9),
        ("auth_time", NOW - 331),
        ("auth_time", True),
        ("auth_time", float(NOW - 20)),
        ("auth_time", None),
        ("nbf", NOW + 31),
        ("nbf", NOW + 600),
        ("nbf", True),
        ("nbf", -1),
        ("amr", ["pwd", "otp"]),
        ("amr", ["mfa"]),
        ("amr", ["pwd", "hwk", "mfa"]),
        ("amr", ["pwd", "otp", "mfa", "hwk"]),
        ("amr", ["pwd", "otp", "otp"]),
        ("amr", ["PWD", "otp", "mfa"]),
        ("amr", ["pwd", {}, "mfa"]),
        ("amr", "pwd otp mfa"),
        ("amr", []),
        ("amr", None),
        ("email", "owner@example.test"),
        ("aal", "aal2"),
        ("groups", ["trading"]),
        ("at_hash", ""),
        ("at_hash", True),
        ("at_hash", "x" * 22),
    ],
)
def test_signed_but_unauthorized_claims_fail(private, claims, jwks, attempt, field, value):
    with pytest.raises(AuthenticationDenied):
        verify_id_token(token(private, claims | {field: value}), jwks, attempt, NOW)


@pytest.mark.parametrize("name", ["iss", "sub", "aud", "exp", "iat", "auth_time", "nonce", "amr"])
def test_missing_required_claims_fail(private, claims, jwks, attempt, name):
    del claims[name]
    with pytest.raises(AuthenticationDenied):
        verify_id_token(token(private, claims), jwks, attempt, NOW)


@pytest.mark.parametrize(
    "updates",
    [
        {"aud": ["trading-personal"], "azp": "trading-personal"},
        {"iat": NOW + 30, "auth_time": NOW + 30},
        {"auth_time": NOW - 330},
        {"nbf": NOW + 30},
        {"exp": NOW - 10 + 3600},
        {"amr": ["mfa", "otp", "pwd"]},
    ],
)
def test_explicit_profile_boundaries(private, claims, jwks, attempt, updates):
    assert verify_id_token(token(private, claims | updates), jwks, attempt, NOW)


def test_zero_max_age_requires_recent_authentication_not_merely_recent_token(
    private, claims, jwks, attempt
):
    attempt = replace(attempt, max_age=0)
    assert verify_id_token(token(private, claims | {"auth_time": NOW - 30}), jwks, attempt, NOW)
    with pytest.raises(AuthenticationDenied):
        verify_id_token(token(private, claims | {"auth_time": NOW - 31}), jwks, attempt, NOW)


def test_authentication_time_cannot_follow_issuance(private, claims, jwks, attempt):
    with pytest.raises(AuthenticationDenied):
        verify_id_token(
            token(private, claims | {"iat": NOW, "auth_time": NOW + 1}), jwks, attempt, NOW
        )


def test_access_token_hash_uses_maintained_oidc_validation(private, claims, jwks, attempt):
    access = SecretStr("synthetic-private-access-token")
    claims["at_hash"] = create_half_hash(access.get_secret_value(), "RS256").decode("ascii")
    signed = token(private, claims)
    assert verify_id_token(signed, jwks, attempt, NOW, access_token=access)
    for bad in (None, SecretStr("different-access-token"), "unwrapped-access", SecretStr("\r\n")):
        with pytest.raises(AuthenticationDenied):
            verify_id_token(signed, jwks, attempt, NOW, access_token=bad)
    with pytest.raises(AuthenticationDenied):
        verify_id_token(
            token(private, claims | {"at_hash": "A" * 22}), jwks, attempt, NOW, access_token=access
        )


@pytest.mark.parametrize(
    "mutation",
    [
        {"kty": "oct"},
        {"alg": "HS256"},
        {"use": "enc"},
        {"key_ops": ["sign"]},
        {"key_ops": ["verify", "sign"]},
        {"key_ops": ["verify", "verify"]},
        {"key_ops": "verify"},
        {"key_ops": []},
        {"key_ops": None},
        {"e": "Aw"},
        {"n": ""},
        {"n": "AA"},
        {"n": "AA=="},
        {"n": None},
        {"kid": ""},
        {"kid": "x" * 129},
        {"kid": True},
        {"d": "private"},
        {"p": "private"},
        {"x5u": "https://evil.test/cert"},
        {"jku": "https://evil.test/keys"},
        {"x5c": []},
        {"unknown": "value"},
    ],
)
def test_invalid_trusted_key_configuration_is_unavailable(private, claims, attempt, mutation):
    with pytest.raises(AuthenticationUnavailable) as error:
        verify_id_token(
            token(private, claims), document({"keys": [public(private) | mutation]}), attempt, NOW
        )
    assert str(error.value) == "Authentication is temporarily unavailable."


@pytest.mark.parametrize("remove", ["kty", "kid", "n", "e"])
def test_missing_jwk_parts_fail(private, claims, attempt, remove):
    key = public(private)
    del key[remove]
    with pytest.raises(AuthenticationUnavailable):
        verify_id_token(token(private, claims), document({"keys": [key]}), attempt, NOW)


def test_key_snapshot_bounds_duplicates_and_no_private_components(private, claims, attempt):
    signed = token(private, claims)
    key = public(private)
    maximum = [key | {"kid": "key-1" if i == 0 else f"key-{i + 1}"} for i in range(8)]
    assert verify_id_token(signed, document({"keys": maximum}), attempt, NOW)
    invalid = [
        b"",
        b" " * 65537,
        b"[]",
        document({"keys": []}),
        document({"keys": [key, key]}),
        document({"keys": maximum + [key | {"kid": "key-9"}]}),
        document({"keys": [key], "uri": "https://evil.test"}),
        document({"keys": [RSAKey.import_key(private).as_dict(private=True)]}),
        document(
            {
                "keys": [
                    key
                    | {
                        "n": encoded(
                            b"\0" + base64.urlsafe_b64decode(key["n"] + "=" * (-len(key["n"]) % 4))
                        )
                    }
                ]
            }
        ),
        b'{"keys":[],"keys":[]}',
        document({"keys": [key]}).replace(b'"kid":"key-1"', b'"kid":"key-1","kid":"key-1"'),
    ]
    for value in invalid:
        with pytest.raises(AuthenticationUnavailable):
            verify_id_token(signed, value, attempt, NOW)


def test_weak_rsa_is_not_imported(claims, attempt):
    private = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    numbers = private.public_key().public_numbers()
    weak = {
        "kty": "RSA",
        "kid": "key-1",
        "e": "AQAB",
        "n": encoded(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8)),
    }
    with pytest.raises(AuthenticationUnavailable):
        verify_id_token(token(private, claims), document({"keys": [weak]}), attempt, NOW)


@pytest.mark.parametrize(
    "header,payload",
    [
        (b'{"alg":"RS256","alg":"RS256","kid":"key-1"}', None),
        (b'{"alg":"RS256","kid":"key-1","kid":"key-1"}', None),
        (b"[]", None),
        (b'{"alg":"RS256","kid":"key-1","typ":NaN}', None),
        (None, b'{"iss":"one","iss":"two"}'),
        (None, b'{"iat":NaN}'),
        (None, b'{"iat":Infinity}'),
        (None, b'{"iat":-Infinity}'),
        (None, b'{"iat":1.0}'),
        (None, b"[]"),
        (None, b"\xff"),
        (None, b'{"nested":[[[[[[[[]]]]]]]]}'),
    ],
)
def test_signed_noncanonical_or_ambiguous_json_fails(
    private, claims, jwks, attempt, header, payload
):
    header = document({"alg": "RS256", "kid": "key-1"}) if header is None else header
    payload = document(claims) if payload is None else payload
    with pytest.raises(AuthenticationDenied):
        verify_id_token(raw_token(private, header, payload), jwks, attempt, NOW)


def test_token_and_json_size_bounds(private, claims, jwks, attempt):
    good = token(private, claims).get_secret_value()
    head, body, signature = good.split(".")
    for value in (
        "",
        "x" * 16385,
        good + ".extra",
        head + "=." + body + "." + signature,
        head + "." + body + ".",
        head + "." + body + ".AA",
        "\u00e9",
    ):
        with pytest.raises(AuthenticationDenied):
            verify_id_token(SecretStr(value), jwks, attempt, NOW)
    for header, payload in (
        (b" " * 2049, document(claims)),
        (document({"alg": "RS256", "kid": "key-1"}), b" " * 8193),
    ):
        with pytest.raises(AuthenticationDenied):
            verify_id_token(raw_token(private, header, payload), jwks, attempt, NOW)


@pytest.mark.parametrize("now", [True, float(NOW), str(NOW), NOW - 101, NOW + 200])
def test_strict_clock_and_live_attempt_before_crypto(private, claims, jwks, attempt, now):
    with pytest.raises(AuthenticationDenied):
        verify_id_token(token(private, claims), jwks, attempt, now)


def test_wrong_types_and_unverified_payload_never_escape(private, claims, jwks, attempt):
    for bad in ("plain-token", None, b"token"):
        with pytest.raises(AuthenticationDenied):
            verify_id_token(bad, jwks, attempt, NOW)
    with pytest.raises(AuthenticationDenied):
        verify_id_token(token(private, claims), jwks, None, NOW)
    for bad in ("jwks-text", None, bytearray(jwks)):
        with pytest.raises(AuthenticationUnavailable):
            verify_id_token(token(private, claims), bad, attempt, NOW)


def test_invalid_signature_does_not_return_identity(private, rotated, claims, jwks, attempt):
    signed = token(rotated, claims)
    with pytest.raises(AuthenticationDenied) as error:
        verify_id_token(signed, jwks, attempt, NOW)
    assert claims["sub"] not in str(error.value) + repr(error.value)
    assert signed.get_secret_value() not in str(error.value) + repr(error.value)
