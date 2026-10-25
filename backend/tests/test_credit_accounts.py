"""Credit identity accepts no card references, financial values or caller ownership."""

import warnings
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from trading_db.credit_accounts import (
    CreditAccount,
    CreditAccountDefinition,
    CreditAccountTransaction,
    CreditAccountUnavailable,
    identifier,
    page,
    revision,
)


@pytest.mark.parametrize(
    "changes",
    [
        {"issuer": "sbi"},
        {"billing_currency": "USD"},
        {"owner_id": str(uuid4())},
        {"last_four": "0000"},
        {"card_number": "synthetic"},
        {"reference": "synthetic"},
        {"outstanding": "0.00"},
        {"label": "Card 0000"},
        {"label": ""},
        {"label": "A" * 65},
        {"label": "Name\n"},
        {"label": " Name"},
        {"label": "<script>"},
        {"label": "Synthetic@example.invalid"},
        {"label": "Café"},
        {"label": None},
        {"label": True},
    ],
)
def test_definition_rejects_unsupported_or_sensitive_fields(changes):
    with pytest.raises(ValidationError) as error:
        CreditAccountDefinition(**({"label": "Synthetic billing"} | changes))
    assert "input_value" not in str(error.value)


def test_identity_representation_is_private_and_definition_is_immutable():
    definition = CreditAccountDefinition(label="Synthetic billing")
    assert definition.issuer == "hdfc" and definition.billing_currency == "INR"
    assert "Synthetic billing" not in repr(definition)
    now = datetime.now(UTC)
    account = CreditAccount(uuid4(), definition, 1, now, now, None)
    assert "Synthetic billing" not in repr(account) and str(account.id) not in repr(account)
    with pytest.raises(ValidationError):
        definition.label = "Changed"


@pytest.mark.parametrize("value", [None, UUID(int=0), str(uuid4()), True, 1])
def test_opaque_identity_is_not_coerced(value):
    with pytest.raises(CreditAccountUnavailable):
        identifier(value)


@pytest.mark.parametrize("value", [-1, 0, 101, True, 1.0, "1", None])
def test_paging_is_strict_and_bounded(value):
    with pytest.raises(CreditAccountUnavailable):
        page(value, None)


@pytest.mark.parametrize("value", [-1, 0, True, 1.0, "1", 9007199254740991])
def test_revision_is_strict_and_bounded(value):
    with pytest.raises(CreditAccountUnavailable):
        revision(value)


def test_valid_identifiers_page_and_revision_retain_identity():
    account_id = uuid4()
    assert identifier(account_id) is account_id
    assert revision(1) == 1
    page(100, account_id)
    with pytest.raises(CreditAccountUnavailable):
        page(25, str(account_id))


@pytest.mark.parametrize(
    "definition",
    [
        {},
        None,
        CreditAccountDefinition.model_construct(label="Account 0000"),
        CreditAccountDefinition(label="Synthetic").model_copy(update={"billing_currency": "USD"}),
        CreditAccountDefinition(label="Synthetic").model_copy(update={"issuer": "unsupported"}),
    ],
)
def test_unsafe_constructed_models_fail_before_accessing_a_transaction(definition):
    unit = CreditAccountTransaction(SimpleNamespace())
    with pytest.raises(CreditAccountUnavailable) as error:
        unit.create(definition)
    assert "0000" not in str(error.value) and "unsupported" not in str(error.value)


def test_invalid_constructed_label_does_not_escape_through_serialization_warnings(capsys, caplog):
    marker = "synthetic-sensitive-marker"
    definition = CreditAccountDefinition(label="Synthetic").model_copy(update={"label": [marker]})
    unit = CreditAccountTransaction(SimpleNamespace())
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        with pytest.raises(CreditAccountUnavailable) as error:
            unit.create(definition)
    output = capsys.readouterr()
    assert captured == []
    assert marker not in str(error.value) + output.out + output.err + caplog.text
