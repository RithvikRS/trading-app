"""Request tests: financial input and private references cannot enter public manifests."""

import json
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from trading_db.completion_contracts import (
    CompletionRequest,
    CompletionRow,
    CompletionSelection,
    canonical_request,
    parse_manifest,
)


def row(**changes):
    return CompletionRow(**(dict(row_id=uuid4(), review_revision=1, operation="record") | changes))


def request(**changes):
    return CompletionRequest(
        **(
            dict(
                idempotency_key=uuid4(),
                batch_id=uuid4(),
                batch_revision=1,
                baseline="a" * 64,
                mode="limited",
                rows=(row(),),
            )
            | changes
        )
    )


def test_private_references_are_separate_from_the_public_idempotency_manifest():
    first = request(rows=(row(provider_reference="FAKE-PRIVATE-A"),))
    second = first.model_copy(
        update={
            "rows": (first.rows[0].model_copy(update={"provider_reference": "FAKE-PRIVATE-B"}),)
        }
    )
    # The completion service MUST additionally compare the encrypted private identity.
    # A public manifest/digest alone deliberately cannot distinguish these requests.
    encoded = canonical_request(first)
    assert encoded == canonical_request(second)
    assert "FAKE-PRIVATE" not in encoded and "FAKE-PRIVATE" not in repr(first.rows[0])
    parsed = json.loads(encoded)
    assert parsed["rows"][0]["provider_reference_supplied"] is True
    assert "provider_reference" not in parsed["rows"][0]
    absent = first.model_copy(
        update={"rows": (first.rows[0].model_copy(update={"provider_reference": None}),)}
    )
    assert canonical_request(absent) != encoded


def test_request_order_does_not_change_the_public_manifest():
    rows = (row(), row())
    selections = tuple(
        CompletionSelection(row_id=item.row_id, expected_revision=0) for item in rows
    )
    first = request(rows=rows, selections=selections)
    reordered = first.model_copy(update={"rows": rows[::-1], "selections": selections[::-1]})
    assert canonical_request(first) == canonical_request(reordered)
    assert len(canonical_request(first).encode()) < 65536


@pytest.mark.parametrize(
    "changes",
    [
        dict(owner_id=uuid4()),
        dict(amount="100.00"),
        dict(coverage="complete_activity"),
        dict(baseline_verified=True),
        dict(batch_revision=True),
        dict(idempotency_key=UUID(int=0)),
        dict(baseline="a" * 64 + "\n"),
        dict(rows=()),
        dict(mode="override"),
    ],
)
def test_request_does_not_accept_ownership_economics_or_unproved_assertions(changes):
    with pytest.raises(ValidationError):
        request(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        dict(operation="exclude", provider_reference="FAKE"),
        dict(operation="exclude", position_id=uuid4()),
        dict(operation="record", target_id=uuid4()),
        dict(operation="correct"),
        dict(review_revision=True),
        dict(lot_id=uuid4(), lot_source_row_id=uuid4()),
        dict(provider_reference="private@example.invalid"),
        dict(provider_reference="FAKE\n"),
        dict(provider_reference=1.5),
        dict(row_id=UUID(int=0)),
    ],
)
def test_operation_fields_and_private_reference_shapes_are_strict(changes):
    with pytest.raises(ValidationError):
        row(**changes)


def test_nested_copied_models_revalidate_before_serialization():
    value = request()
    broken = value.rows[0].model_copy(update={"provider_reference": 1.5})
    with pytest.raises(ValidationError):
        canonical_request(value.model_copy(update={"rows": (broken,)}))
    with pytest.raises(ValidationError):
        request(rows=(value.rows[0], value.rows[0]))
    with pytest.raises(ValidationError):
        request(
            rows=value.rows, selections=(CompletionSelection(row_id=uuid4(), expected_revision=0),)
        )
    with pytest.raises(ValidationError):
        request(
            rows=(row(operation="exclude"),),
            selections=(CompletionSelection(row_id=value.rows[0].row_id, expected_revision=0),),
        )


