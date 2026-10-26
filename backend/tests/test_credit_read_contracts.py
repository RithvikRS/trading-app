"""Finite private credit identity/mapping wire contracts and serialization."""

import json
import warnings
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from trading_api.credit_read_contracts import (
    CreditAccountView,
    CreditMappingHistoryPage,
    CreditMappingHistoryQuery,
    CreditMappingView,
    CreditPage,
    CreditSourceView,
    serialize_response,
)
from trading_api.read_contracts import PageQuery
from trading_api.valuation_read_contracts import InspectQuery
from trading_db.credit_reads import CreditReadTransaction
from trading_db.financial_reads import FinancialReadUnavailable

MARKER = "Synthetic private nickname"


def account(**updates):
    return (
        dict(
            id=str(uuid4()),
            issuer="hdfc",
            billing_currency="INR",
            label=MARKER,
            revision=1,
            state="active",
        )
        | updates
    )


def mapping(**updates):
    return (
        dict(
            source_id=str(uuid4()),
            revision=1,
            previous_revision=None,
            account_id=str(uuid4()),
            reason="initial",
            is_latest_revision=True,
            account_state="active",
        )
        | updates
    )


@pytest.mark.parametrize("value", [True, False, 0, -1, 101, 1.0, "25", None])
def test_strict_query_limits(value):
    for model, extra in ((PageQuery, {}), (CreditMappingHistoryQuery, {"id": str(uuid4())})):
        with pytest.raises(ValidationError):
            model.model_validate({"limit": value, **extra})


@pytest.mark.parametrize(
    "value", ["", str(UUID(int=0)), "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", 1, True, None]
)
def test_parent_identifiers_are_canonical_nonzero_strings(value):
    for model in (InspectQuery, CreditMappingHistoryQuery):
        with pytest.raises(ValidationError):
            model.model_validate({"id": value})


@pytest.mark.parametrize("value", [True, 0, -1, 1.0, "1", 9007199254740992])
def test_history_revision_is_finite_and_strict(value):
    with pytest.raises(ValidationError):
        CreditMappingHistoryQuery(id=str(uuid4()), before=value)


