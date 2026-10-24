"""Synthetic private-reference envelopes must fail closed under scope/key tampering."""

from uuid import uuid4

import pytest

from trading_db.account_keys import ReferenceKeys, ReferenceUnavailable
from trading_db.provider_keys import ProviderKeys


def envelope():
    keys = ProviderKeys(ReferenceKeys({1: b"a" * 32}, 1))
    row = dict(owner_id=uuid4(), id=uuid4(), source_id=uuid4(), kind="cash_movement")
    row.update(keys.seal(row["owner_id"], row["id"], row["source_id"], row["kind"], "FAKE-REF"))
    return keys, row


def test_reference_round_trip_domain_separation_and_random_nonce():
    keys, row = envelope()
    assert keys.open(row) == "FAKE-REF"
    again = keys.seal(row["owner_id"], row["id"], row["source_id"], row["kind"], "FAKE-REF")
    assert again["fingerprint"] == row["fingerprint"]
    assert again["encrypted_reference"] != row["encrypted_reference"]
    assert "FAKE-REF" not in repr(keys) and "FAKE-REF" not in row["encrypted_reference"]
    account = ReferenceKeys({1: b"a" * 32}, 1)
    assert account.key_check(row["owner_id"], 1) != row["key_check"]
    assert (
        len(
            {
                keys.fingerprint(row["owner_id"], source, kind, "FAKE-REF", 1)
                for source in (row["source_id"], uuid4())
                for kind in ("buy", "sell")
            }
        )
        == 4
    )


@pytest.mark.parametrize(
    "change",
    [
        dict(owner_id=uuid4()),
        dict(id=uuid4()),
        dict(source_id=uuid4()),
        dict(kind="fee"),
        dict(key_version=2),
        dict(key_check="0" * 64),
        dict(fingerprint="0" * 64),
        dict(encrypted_reference="A" * 40),
        dict(encrypted_reference="!" * 40),
        dict(id=uuid4().int),
    ],
)
def test_scope_key_and_ciphertext_tampering_rejected(change):
    keys, row = envelope()
    with pytest.raises(ReferenceUnavailable):
        keys.open(row | change)


@pytest.mark.parametrize(
    "value", [None, True, 1, "", " FAKE", "FAKE ", "x" * 129, "FAKE\n", "नकली"]
)
def test_invalid_private_reference_never_seals(value):
    keys, row = envelope()
    with pytest.raises(ReferenceUnavailable):
        keys.seal(row["owner_id"], row["id"], row["source_id"], row["kind"], value)


def test_wrong_old_or_missing_key_cannot_turn_existing_reference_into_new_identity():
    _, row = envelope()
    for material, active in (({1: b"x" * 32}, 1), ({2: b"b" * 32}, 2)):
        with pytest.raises(ReferenceUnavailable):
            ProviderKeys(ReferenceKeys(material, active)).open(row)
    keys = ProviderKeys(ReferenceKeys({1: b"a" * 32, 2: b"b" * 32}, 2))
    assert keys.open(row) == "FAKE-REF"
    rotated = row | keys.seal(
        row["owner_id"], row["id"], row["source_id"], row["kind"], keys.open(row)
    )
    assert ProviderKeys(ReferenceKeys({2: b"b" * 32}, 2)).open(rotated) == "FAKE-REF"
