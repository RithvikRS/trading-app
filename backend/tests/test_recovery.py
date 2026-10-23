"""Malformed recovery objects and unsafe destinations fail before writes."""

import json

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import URL

from trading_db import recovery
from trading_db.connections import DatabaseFailure


def payload():
    return {
        "format": recovery.FORMAT,
        "revision": recovery.HEAD,
        "postgres_major": 17,
        "migration_digest": recovery.source_digest(),
        "application_version": "0.1.0",
        "rows": {table: [] for table in recovery.COLUMNS},
    }


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(revision="older"),
        lambda value: value.update(migration_digest="different"),
        lambda value: value.update(postgres_major=16),
        lambda value: value.update(format=True),
        lambda value: value.update(format=1),
        lambda value: value.update(extra="unexpected"),
        lambda value: value["rows"].update(auth_sessions=[]),
        lambda value: value["rows"].update(owners=[{}]),
        lambda value: value["rows"].update(owners=[{}] * 1001),
        lambda value: value["rows"].update(
            owners=[dict(id=[], is_active=True, created_at="invalid")]
        ),
    ],
)
def test_incompatible_objects_cannot_restore(change):
    key = Fernet.generate_key()
    value = payload()
    change(value)
    with pytest.raises(DatabaseFailure, match="invalid or incompatible"):
        recovery.decode_snapshot(Fernet(key).encrypt(json.dumps(value).encode()), key)


def test_wrong_key_tampering_duplicate_fields_and_size_are_rejected():
    key = Fernet.generate_key()
    cipher = Fernet(key)
    valid = cipher.encrypt(json.dumps(payload()).encode())
    assert recovery.decode_snapshot(valid, key) == payload()["rows"]
    for encrypted, supplied_key in [
        (valid, Fernet.generate_key()),
        (valid[:-8] + b"tampered", key),
        (cipher.encrypt(b'{"format":1,"format":1}'), key),
        (b"x" * (recovery.LIMIT * 2 + 1), key),
        (cipher.encrypt(b"x" * (recovery.LIMIT + 1)), key),
        (cipher.encrypt(b"[]"), key),
    ]:
        with pytest.raises(DatabaseFailure):
            recovery.decode_snapshot(encrypted, supplied_key)


@pytest.mark.parametrize(
    "changes,project",
    [
        ({"database": "trading_dev"}, "trading-development"),
        ({"host": "remote.invalid"}, "trading-test-" + "a" * 16),
        ({"username": "trading_runtime"}, "trading-test-" + "a" * 16),
        ({}, "trading-development"),
    ],
)
def test_unsafe_targets_rejected_before_connect(monkeypatch, changes, project):
    def denied(*args, **kwargs):
        pytest.fail("Unsafe target attempted a connection")

    monkeypatch.setattr("trading_db.connections.engine_for", denied)
    url = URL.create(
        "postgresql+psycopg",
        username="trading_bootstrap",
        password="synthetic",
        host="127.0.0.1",
        port=55432,
        database="trading_test",
    ).set(**changes)
    with pytest.raises(DatabaseFailure):
        recovery.export_snapshot(url, project, Fernet.generate_key())
