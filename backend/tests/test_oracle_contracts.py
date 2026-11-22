from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError

from trading_oracle.contracts import (
    IdentityKey,
    LocalTarget,
    OracleOwnerDenied,
    OracleUnavailable,
    RoleSecrets,
    exact_uuid,
    new_role_secrets,
    owner_bytes,
)
from trading_oracle.metadata import integer
from trading_oracle.schema import normalize_sql
from trading_oracle.workspace import snapshot


@pytest.mark.parametrize("port", [True, "1521", 0, 1023, 65536, 1521.0])
def test_target_rejects_nonexact_or_unbounded_port(port):
    with pytest.raises(ValidationError):
        LocalTarget(run_id="a" * 32, port=port)


@pytest.mark.parametrize("extra", [{"dsn": "example/FREEPDB1"}, {"host": "::1"}, {"version": True}])
def test_target_cannot_supply_an_endpoint_or_coerce_version(extra):
    with pytest.raises(ValidationError):
        LocalTarget.model_validate({"run_id": "a" * 32, "port": 1521, **extra})


@pytest.mark.parametrize("text", ["", " a", "a ", "a\x00b", "a\u200bb", "\ud800"])
def test_identity_rejects_empty_control_surrogate_or_edge_space(text):
    with pytest.raises(ValidationError):
        IdentityKey(issuer="https://issuer.example", subject=text)


def test_identity_preserves_exact_case_slash_and_unicode_bytes():
    first = IdentityKey(issuer="https://issuer.example/", subject="Éclair")
    second = IdentityKey(issuer="https://issuer.example", subject="E\u0301clair")
    assert first.issuer.endswith("/")
    assert first.subject.encode() != second.subject.encode()
    assert first != second
    assert "Éclair" not in repr(first)


@pytest.mark.parametrize("field,limit", [("issuer", 512), ("subject", 256)])
def test_identity_limits_encoded_bytes(field, limit):
    values = {"issuer": "https://issuer.example", "subject": "subject"}
    values[field] = "é" * (limit // 2)
    IdentityKey.model_validate(values)
    values[field] += "x"
    with pytest.raises(ValidationError):
        IdentityKey.model_validate(values)


def test_generated_role_secrets_are_separate_bounded_and_redacted():
    secrets = new_role_secrets()
    values = [
        secrets.for_role(role).get_secret_value()
        for role in ("TRADING_MIGRATOR", "TRADING_RUNTIME", "TRADING_AUTH")
    ]
    assert len(set(values)) == 3
    assert all(len(value) == 51 and value not in repr(secrets) for value in values)
    with pytest.raises(ValidationError):
        RoleSecrets(
            migrator=SecretStr('Ta1";GRANT DBA'), runtime=secrets.runtime, auth=secrets.auth
        )


@pytest.mark.parametrize("owner", [UUID(int=0), "11111111-1111-1111-1111-111111111111", None])
def test_owner_requires_a_nonzero_uuid_instance(owner):
    with pytest.raises(OracleOwnerDenied):
        owner_bytes(owner)


@pytest.mark.parametrize("value", [b"", b"x" * 15, b"x" * 17, b"\0" * 16, bytearray(b"x" * 16)])
def test_database_uuid_requires_exact_raw_bytes(value):
    with pytest.raises(OracleUnavailable):
        exact_uuid(value)


@pytest.mark.parametrize("value", [True, 1.0, "1", Decimal("1.1"), Decimal("NaN"), 2**53])
def test_integer_never_coerces_inexact_or_unsafe_values(value):
    with pytest.raises(OracleUnavailable):
        integer(value)


def test_safe_integer_and_snapshot_conversion():
    assert integer(Decimal("9007199254740991")) == 9007199254740991
    assert snapshot(("dark", "USD", Decimal(1), Decimal(7))).model_dump() == {
        "theme": "dark",
        "display_currency": "USD",
        "amount_masked": True,
        "revision": 7,
    }


@pytest.mark.parametrize(
    "value",
    [
        ("dark", "USD", 2, 1),
        ("dark", "USD", 1, 0),
        ("dark", "USD", True, 1),
        ("dark", "USD", 1, 2**53),
        ("dark", "USD", 1),
    ],
)
def test_snapshot_rejects_invalid_database_values(value):
    with pytest.raises(OracleUnavailable):
        snapshot(value)


def test_sql_normalization_preserves_literal_semantics():
    assert normalize_sql("\"THEME\" IN ('light','dark')") == normalize_sql(
        "theme IN ('light','dark')"
    )
    assert normalize_sql("x='LIGHT'") != normalize_sql("x='light'")
    assert normalize_sql("x='a  b'") != normalize_sql("x='a b'")
    assert normalize_sql("x='a''b'") != normalize_sql("x='ab'")
