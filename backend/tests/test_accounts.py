"""Synthetic account boundaries and authenticated reference encryption."""

import os
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from trading_db.account_keys import ReferenceKeys, ReferenceUnavailable, initialize_key, load_keys
from trading_db.accounts import AccountDefinition, AccountUnavailable, identifier, page, revision

OWNER = UUID("10000000-0000-4000-8000-000000000001")
SOURCE = UUID("20000000-0000-4000-8000-000000000001")
SYNTHETIC = "FAKE-0001/folio"


def sealed(keys=None):
    keys = keys or ReferenceKeys({1: b"a" * 32}, 1)
    return keys, {
        "owner_id": OWNER,
        "id": SOURCE,
        "namespace": "cas",
        **keys.seal(OWNER, SOURCE, "cas", SYNTHETIC),
    }


def test_reference_round_trip_is_randomized_and_owner_provider_key_scoped():
    keys, first = sealed()
    _, second = sealed(keys)
    assert keys.open(first) == keys.open(second) == SYNTHETIC
    assert first["encrypted_reference"] != second["encrypted_reference"]
    assert first["fingerprint"] == second["fingerprint"]
    assert SYNTHETIC not in repr(first)
    assert repr(keys) == "ReferenceKeys(<redacted>)"
    fingerprints = {
        keys.fingerprint(owner, namespace, value, 1)
        for owner in (OWNER, uuid4())
        for namespace in ("cas", "advisor")
        for value in ("FAKE-0001", "FAKE-001", "fake-0001")
    }
    assert len(fingerprints) == 12
    rotated = ReferenceKeys({1: b"a" * 32, 2: b"b" * 32}, 2)
    assert rotated.open(first) == SYNTHETIC
    _, current = sealed(rotated)
    assert current["key_version"] == 2
    assert current["fingerprint"] != first["fingerprint"]
    assert ReferenceKeys({2: b"b" * 32}, 2).open(current) == SYNTHETIC


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_id", uuid4()),
        ("id", uuid4()),
        ("namespace", "advisor"),
        ("namespace", "unrecognized"),
        ("key_version", 2),
        ("key_version", True),
        ("key_check", "0" * 64),
        ("fingerprint", "0" * 64),
        ("encrypted_reference", "A" * 80),
        ("encrypted_reference", "!" * 80),
        ("encrypted_reference", "a" * 257),
        ("id", UUID(int=0)),
    ],
)
def test_ciphertext_and_context_tampering_fails_without_disclosing_reference(field, value):
    keys, row = sealed()
    row[field] = value
    with pytest.raises(ReferenceUnavailable) as error:
        keys.open(row)
    assert SYNTHETIC not in str(error.value)


@pytest.mark.parametrize(
    "value", ["", "0" * 129, " private", "private ", "a\n", "é", 123, True, None]
)
def test_reference_requires_bounded_exact_ascii(value):
    with pytest.raises(ReferenceUnavailable):
        ReferenceKeys({1: b"a" * 32}, 1).seal(OWNER, SOURCE, "cas", value)


@pytest.mark.parametrize(
    "keys,active",
    [
        ({}, 1),
        ({1: b"a" * 31}, 1),
        ({1: b"a" * 33}, 1),
        ({1: "a" * 32}, 1),
        ({1: b"a" * 32}, 2),
        ({True: b"a" * 32}, 1),
        ({1: b"a" * 32}, True),
        ({0: b"a" * 32}, 0),
        ({1: b"a" * 32, 2: b"a" * 32}, 2),
        ({1: b"a" * 32, 2: b"b" * 32}, 1),
        ({i: bytes([i]) * 32 for i in range(1, 10)}, 1),
    ],
)
def test_key_ring_rejects_unsupported_or_reused_keys(keys, active):
    with pytest.raises(ReferenceUnavailable):
        ReferenceKeys(keys, active)


def test_wrong_and_missing_keys_fail_and_input_mapping_cannot_replace_keys():
    material = {1: b"a" * 32}
    keys = ReferenceKeys(material, 1)
    _, row = sealed(keys)
    material[1] = b"x" * 32
    assert keys.open(row) == SYNTHETIC
    for wrong in (ReferenceKeys({1: b"x" * 32}, 1), ReferenceKeys({2: b"b" * 32}, 2)):
        with pytest.raises(ReferenceUnavailable):
            wrong.open(row)


def test_private_key_creation_is_explicit_exclusive_and_recoverable(tmp_path, monkeypatch):
    monkeypatch.setattr("trading_db.local.ROOT", tmp_path)
    directory = tmp_path / "keys"
    initialize_key(directory, 1)
    original = (directory / "v1.key").read_bytes()
    keys = load_keys(directory, active=1, versions=(1,))
    _, row = sealed(keys)
    with pytest.raises(ReferenceUnavailable):
        initialize_key(directory, 1)
    assert (directory / "v1.key").read_bytes() == original
    assert load_keys(directory, active=1, versions=(1,)).open(row) == SYNTHETIC
    with pytest.raises(ReferenceUnavailable):
        load_keys(directory, active=2, versions=(1, 2))
    assert not (directory / "v2.key").exists()
    if os.name != "nt":
        (directory / "v1.key").chmod(0o644)
        with pytest.raises(ReferenceUnavailable):
            load_keys(directory, active=1, versions=(1,))


@pytest.mark.parametrize(
    "changes",
    [
        {"owner_id": str(OWNER)},
        {"kind": "credit_card"},
        {"market": "US"},
        {"institution": "ubs"},
        {"label": "Account 12345678"},
        {"label": "a\n"},
        {"currencies": ()},
        {"currencies": ("EUR",)},
        {"currencies": ("INR", "INR")},
        {"currencies": ["INR"]},
    ],
)
def test_account_definition_rejects_unsafe_or_inconsistent_payload(changes):
    values = dict(
        kind="bank", institution="hdfc", market="IN", label="Savings", currencies=("INR",)
    )
    with pytest.raises(ValidationError):
        AccountDefinition(**(values | changes))


@pytest.mark.parametrize("value", [None, UUID(int=0), str(OWNER), True])
def test_opaque_ids_cannot_be_coerced(value):
    with pytest.raises(AccountUnavailable):
        identifier(value)


@pytest.mark.parametrize("value", [-1, 0, 101, True, 1.0, "1"])
def test_page_sizes_are_bounded(value):
    with pytest.raises(AccountUnavailable):
        page(value, None)


@pytest.mark.parametrize("value", [-1, 0, True, 1.0, "1", 9007199254740991])
def test_mutation_revision_cannot_be_coerced_or_overflow(value):
    with pytest.raises(AccountUnavailable):
        revision(value)
