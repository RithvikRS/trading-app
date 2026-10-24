"""Explicit statement meaning and versioned normalization without inferred boundaries."""

import hashlib
import json

import pytest
from pydantic import ValidationError

from trading_db.import_contracts import BatchDefinition, CandidateDefinition, StagedValue
from trading_db.imports import canonical


def checkpoint(**changes):
    return CandidateDefinition(
        **(
            dict(
                occurrence=1,
                kind="cash_snapshot",
                as_of_date="2026-10-24",
                snapshot_scope="native_cash",
                reconciliation_boundary="before_period",
                values=(StagedValue(role="net_cash", source="100.00", currency="INR"),),
            )
            | changes
        )
    )


@pytest.mark.parametrize(
    "changes",
    [
        dict(reconciliation_boundary="opening"),
        dict(reconciliation_boundary=True),
        dict(snapshot_scope=None),
        dict(snapshot_scope="full_account"),
        dict(as_of_date=None),
        dict(kind="cash_movement", snapshot_scope=None),
        dict(kind="lot_remaining", snapshot_scope=None),
        dict(kind="position_snapshot", snapshot_scope="native_cash"),
    ],
)
def test_boundary_requires_explicit_compatible_snapshot_meaning(changes):
    with pytest.raises(ValidationError):
        checkpoint(**changes)


def test_boundary_is_never_inferred_from_date_or_source_instant():
    unknown = checkpoint(reconciliation_boundary=None)
    exact = checkpoint(reconciliation_boundary=None, as_of_instant="2026-10-24T00:00:00+05:30")
    assert unknown.reconciliation_boundary is exact.reconciliation_boundary is None
    assert checkpoint().reconciliation_boundary == "before_period"
    assert (
        checkpoint(reconciliation_boundary="after_period").reconciliation_boundary == "after_period"
    )
    position = checkpoint(
        kind="position_snapshot",
        snapshot_scope="selected_position",
        values=(StagedValue(role="quantity", source="0.000000000001"),),
    )
    assert position.reconciliation_boundary == "before_period"
    assert "2026-10-24" not in repr(position)


@pytest.mark.parametrize("basis", (None, "booking", "value", "settlement"))
def test_cash_basis_is_a_retained_normalization_choice(basis):
    value = BatchDefinition(
        normalizer="synthetic", normalizer_version="1", cash_date_basis=basis, rows=(checkpoint(),)
    )
    assert value.cash_date_basis == basis
    assert json.loads(canonical(value))["cash_date_basis"] == basis


@pytest.mark.parametrize("basis", ("trade", "automatic", True, 1, "booking\n"))
def test_cash_basis_does_not_coerce_or_guess(basis):
    with pytest.raises(ValidationError):
        BatchDefinition(
            normalizer="synthetic",
            normalizer_version="1",
            cash_date_basis=basis,
            rows=(checkpoint(),),
        )


def test_contracts_one_through_four_keep_their_original_canonical_content():
    old = BatchDefinition(
        normalizer="synthetic",
        normalizer_version="1",
        rows=(checkpoint(reconciliation_boundary=None),),
    )
    current = old.model_copy(update={"cash_date_basis": "booking", "rows": (checkpoint(),)})
    # Computed with the prior release's models and canonicalizer, before contract 5.
    expected = (
        "aaecc8d7490e25a6154f99fc4d91f4ef5eb66227c2fa6d501b7c7096742f5713",
        "d5d5d5a3a73afba9599de26e596022817c320a1ca742f7732a6e2319d5ec1630",
        "a8f4d56a8f5a8cb423ca8f991b14ad4214d716c0c2362a4a792f5f361327272d",
        "d3d80ad53031a16d6869f796275f97d4e5e7a4ceac69585ecb7ee5a52443fab5",
    )
    for version, digest in enumerate(expected, 1):
        assert hashlib.sha256(canonical(old, version).encode()).hexdigest() == digest
        assert canonical(old, version) == canonical(current, version)
        legacy = json.loads(canonical(current, version))
        assert "cash_date_basis" not in legacy
        assert "reconciliation_boundary" not in legacy["rows"][0]
    assert canonical(old, 5) != canonical(current, 5)
    assert (
        json.loads(canonical(current, 5))["rows"][0]["reconciliation_boundary"] == "before_period"
    )
