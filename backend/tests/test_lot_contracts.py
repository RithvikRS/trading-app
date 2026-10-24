"""Independent lot evidence bounds, cancellation shape and legacy canonical content."""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from trading_db.import_contracts import BatchDefinition, CandidateDefinition, StagedValue
from trading_db.imports import canonical


def lot(**changes):
    return CandidateDefinition(
        **(
            dict(
                occurrence=1,
                kind="lot_remaining",
                as_of_date="2026-10-24",
                instrument_identifier_id=uuid4(),
                values=(StagedValue(role="quantity", source="1.000000000001"),),
            )
            | changes
        )
    )


@pytest.mark.parametrize(
    "kind,quantity,issue",
    (
        ("lot_remaining", "0", None),
        ("lot_acquisition", "0", "conflicting_evidence"),
        ("lot_remaining", "-1", "conflicting_evidence"),
        ("lot_acquisition", "0.000000000001", None),
    ),
)
def test_original_and_remaining_quantity_have_distinct_meanings(kind, quantity, issue):
    assert lot(kind=kind, values=(StagedValue(role="quantity", source=quantity),)).issue() == issue


@pytest.mark.parametrize("role", ("acquisition_cost", "reported_tax_basis", "discount_amount"))
def test_negative_lot_cost_basis_or_discount_remains_blocked_evidence(role):
    value = StagedValue(role=role, source="-1.00000000", currency="USD")
    assert (
        lot(values=(StagedValue(role="quantity", source="1"), value)).issue()
        == "conflicting_evidence"
    )
    zero = value.model_copy(update={"source": "-0.00000000"})
    assert lot(values=(StagedValue(role="quantity", source="1"), zero)).issue() is None
    unknown = value.model_copy(update={"source": None, "missing_reason": "not_supplied"})
    assert lot(values=(StagedValue(role="quantity", source="1"), unknown)).issue() is None


def test_acquisition_date_is_not_inferred_and_cannot_follow_its_observation():
    assert lot().acquisition_date is None
    assert lot(acquisition_date="2026-10-25").issue() == "conflicting_evidence"
    assert lot(acquisition_date="2026-10-24").issue() is None
    with pytest.raises(ValidationError):
        lot(acquisition_date="2026-02-30")
    with pytest.raises(ValidationError):
        lot(kind="position_snapshot", acquisition_date="2026-09-01")


def test_cancellation_has_explicit_date_but_no_invented_economic_components():
    valid = CandidateDefinition(occurrence=1, kind="cancellation", booking_date="2026-10-24")
    assert valid.issue() is None and valid.values == () and valid.posting_state is None
    assert valid.model_copy(update={"booking_date": None}).issue() == "not_supplied"
    assert (
        valid.model_copy(
            update={"values": (StagedValue(role="net_cash", source="0", currency="INR"),)}
        ).issue()
        == "unsupported_component"
    )
    with pytest.raises(ValidationError):
        CandidateDefinition.model_validate(valid.model_dump() | {"posting_state": "posted"})


def test_new_metadata_does_not_change_legacy_canonical_bytes():
    definition = BatchDefinition(normalizer="synthetic", normalizer_version="1", rows=(lot(),))
    revised = definition.model_copy(
        update={"rows": (definition.rows[0].model_copy(update={"acquisition_date": "2026-09-01"}),)}
    )
    for version in (1, 2):
        assert canonical(definition, version) == canonical(revised, version)
        assert "acquisition_date" not in json.loads(canonical(definition, version))["rows"][0]
    assert "posting_state" not in json.loads(canonical(definition, 1))["rows"][0]
    assert "posting_state" in json.loads(canonical(definition, 2))["rows"][0]
    assert canonical(definition) != canonical(revised)