def test_corrections_require_the_existing_target_and_supported_reason():
    corrected = row(
        operation="correct",
        target_kind="event",
        target_id=uuid4(),
        target_revision=2,
        correction_reason="posting_update",
    )
    assert corrected.target_revision == 2
    with pytest.raises(ValidationError):
        CompletionRow.model_validate(corrected.model_copy(update={"target_kind": "snapshot"}))
    with pytest.raises(ValidationError):
        CompletionRow.model_validate(corrected.model_copy(update={"provider_reference": "FAKE"}))


def test_request_bounds_and_lot_links_cannot_form_cycles_or_chains():
    rows = tuple(row(provider_reference="FAKE" + str(index)) for index in range(100))
    assert len(canonical_request(request(rows=rows)).encode()) < 65536
    with pytest.raises(ValidationError):
        request(rows=(*rows, row()))
    position, first_id, second_id = uuid4(), uuid4(), uuid4()
    first = row(row_id=first_id, position_id=position, lot_source_row_id=second_id)
    second = row(row_id=second_id, position_id=position, lot_source_row_id=first_id)
    with pytest.raises(ValidationError):
        request(rows=(first, second))
    root = row(position_id=position)
    left = row(position_id=position, lot_source_row_id=root.row_id)
    assert request(rows=(root, left)).rows == (root, left)
    with pytest.raises(ValidationError):
        row(lot_id=uuid4())


def test_public_manifest_round_trip_retains_fields_without_private_values():
    opening = row(position_id=uuid4(), provider_reference="FAKE-PRIVATE")
    remaining = row(position_id=opening.position_id, lot_source_row_id=opening.row_id)
    corrected = row(
        operation="correct",
        target_kind="event",
        target_id=uuid4(),
        target_revision=3,
        correction_reason="source_correction",
    )
    value = request(rows=(opening, remaining, corrected, row(operation="exclude")))
    parsed = parse_manifest(canonical_request(value))
    assert parsed.batch_id == value.batch_id and parsed.baseline == value.baseline
    public = {item.row_id: item for item in parsed.rows}
    assert public[opening.row_id].provider_reference_supplied is True
    assert public[remaining.row_id].lot_source_row_id == opening.row_id
    assert public[corrected.row_id].target_revision == 3
    assert not hasattr(public[opening.row_id], "provider_reference")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda body: body.update(owner_id=str(uuid4())),
        lambda body: body.update(request_contract=True),
        lambda body: body.update(request_contract=2),
        lambda body: body.update(baseline_verified=True),
        lambda body: body["rows"][0].update(provider_reference="FAKE-PRIVATE"),
        lambda body: body["rows"][0].update(provider_reference_supplied="false"),
        lambda body: body["rows"][0].update(operation="exclude"),
        lambda body: body["rows"][0].update(position_id=None),
        lambda body: body["rows"].append(body["rows"][0]),
        lambda body: body["selections"].append(
            dict(row_id=str(uuid4()), expected_revision=0, reason="reviewed")
        ),
    ],
)
def test_stored_manifest_rejects_injected_private_ambiguous_or_incoherent_fields(mutation):
    body = json.loads(canonical_request(request(rows=(row(provider_reference="FAKE-PRIVATE"),))))
    mutation(body)
    with pytest.raises(ValueError):
        parse_manifest(json.dumps(body, sort_keys=True, separators=(",", ":")))


def test_stored_manifest_requires_canonical_order_and_rejects_duplicate_json_keys():
    value = canonical_request(request(rows=(row(), row())))
    parsed = json.loads(value)
    reverse = parsed | {"rows": parsed["rows"][::-1]}
    for damaged in (
        value + " ",
        json.dumps(parsed),
        json.dumps(reverse, sort_keys=True, separators=(",", ":")),
        value.replace('"request_contract":1', '"request_contract":1,"request_contract":1'),
        "[]",
        "{",
        "x" * 65537,
    ):
        with pytest.raises(ValueError):
            parse_manifest(damaged)


def test_manifest_parser_accepts_json_uuids_but_internal_request_remains_strict():
    value = request()
    with pytest.raises(ValidationError):
        CompletionRequest.model_validate(value.model_dump(mode="json"))
    assert parse_manifest(canonical_request(value)).rows[0].row_id == value.rows[0].row_id
