"""Credit source inputs contain only application identifiers and bounded revisions."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from trading_db.credit_sources import (
    FAMILY,
    CreditMapping,
    CreditSource,
    CreditSourceTransaction,
    CreditSourceUnavailable,
    identifier,
    page,
    revision,
)


def test_private_immutable_source_and_mapping_representations():
    source_id, account_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    source = CreditSource(source_id, FAMILY, now)
    mapping = CreditMapping(source_id, 1, None, account_id, "initial", now)
    for value in (source, mapping):
        assert str(source_id) not in repr(value) and str(account_id) not in repr(value)
        with pytest.raises((FrozenInstanceError, AttributeError)):
            value.created_at = now
    assert not hasattr(source, "__dict__") and not hasattr(mapping, "__dict__")


@pytest.mark.parametrize("value", [None, UUID(int=0), str(uuid4()), True, 1])
def test_identifiers_are_strict_before_database_access(value):
    unit = CreditSourceTransaction(SimpleNamespace())
    for call in (
        lambda: identifier(value),
        lambda: unit.get(value),
        lambda: unit.resolve(value),
        lambda: unit.history(value),
        lambda: unit.map(value, None, expected_revision=0),
    ):
        with pytest.raises(CreditSourceUnavailable):
            call()


@pytest.mark.parametrize("value", [-1, True, 1.0, "1", None, 9007199254740991])
def test_mapping_revision_is_not_coerced(value):
    unit = CreditSourceTransaction(SimpleNamespace())
    with pytest.raises(CreditSourceUnavailable):
        unit.map(uuid4(), uuid4(), expected_revision=value)
    with pytest.raises(CreditSourceUnavailable):
        revision(value, initial=True)


@pytest.mark.parametrize("value", [0, -1, 101, True, 1.0, "1", None])
def test_pages_are_bounded_before_database_access(value):
    unit = CreditSourceTransaction(SimpleNamespace())
    with pytest.raises(CreditSourceUnavailable):
        unit.list(limit=value)
    with pytest.raises(CreditSourceUnavailable):
        unit.history(uuid4(), limit=value)


def test_valid_bounds_and_invalid_account_or_cursor():
    unit = CreditSourceTransaction(SimpleNamespace())
    item = uuid4()
    assert identifier(item) is item and revision(0, initial=True) == 0
    page(100, item)
    for call in (
        lambda: unit.list(after="private-marker"),
        lambda: unit.history(item, before=0),
        lambda: unit.map(item, "private-marker", expected_revision=0),
    ):
        with pytest.raises(CreditSourceUnavailable) as error:
            call()
        assert "private-marker" not in str(error.value)


@pytest.mark.parametrize(
    "field",
    [
        "owner_id",
        "reference",
        "card_number",
        "last_four",
        "label",
        "filename",
        "encrypted_reference",
        "amount",
    ],
)
def test_source_creation_has_no_private_or_caller_owned_fields(field, caplog, capsys):
    unit = CreditSourceTransaction(SimpleNamespace())
    with pytest.raises(TypeError) as error:
        unit.create(**{field: "synthetic-private-marker"})
    captured = capsys.readouterr()
    assert (
        "synthetic-private-marker"
        not in str(error.value) + caplog.text + captured.out + captured.err
    )
