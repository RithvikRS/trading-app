"""Private typed native evidence and finite account/kind/root/revision reads."""

import json
import warnings
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from trading_api.credit_evidence_contracts import (
    CreditCashView,
    CreditEvidenceHistoryPage,
    CreditEvidenceHistoryQuery,
    CreditEvidenceInspectQuery,
    CreditEvidencePage,
    CreditEvidenceQuery,
    evidence_model,
)
from trading_api.credit_read_contracts import serialize_response
from trading_db.credit_evidence_reads import CreditEvidenceReadTransaction, project
from trading_db.financial_reads import FinancialReadUnavailable

KINDS = ("statement", "current", "entry")
PRIVATE = "123456789.40"
ACCOUNT = str(uuid4())
SOURCE = str(uuid4())
ROOT = str(uuid4())


def cash(source=PRIVATE, currency="INR", missing_reason=None):
    return dict(source=source, currency=currency, missing_reason=missing_reason)


def values(kind):
    if kind == "statement":
        return dict(
            period_start="0001-01-01",
            period_end="9999-12-31",
            statement_date="2026-10-01",
            due_date=None,
            opening_liability=cash("-100.10"),
            closing_liability=cash("-0.00"),
            total_due=cash(),
            minimum_due=cash(None, missing_reason="not_supplied"),
        )
    if kind == "current":
        return dict(
            as_of_date="2026-10-01",
            as_of_instant="2026-10-01T00:15:00.1200+05:30",
            outstanding=cash(),
            unbilled=cash(None, missing_reason="unsupported"),
            credit_limit=cash("0.00"),
            available_credit=cash("-0.00"),
        )
    return dict(
        role="pending_debit",
        treatment="unsupported",
        transaction_date="2026-10-01",
        posting_date=None,
        billing_amount=cash(),
        original_amount=cash(None, "USD", "not_supplied"),
    )


def item(kind, **updates):
    return (
        dict(
            id=ROOT,
            kind=kind,
            revision=1,
            previous_revision=None,
            source_id=SOURCE,
            mapping_revision=1,
            account_id=ACCOUNT,
            account_state="active",
            is_latest_revision=True,
            values=values(kind),
        )
        | updates
    )


def row(kind, **updates):
    data = item(kind, **updates)
    payload = data.pop("values")
    data.update(
        child_revision=data["revision"], child_kind=kind, mapping_account=data["account_id"]
    )
    for name, value in payload.items():
        if name in (
            "transaction_date",
            "posting_date",
            "period_start",
            "period_end",
            "statement_date",
            "due_date",
            "as_of_date",
        ):
            data[name] = date.fromisoformat(value) if value is not None else None
        elif isinstance(value, dict) or name == "original_amount":
            prefix = name.removesuffix("_amount")
            for part in ("source", "missing"):
                data[prefix + "_" + part] = (
                    value["source" if part == "source" else "missing_reason"] if value else None
                )
            data[prefix + "_amount"] = (
                Decimal(value["source"]) if value and value["source"] is not None else None
            )
            if name == "original_amount":
                data["original_currency"] = value["currency"] if value else None
        else:
            data[name] = value
    return data


def reader(rows):
    instance = object.__new__(CreditEvidenceReadTransaction)
    instance._account = lambda account: True
    instance._root = lambda *args: True
    result = SimpleNamespace(all=lambda: rows, one_or_none=lambda: rows[0] if rows else None)
    instance._execute = lambda *args, **kw: SimpleNamespace(mappings=lambda: result)
    return instance


@pytest.mark.parametrize("kind", KINDS)
def test_exact_native_typed_payloads_survive_serialization(kind):
    value = evidence_model(kind).model_validate(item(kind))
    encoded = serialize_response(CreditEvidencePage, CreditEvidencePage(items=(value,)))
    decoded = json.loads(encoded)
    assert decoded["items"][0] == item(kind)
    assert PRIVATE not in repr(value) and PRIVATE not in repr(value.values)
    assert "value" not in json.dumps(decoded["items"][0]["values"])
    assert project(row(kind), account=ACCOUNT, kind=kind) == value


@pytest.mark.parametrize(
    "original", [None, cash(None, "USD", "unsupported"), cash("-0.00", "USD"), cash("12.30", "INR")]
)
def test_original_cash_presence_missing_and_zero_remain_distinct(original):
    payload = values("entry") | dict(original_amount=original)
    value = evidence_model("entry").model_validate(item("entry", values=payload))
    assert (
        json.loads(serialize_response(type(value), value))["values"]["original_amount"] == original
    )


@pytest.mark.parametrize("value", [True, False, 0, -1, 101, 1.5, "25", None])
def test_query_limits_are_strict(value):
    for model, extra in ((CreditEvidenceQuery, {}), (CreditEvidenceHistoryQuery, {"id": ROOT})):
        with pytest.raises(ValidationError):
            model.model_validate(dict(account_id=ACCOUNT, kind="entry", limit=value) | extra)


