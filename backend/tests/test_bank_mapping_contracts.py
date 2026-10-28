"""Bank assignment boundaries and transition equivalence without SQL or provider state."""

import json
from uuid import UUID

import pytest
from pydantic import ValidationError, model_serializer

from trading_api.bank_mapping_contracts import (
    MAX_MAPPING_REVISION as MAX,
)
from trading_api.bank_mapping_contracts import (
    BankMappingChange,
    BankMappingHead,
    BankMappingHistoryPage,
    BankMappingHistoryQuery,
    BankMappingTarget,
    BankMappingTransition,
    BankSourceScope,
    derive_transition,
    validate_replay,
    validate_target,
)
from trading_api.bank_mapping_contracts import (
    validate_history as check_history,
)
from trading_api.read_contracts import WireModel

SOURCE = "10000000-0000-4000-8000-000000000001"
OTHER = "10000000-0000-4000-8000-000000000002"
ACCOUNT = "20000000-0000-4000-8000-000000000001"
SECOND = "20000000-0000-4000-8000-000000000002"


def scope(**changes):
    return BankSourceScope.model_validate(
        dict(source_id=SOURCE, namespace="hdfc_statement") | changes
    )


def validate_history(query, response, *, minimum_revision=0):
    return check_history(query, response, source=scope(), minimum_revision=minimum_revision)


def command(expected=0, target=ACCOUNT, **changes):
    return BankMappingChange.model_validate(
        dict(source_id=SOURCE, expected_revision=expected, account_id=target) | changes
    )


def transition(revision=1, target=ACCOUNT, **changes):
    return BankMappingTransition.model_validate(
        dict(
            source_id=SOURCE,
            namespace="hdfc_statement",
            revision=revision,
            previous_revision=revision - 1 if revision > 1 else None,
            account_id=target,
            reason="unlinked" if target is None else "initial" if revision == 1 else "correction",
        )
        | changes
    )


def page(head=None, items=(), **changes):
    return BankMappingHistoryPage.model_validate(
        dict(
            source_id=SOURCE,
            namespace="hdfc_statement",
            head_revision=head.revision if head else 0,
            head=head,
            items=tuple(items),
            next_before=items[-1].revision if items and items[-1].revision > 1 else None,
        )
        | changes
    )


def target(**changes):
    return BankMappingTarget.model_validate(
        dict(
            id=ACCOUNT,
            kind="bank",
            institution="hdfc",
            market="IN",
            label="Everyday savings",
            currencies=("INR",),
            revision=1,
            state="active",
        )
        | changes
    )


@pytest.mark.parametrize("value", [0, 1, MAX - 1])
def test_append_expected_bound_allows_only_safe_successor_arithmetic(value):
    assert command(value).expected_revision + 1 <= MAX


@pytest.mark.parametrize("value", [-1, MAX, MAX + 1, True, False, 1.0, "1", None])
def test_append_rejects_terminal_or_coerced_expected_revision(value):
    with pytest.raises(ValidationError):
        command(value)


@pytest.mark.parametrize("value", [1, MAX - 1, MAX])
def test_stored_and_exclusive_history_cursor_domains_include_terminal_revision(value):
    assert transition(value).revision == value
    assert BankMappingHistoryQuery(source_id=SOURCE, before=value).before == value


@pytest.mark.parametrize("value", [0, -1, MAX + 1, True, False, 1.0, "1"])
def test_stored_revision_and_cursor_reject_non_domain_values(value):
    with pytest.raises(ValidationError):
        BankMappingTransition.model_validate(transition().model_dump() | {"revision": value})
    with pytest.raises(ValidationError):
        BankMappingHistoryQuery(source_id=SOURCE, before=value)


@pytest.mark.parametrize("value", [-1, MAX + 1, True, False, 1.0, "0"])
def test_head_does_not_coerce_a_never_linked_or_terminal_revision(value):
    with pytest.raises(ValidationError):
        BankMappingHead(
            source_id=SOURCE, namespace="hdfc_statement", head_revision=value, head=None
        )


@pytest.mark.parametrize(
    "identifier",
    [
        "",
        str(UUID(int=0)),
        SOURCE.upper().replace("100", "ABC", 1),
        SOURCE + "\n",
        "{" + SOURCE + "}",
        UUID(SOURCE),
        1,
    ],
)
def test_ids_are_canonical_nonzero_opaque_strings(identifier):
    for fields in [{"source_id": identifier}, {"account_id": identifier}]:
        with pytest.raises(ValidationError):
            command(**fields)


@pytest.mark.parametrize(
    "extra",
    [
        "owner_id",
        "namespace",
        "reference",
        "account_number",
        "reason",
        "request_id",
        "intent_id",
        "created_at",
    ],
)
def test_command_cannot_override_ownership_custody_or_claim_request_attribution(extra):
    with pytest.raises(ValidationError) as error:
        command(**{extra: "private synthetic value"})
    assert "private synthetic value" not in str(error.value)