@pytest.mark.parametrize(
    "extra", ["owner_id", "balance", "last_four", "reference", "offset", "search"]
)
def test_queries_never_accept_financial_or_identifying_extras(extra):
    for model, base in (
        (PageQuery, {}),
        (InspectQuery, {"id": str(uuid4())}),
        (CreditMappingHistoryQuery, {"id": str(uuid4())}),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(base | {extra: MARKER})


@pytest.mark.parametrize(
    "change",
    [
        {"issuer": "sbi"},
        {"billing_currency": "USD"},
        {"label": "Private 1234"},
        {"label": "X" * 65},
        {"label": "Private\n"},
        {"label": 123},
        {"revision": True},
        {"revision": 0},
        {"revision": 9007199254740992},
        {"state": "closed"},
        {"owner_id": str(uuid4())},
        {"created_at": "now"},
    ],
)
def test_account_response_is_minimal_and_safe(change):
    with pytest.raises(ValidationError):
        CreditAccountView.model_validate(account(**change))


def test_all_source_states_preserve_exact_unlink_and_archive_distinctions():
    root, target = str(uuid4()), str(uuid4())
    rows = [
        dict(
            id=root,
            family="hdfc_credit_statement",
            mapping_revision=revision,
            account_id=account_id,
            state=state,
        )
        for revision, account_id, state in (
            (None, None, "unmapped"),
            (2, None, "unmapped"),
            (1, target, "mapped"),
            (1, target, "archived"),
        )
    ]
    for row in rows:
        view = CreditSourceView.model_validate(row)
        assert json.loads(serialize_response(CreditSourceView, view)) == row
    assert rows[0] != rows[1] and rows[2] != rows[3]


@pytest.mark.parametrize(
    "change",
    [
        {"family": "hdfc_statement"},
        {"account_id": str(uuid4())},
        {"state": "mapped"},
        {"state": "archived"},
        {"mapping_revision": 0},
    ],
)
def test_inconsistent_source_shape_fails_closed(change):
    with pytest.raises(ValidationError):
        CreditSourceView.model_validate(
            dict(
                id=str(uuid4()),
                family="hdfc_credit_statement",
                mapping_revision=None,
                account_id=None,
                state="unmapped",
            )
            | change
        )


@pytest.mark.parametrize(
    "change",
    [
        {"revision": 2},
        {"previous_revision": 1},
        {"reason": "correction"},
        {"account_id": None},
        {"reason": "unlinked"},
        {"account_state": None},
        {"is_latest_revision": "true"},
        {"previous_revision": True},
    ],
)
def test_mapping_predecessor_reason_and_lifecycle_are_explicit(change):
    with pytest.raises(ValidationError):
        CreditMappingView.model_validate(mapping(**change))


def test_mapping_history_keeps_old_targets_with_observed_lifecycle():
    root = str(uuid4())
    a = str(uuid4())
    b = str(uuid4())
    rows = tuple(
        CreditMappingView.model_validate(
            mapping(
                source_id=root,
                revision=revision,
                previous_revision=revision - 1 if revision > 1 else None,
                account_id=target,
                reason=reason,
                is_latest_revision=revision == 3,
                account_state=state,
            )
        )
        for revision, target, reason, state in (
            (3, None, "unlinked", None),
            (2, b, "correction", "active"),
            (1, a, "initial", "archived"),
        )
    )
    page = CreditMappingHistoryPage(items=rows[:2], next_before=2)
    assert json.loads(serialize_response(CreditMappingHistoryPage, page))["next_before"] == 2
    assert "items" not in repr(page)
    assert CreditMappingHistoryPage(items=rows[2:]).items[0].account_state == "archived"
    with pytest.raises(ValidationError):
        CreditMappingHistoryPage(items=rows, next_before=2)
    with pytest.raises(ValidationError):
        CreditMappingHistoryPage(items=(rows[0], rows[2]))
    with pytest.raises(ValidationError):
        CreditMappingHistoryPage(
            items=(rows[0], rows[1].model_copy(update={"source_id": str(uuid4())}))
        )


def test_private_page_serialization_preserves_fields_and_order():
    rows = sorted([account(), account()], key=lambda row: row["id"])
    page = CreditReadTransaction._page(
        CreditAccountView, CreditPage[CreditAccountView], rows, PageQuery(limit=1)
    )
    assert json.loads(serialize_response(CreditPage[CreditAccountView], page)) == dict(
        items=[rows[0]], next_after=rows[0]["id"]
    )
    assert MARKER not in repr(page) and MARKER not in repr(page.items[0])
    with pytest.raises(ValidationError):
        CreditPage[CreditAccountView](
            items=tuple(CreditAccountView.model_validate(row) for row in rows[::-1])
        )


@pytest.mark.parametrize("attack", ["duplicate", "backward", "excess", "bad-sentinel", "after"])
def test_probe_and_ordering_failures_are_not_truncated_success(attack):
    rows = sorted([account(), account()], key=lambda row: row["id"])
    query = PageQuery(limit=1)
    if attack == "duplicate":
        rows[1] = rows[0]
    elif attack == "backward":
        rows.reverse()
    elif attack == "excess":
        rows.append(account())
    elif attack == "bad-sentinel":
        rows[1]["label"] = 123
    else:
        query = PageQuery(limit=1, after=rows[0]["id"])
    with pytest.raises((FinancialReadUnavailable, ValidationError)):
        CreditReadTransaction._page(CreditAccountView, CreditPage[CreditAccountView], rows, query)


@pytest.mark.parametrize(
    "attack",
    [
        "construct-label",
        "copy-label",
        "copy-extra",
        "missing-field",
        "nested-copy",
        "tuple-overflow",
        "wrong-type",
        "extra-container",
        "cycle",
    ],
)
def test_counterfeit_wire_values_are_rejected_without_serializer_warnings(attack, capsys, caplog):
    good = CreditAccountView.model_validate(account())
    model = CreditAccountView
    if attack == "construct-label":
        value = model.model_construct(**account(label={"private": MARKER}))
    elif attack == "copy-label":
        value = good.model_copy(update={"label": {"private": MARKER}})
    elif attack == "copy-extra":
        value = good.model_copy(update={"hidden": MARKER})
    elif attack == "missing-field":
        value = good.model_copy()
        del value.__dict__["label"]
    elif attack == "wrong-type":
        value = good.model_dump()
    elif attack == "cycle":
        value = good.model_copy()
        value.__dict__["label"] = value
    elif attack == "extra-container":
        value = good.model_copy()
        object.__setattr__(value, "__pydantic_extra__", {"hidden": MARKER})
    else:
        model = CreditPage[CreditAccountView]
        value = model.model_construct(
            items=(good.model_copy(update={"label": [MARKER]}),)
            if attack == "nested-copy"
            else (good,) * 101,
            next_after=None,
        )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises((ValueError, TypeError, AttributeError)) as error:
            serialize_response(model, value)
    output = capsys.readouterr()
    assert not caught and MARKER not in str(error.value) + caplog.text + output.out + output.err


@pytest.mark.parametrize(
    "method,query",
    [
        ("accounts", PageQuery.model_construct(limit=True)),
        ("sources", PageQuery().model_copy(update={"limit": 101})),
        ("account", InspectQuery.model_construct(id="private")),
        (
            "mapping_history",
            CreditMappingHistoryQuery.model_construct(id=str(uuid4()), before=True),
        ),
    ],
)
def test_counterfeit_requests_fail_before_sql(method, query):
    read = CreditReadTransaction(SimpleNamespace())
    with pytest.raises(ValidationError):
        getattr(read, method)(query)


def test_account_inspection_requires_the_requested_identity(monkeypatch):
    read = CreditReadTransaction(SimpleNamespace())
    result = SimpleNamespace()
    result.mappings = lambda: result
    result.one_or_none = lambda: account()
    monkeypatch.setattr(read, "_execute", lambda *args, **kwargs: result)
    with pytest.raises(FinancialReadUnavailable):
        read.account(InspectQuery(id=str(uuid4())))


@pytest.mark.parametrize("attack", ["source", "latest", "before"])
def test_history_projection_binds_source_latest_flag_and_cursor(monkeypatch, attack):
    root = str(uuid4())
    query = CreditMappingHistoryQuery(id=root)
    row = mapping(source_id=root)
    if attack == "source":
        row["source_id"] = str(uuid4())
    elif attack == "latest":
        row["is_latest_revision"] = False
    else:
        query = CreditMappingHistoryQuery(id=root, before=1)
    result = SimpleNamespace()
    result.mappings = lambda: result
    result.scalar_one = lambda: True
    result.all = lambda: [row]
    read = CreditReadTransaction(SimpleNamespace())
    monkeypatch.setattr(read, "_execute", lambda *args, **kwargs: result)
    with pytest.raises(FinancialReadUnavailable):
        read.mapping_history(query)