@pytest.mark.parametrize("field", ["account_id", "id"])
@pytest.mark.parametrize(
    "value", [None, 1, True, "", str(UUID(int=0)), "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"]
)
def test_bound_ids_are_strict(field, value):
    with pytest.raises(ValidationError):
        CreditEvidenceInspectQuery.model_validate(
            dict(account_id=ACCOUNT, kind="entry", id=ROOT, at_revision=1) | {field: value}
        )


@pytest.mark.parametrize("value", [None, True, 0, -1, "1", 1.0, 9007199254740992])
def test_exact_revision_is_required_positive_and_bounded(value):
    with pytest.raises(ValidationError):
        CreditEvidenceInspectQuery(account_id=ACCOUNT, kind="entry", id=ROOT, at_revision=value)


@pytest.mark.parametrize(
    "extra",
    [
        {"kind": "balance"},
        {"owner_id": SOURCE},
        {"search": PRIVATE},
        {"offset": 0},
        {"values": {}},
        {"paid": True},
    ],
)
def test_request_discriminator_and_no_extra_payload(extra):
    with pytest.raises(ValidationError):
        CreditEvidenceQuery.model_validate(dict(account_id=ACCOUNT, kind="entry") | extra)


@pytest.mark.parametrize(
    "change",
    [
        {"source": 1.2},
        {"source": "NaN"},
        {"source": "1e2"},
        {"source": "1.001"},
        {"source": "01"},
        {"source": None},
        {"missing_reason": "unsupported"},
        {"currency": "EUR"},
        {"amount": PRIVATE},
    ],
)
def test_cash_is_native_exact_bounded_and_privately_invalid(change):
    with pytest.raises(ValidationError) as error:
        CreditCashView.model_validate(cash() | change)
    assert PRIVATE not in str(error.value)


@pytest.mark.parametrize(
    "kind,change",
    [
        ("statement", {"period_end": "0000-01-01"}),
        ("statement", {"period_start": "9999-12-31", "period_end": "0001-01-01"}),
        ("statement", {"minimum_due": cash("-0.01")}),
        ("statement", {"total_due": cash("1.00", "USD")}),
        ("current", {"as_of_instant": "2026-09-30T23:59:00Z"}),
        ("current", {"as_of_instant": "2026-10-01T00:00:00"}),
        ("current", {"credit_limit": cash("-1.00")}),
        ("entry", {"posting_date": "2026-10-01"}),
        ("entry", {"role": "unresolved", "treatment": "movement"}),
        ("entry", {"billing_amount": cash("-1.00")}),
        ("entry", {"original_amount": cash("-1.00", "USD")}),
        ("entry", {"transaction_date": "2026-02-30"}),
    ],
)
def test_typed_values_reuse_financial_contracts(kind, change):
    with pytest.raises(ValidationError):
        evidence_model(kind).model_validate(item(kind, values=values(kind) | change))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "attack", ["extra", "missing", "wrong_cash", "wrong_kind", "cycle", "oversized"]
)
def test_counterfeit_nested_responses_fail_without_private_warnings(kind, attack, caplog, capsys):
    value = evidence_model(kind).model_validate(item(kind))
    if attack == "extra":
        value = value.model_copy(update={"private": PRIVATE})
    elif attack == "missing":
        value = value.model_copy()
        del value.__dict__["values"]
    elif attack == "wrong_kind":
        value = value.model_copy(update={"kind": "other"})
    else:
        fields = value.values.model_copy()
        role = {"statement": "total_due", "current": "outstanding", "entry": "billing_amount"}[kind]
        nested = getattr(fields, role).model_copy(update={"source": {"private": PRIVATE}})
        if attack == "cycle":
            nested.__dict__["source"] = nested
        fields.__dict__[role] = nested
        value = value.model_copy(update={"values": fields})
    page = CreditEvidencePage.model_construct(
        items=(value,) * (101 if attack == "oversized" else 1), next_after=None
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(ValueError) as error:
            serialize_response(CreditEvidencePage, page)
    captured = capsys.readouterr()
    assert (
        not caught and PRIVATE not in str(error.value) + caplog.text + captured.out + captured.err
    )


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "change",
    [
        {"account_id": SOURCE},
        {"kind": "invalid"},
        {"child_kind": "invalid"},
        {"child_revision": 2},
        {"mapping_account": None},
        {"revision": True},
        {"previous_revision": 1},
        {"mapping_revision": 0},
    ],
)
def test_projection_checks_scope_child_mapping_and_revisions(kind, change):
    raw = row(kind)
    raw.update(change)
    with pytest.raises((FinancialReadUnavailable, ValidationError)):
        project(raw, account=ACCOUNT, kind=kind)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "attack", ["missing_column", "wrong_numeric", "nonfinite", "amount_mismatch", "bad_date"]
)
def test_projected_values_fail_privately(kind, attack):
    raw = row(kind)
    role = {"statement": "total_due", "current": "outstanding", "entry": "billing"}[kind]
    if attack == "missing_column":
        del raw[role + "_source"]
    elif attack == "wrong_numeric":
        raw[role + "_amount"] = 123.4
    elif attack == "nonfinite":
        raw[role + "_amount"] = Decimal("NaN")
    elif attack == "amount_mismatch":
        raw[role + "_amount"] = Decimal("42")
    else:
        raw[
            {"statement": "period_start", "current": "as_of_date", "entry": "transaction_date"}[
                kind
            ]
        ] = PRIVATE
    with pytest.raises(FinancialReadUnavailable) as error:
        project(raw, account=ACCOUNT, kind=kind)
    assert PRIVATE not in str(error.value)