def test_json_contract_and_frozen_command_keep_original_predecessor():
    body = dict(source_id=SOURCE, expected_revision=0, account_id=ACCOUNT)
    parsed = BankMappingChange.model_validate_json(json.dumps(body))
    assert parsed == command()
    with pytest.raises(ValidationError):
        parsed.expected_revision = 1
    with pytest.raises(ValidationError):
        command(target=None)


def test_link_correct_unlink_relink_is_contiguous_and_preserves_old_transitions():
    first = derive_transition(command(), scope(), None)
    second = derive_transition(command(1, SECOND), scope(), first)
    third = derive_transition(command(2, None), scope(), second)
    fourth = derive_transition(command(3, ACCOUNT), scope(), third)
    assert [
        (row.revision, row.previous_revision, row.account_id, row.reason)
        for row in (first, second, third, fourth)
    ] == [
        (1, None, ACCOUNT, "initial"),
        (2, 1, SECOND, "correction"),
        (3, 2, None, "unlinked"),
        (4, 3, ACCOUNT, "correction"),
    ]
    assert validate_replay(command(), scope(), None, first) == first
    assert validate_replay(command(1, SECOND), scope(), first, second) == second
    assert validate_replay(command(2, None), scope(), second, third) == third
    # A later coincidentally matching target is not the immediate successor of the command.
    with pytest.raises(ValueError):
        validate_replay(command(), scope(), None, fourth)
    assert fourth.revision == 4 and first.revision == 1


@pytest.mark.parametrize(
    "previous,requested", [(transition(), ACCOUNT), (transition(2, None), None)]
)
def test_no_op_has_no_replayable_state_transition(previous, requested):
    with pytest.raises(ValueError):
        derive_transition(command(previous.revision, requested), scope(), previous)


@pytest.mark.parametrize(
    "previous",
    [None, transition(2), transition(source_id=OTHER), transition(namespace="sbi_statement")],
)
def test_transition_requires_the_exact_owned_scope_and_predecessor(previous):
    with pytest.raises(ValueError):
        derive_transition(command(1, SECOND), scope(), previous)


def test_replay_rejects_changed_payload_scope_reason_and_revision():
    first, saved = transition(), transition(2, SECOND)
    for request, origin, retained in [
        (command(1, None), scope(), saved),
        (command(0, SECOND), scope(), saved),
        (command(1, SECOND), scope(source_id=OTHER), saved),
        (command(1, SECOND), scope(), transition(3, SECOND)),
        (command(1, SECOND), scope(), transition(2, ACCOUNT)),
    ]:
        with pytest.raises(ValueError):
            validate_replay(request, origin, first, retained)


@pytest.mark.parametrize(
    "changes",
    [
        {"previous_revision": 0},
        {"previous_revision": 2},
        {"reason": "correction"},
        {"reason": "unlinked"},
        {"account_id": None},
        {"namespace": "indmoney_india"},
        {"is_current": True},
        {"account_state": "active"},
    ],
)
def test_transition_has_only_immutable_bank_scope_and_derived_reason(changes):
    with pytest.raises(ValidationError):
        transition(**changes)


def test_never_linked_and_explicit_unlink_are_different_heads():
    empty = page()
    assert validate_history(BankMappingHistoryQuery(source_id=SOURCE), empty).head is None
    unlink = transition(2, None)
    linked_before = transition()
    history = page(unlink, (unlink, linked_before))
    assert validate_history(BankMappingHistoryQuery(source_id=SOURCE), history).head == unlink
    assert history.head_revision == 2 and history.head.account_id is None
    with pytest.raises(ValidationError):
        page(unlink, (), head_revision=0)
    with pytest.raises(ValidationError):
        page(head_revision=1)


def test_history_window_and_current_head_remain_independent():
    first, second, third = transition(), transition(2, SECOND), transition(3, None)
    full = page(third, (third, second, first))
    assert validate_history(BankMappingHistoryQuery(source_id=SOURCE), full) == full
    initial = page(third, (third,))
    assert initial.next_before == 3
    assert validate_history(BankMappingHistoryQuery(source_id=SOURCE, limit=1), initial) == initial
    earlier = page(third, (second, first))
    assert (
        validate_history(BankMappingHistoryQuery(source_id=SOURCE, before=3), earlier).head == third
    )
    assert validate_history(
        BankMappingHistoryQuery(source_id=SOURCE, before=1), page(third)
    ) == page(third)
    with pytest.raises(ValueError):
        validate_history(BankMappingHistoryQuery(source_id=SOURCE), earlier)
    with pytest.raises(ValueError):
        validate_history(BankMappingHistoryQuery(source_id=SOURCE, before=3), full)
    with pytest.raises(ValueError):
        validate_history(BankMappingHistoryQuery(source_id=SOURCE, limit=1), full)


def test_terminal_limit_one_cursor_can_be_used_for_the_next_page():
    newest, previous = transition(MAX, SECOND), transition(MAX - 1, ACCOUNT)
    first = page(newest, (newest,))
    assert (
        validate_history(BankMappingHistoryQuery(source_id=SOURCE, limit=1), first).next_before
        == MAX
    )
    query = BankMappingHistoryQuery(source_id=SOURCE, limit=1, before=first.next_before)
    assert validate_history(query, page(newest, (previous,))).items == (previous,)
    assert derive_transition(command(MAX - 1, SECOND), scope(), previous) == newest


