"""Encrypted market archives reject coercible source positions before SQL is reachable."""

import json
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import URL

from tests.test_market_occurrences import SCOPES
from tests.test_market_occurrences import payload as market_payload
from tests.test_recovery import payload
from trading_db import recovery
from trading_db.connections import DatabaseFailure
from trading_db.market_contracts import MarketDefinition


def observation(**changes):
    value = MarketDefinition.model_validate(market_payload(contract_version=2, occurrence=25000))
    return (
        dict(
            owner_id=str(uuid4()),
            id=str(uuid4()),
            **value.model_dump(mode="json"),
            amount=value.source,
            created_at="2026-10-28T00:00:00+00:00",
        )
        | changes
    )


def encrypted_rows(rows, key):
    data = payload()
    data["rows"]["market_observations"] = rows
    return Fernet(key).encrypt(json.dumps(data).encode())


@pytest.mark.parametrize("kind,namespace", SCOPES)
@pytest.mark.parametrize("occurrence", [1, 1000])
def test_decoder_preserves_legacy_scope_and_exact_integer_positions(kind, namespace, occurrence):
    key = Fernet.generate_key()
    row = observation(kind=kind, namespace=namespace, contract_version=1, occurrence=occurrence)
    # Full target/FK consistency remains a SQL responsibility; this checks the
    # narrow decoder domain without widening the archive's primitive contract.
    rows = recovery.decode_snapshot(encrypted_rows([row], key), key)
    assert rows["market_observations"] == [row]
    assert type(rows["market_observations"][0]["occurrence"]) is int


@pytest.mark.parametrize("occurrence", [1, 1000, 1001, 25000])
def test_decoder_preserves_explicit_nav_v2_without_renumbering(occurrence):
    key = Fernet.generate_key()
    row = observation(occurrence=occurrence)
    rows = recovery.decode_snapshot(encrypted_rows([row], key), key)
    assert rows["market_observations"] == [row]
    assert type(rows["market_observations"][0]["contract_version"]) is int


BAD_POSITIONS = (
    [{"contract_version": value} for value in (True, False, "1", "2", 1.0, 2.0, None, 0, -1, 3)]
    + [
        {"occurrence": value}
        for value in (True, False, "1", "1000", "25000", 1.0, 25000.0, None, 0, -1, 25001)
    ]
    + [
        {"contract_version": 1, "occurrence": 1001},
        {"contract_version": 1, "occurrence": 25000},
        {"namespace": "manual_evidence", "occurrence": 1},
        {"kind": "quote", "namespace": "exchange_quote_report", "occurrence": 1},
        {"kind": "fx", "namespace": "fx_rate_report", "occurrence": 1},
        {"kind": "quote", "namespace": "amfi_nav_report", "contract_version": 1, "occurrence": 1},
    ]
    + [{field: value} for field in ("kind", "namespace") for value in (True, 1, None, "unknown")]
)


@pytest.mark.parametrize("changes", BAD_POSITIONS)
def test_bad_archive_position_fails_before_references_destination_or_engine(monkeypatch, changes):
    def unexpected(*args, **kwargs):
        pytest.fail("Malformed market archive reached restore infrastructure")

    for name in ("verify_references", "target", "engine_for"):
        monkeypatch.setattr(recovery, name, unexpected)
    key = Fernet.generate_key()
    encrypted = encrypted_rows([observation(), observation(**changes)], key)
    with pytest.raises(DatabaseFailure) as caught:
        recovery.restore_snapshot(URL.create("postgresql+psycopg"), "unused", encrypted, key)
    assert str(caught.value) == "Recovery object is invalid or incompatible."
    assert caught.value.__cause__ is None


def test_position_cap_does_not_change_archive_row_or_byte_budgets():
    assert recovery.MAX_ROWS == 1000 and recovery.LIMIT == 4_000_000
    key = Fernet.generate_key()
    with pytest.raises(DatabaseFailure, match="invalid or incompatible"):
        recovery.decode_snapshot(encrypted_rows([observation()] * 1001, key), key)