@pytest.mark.parametrize("operation", ["query", "history", "inspect"])
def test_constructed_invalid_request_rejected_before_sql(operation):
    models = {
        "query": CreditEvidenceQuery,
        "history": CreditEvidenceHistoryQuery,
        "inspect": CreditEvidenceInspectQuery,
    }
    body = dict(
        account_id=ACCOUNT,
        kind="entry",
        **({} if operation == "query" else {"id": ROOT}),
        **({"at_revision": 1} if operation == "inspect" else {}),
    )
    request = models[operation].model_construct(**(body | {"account_id": PRIVATE}))
    reads = object.__new__(CreditEvidenceReadTransaction)
    reads._execute = lambda *args, **kw: pytest.fail("SQL reached for invalid request")
    with pytest.raises(ValidationError):
        getattr(reads, "evidence_" + operation)(request)


@pytest.mark.parametrize(
    "attack",
    ["duplicate", "before_cursor", "foreign_sentinel", "invalid_sentinel", "nonlatest", "overflow"],
)
def test_query_probe_validates_every_row_before_continuation(attack):
    ids = sorted([str(uuid4()), str(uuid4())])
    rows = [row("entry", id=identity) for identity in ids]
    after = None
    if attack == "duplicate":
        rows[1]["id"] = ids[0]
    elif attack == "before_cursor":
        after = ids[0]
    elif attack == "foreign_sentinel":
        rows[1]["account_id"] = SOURCE
    elif attack == "invalid_sentinel":
        rows[1]["billing_source"] = PRIVATE + "9"
    elif attack == "nonlatest":
        rows[1]["is_latest_revision"] = False
    else:
        rows.append(row("entry", id=str(uuid4())))
    with pytest.raises((FinancialReadUnavailable, ValidationError)):
        reader(rows).evidence_query(
            CreditEvidenceQuery(account_id=ACCOUNT, kind="entry", limit=1, after=after)
        )


@pytest.mark.parametrize(
    "attack",
    ["wrong_root", "wrong_source", "gap", "cursor", "regressed_latest", "extra_latest", "sentinel"],
)
def test_history_binds_entire_probe_and_inspection_never_substitutes(attack):
    rows = [row("entry", revision=2, previous_revision=1), row("entry", is_latest_revision=False)]
    before = None
    if attack == "wrong_root":
        rows[1]["id"] = SOURCE
    elif attack == "wrong_source":
        rows[1]["source_id"] = ACCOUNT
    elif attack == "gap":
        rows[1]["revision"] = 3
        rows[1]["child_revision"] = 3
        rows[1]["previous_revision"] = 2
    elif attack == "cursor":
        before = 2
    elif attack == "regressed_latest":
        rows[0]["is_latest_revision"] = False
    elif attack == "extra_latest":
        rows[1]["is_latest_revision"] = True
    else:
        rows[1]["original_currency"] = None
    with pytest.raises((FinancialReadUnavailable, ValidationError)):
        reader(rows).evidence_history(
            CreditEvidenceHistoryQuery(
                account_id=ACCOUNT, kind="entry", id=ROOT, limit=1, before=before
            )
        )
    with pytest.raises(FinancialReadUnavailable):
        reader([row("entry", revision=2, previous_revision=1)]).evidence_inspect(
            CreditEvidenceInspectQuery(account_id=ACCOUNT, kind="entry", id=ROOT, at_revision=1)
        )


def test_history_page_keeps_historical_revision_but_never_mixes_roots():
    old = evidence_model("entry").model_validate(item("entry", is_latest_revision=False))
    assert CreditEvidenceHistoryPage(items=(old,)).items == (old,)
    changed = old.model_copy(update={"id": SOURCE, "revision": 2, "previous_revision": 1})
    with pytest.raises(ValidationError):
        CreditEvidenceHistoryPage(items=(changed, old))


def test_confirmed_root_cannot_have_an_empty_initial_history_projection():
    with pytest.raises(FinancialReadUnavailable):
        reader([]).evidence_history(
            CreditEvidenceHistoryQuery(account_id=ACCOUNT, kind="entry", id=ROOT)
        )
    assert (
        reader([])
        .evidence_history(
            CreditEvidenceHistoryQuery(account_id=ACCOUNT, kind="entry", id=ROOT, before=1)
        )
        .items
        == ()
    )