@pytest.mark.parametrize("floor", [-1, MAX + 1, True, 1.0, "1"])
def test_history_floor_is_a_strict_bounded_observation(floor):
    with pytest.raises(ValueError):
        validate_history(BankMappingHistoryQuery(source_id=SOURCE), page(), minimum_revision=floor)


def test_observed_newer_head_cannot_regress_on_refresh_or_earlier_page():
    one, two, three = transition(), transition(2, SECOND), transition(3, None)
    query = BankMappingHistoryQuery(source_id=SOURCE)
    assert (
        validate_history(query, page(three, (three, two, one)), minimum_revision=2).head_revision
        == 3
    )
    with pytest.raises(ValueError):
        validate_history(query, page(two, (two, one)), minimum_revision=3)
    with pytest.raises(ValueError):
        validate_history(
            BankMappingHistoryQuery(source_id=SOURCE, before=2),
            page(two, (one,)),
            minimum_revision=3,
        )


@pytest.mark.parametrize(
    "items,changes",
    [
        ((transition(3, SECOND), transition()), {}),
        ((transition(3, SECOND), transition(3, SECOND)), {}),
        ((transition(3, SECOND), transition(2, SECOND)), {}),
        ((transition(3, SECOND), transition(2, None, source_id=OTHER)), {}),
        ((transition(3, SECOND), transition(2, None, namespace="sbi_statement")), {}),
        ((transition(3, ACCOUNT),), {}),
        ((transition(3, SECOND),), {"next_before": None}),
        ((transition(3, SECOND),), {"next_before": 2}),
        ((), {"next_before": 3}),
    ],
)
def test_history_rejects_gaps_duplicates_noops_scope_changes_and_false_continuation(items, changes):
    with pytest.raises(ValidationError):
        page(transition(3, SECOND), items, **changes)


def test_history_rejects_foreign_request_scope_and_silent_partial_pages():
    one, two = transition(), transition(2, SECOND)
    with pytest.raises(ValueError):
        validate_history(BankMappingHistoryQuery(source_id=OTHER), page(two, (two, one)))
    with pytest.raises(ValueError):
        validate_history(BankMappingHistoryQuery(source_id=SOURCE, limit=2), page(two, (two,)))


@pytest.mark.parametrize("limit", [0, 101, True, 1.0, "25"])
def test_history_limit_is_bounded_without_coercion(limit):
    with pytest.raises(ValidationError):
        BankMappingHistoryQuery(source_id=SOURCE, limit=limit)


@pytest.mark.parametrize("currencies", [("INR",), ("USD",), ("INR", "USD")])
def test_target_uses_institution_and_identity_not_labels_or_display_currency(currencies):
    chosen = target(currencies=currencies)
    assert validate_target(scope(), chosen) == chosen
    other = target(id=SECOND, currencies=currencies)
    assert chosen.label == other.label and chosen.id != other.id
    assert validate_target(scope(), other) == other
    assert (
        validate_target(scope(namespace="sbi_statement"), target(institution="sbi")).institution
        == "sbi"
    )
    with pytest.raises(ValueError):
        validate_target(scope(namespace="sbi_statement"), chosen)


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "brokerage"},
        {"institution": "indmoney"},
        {"market": "US"},
        {"state": "archived"},
        {"label": "Account123"},
        {"currencies": ("USD", "INR")},
        {"currencies": ("INR", "INR")},
        {"currencies": ()},
        {"currencies": ("EUR",)},
        {"owner_id": SOURCE},
    ],
)
def test_new_target_is_an_active_compatible_safe_bank_declaration(changes):
    with pytest.raises(ValidationError):
        target(**changes)


def test_constructed_and_counterfeit_models_cannot_bypass_response_contracts():
    class Counterfeit(WireModel):
        @model_serializer
        def secret(self):
            raise AssertionError("Serializer must never run")

    with pytest.raises(ValueError):
        validate_replay(command(), scope(), None, Counterfeit())
    malformed = command().model_copy(update={"expected_revision": MAX})
    with pytest.raises(ValidationError):
        derive_transition(malformed, scope(), None)
    cyclic = page()
    cyclic.__dict__["head"] = cyclic
    with pytest.raises(ValueError):
        validate_history(BankMappingHistoryQuery(source_id=SOURCE), cyclic)
    unsafe = target().model_copy(update={"state": "archived"})
    with pytest.raises(ValidationError):
        validate_target(scope(), unsafe)


def test_history_binds_the_selected_immutable_namespace_not_only_its_uuid():
    wrong = transition(namespace="sbi_statement")
    substituted = page(wrong, (wrong,), namespace="sbi_statement")
    query = BankMappingHistoryQuery(source_id=SOURCE)
    with pytest.raises(ValueError):
        check_history(query, substituted, source=scope())
    assert check_history(query, substituted, source=scope(namespace="sbi_statement")) == substituted
    with pytest.raises(ValueError):
        check_history(query, substituted, source=scope(source_id=OTHER, namespace="sbi_statement"))
