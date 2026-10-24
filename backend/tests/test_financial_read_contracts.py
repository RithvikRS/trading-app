"""Strict JSON contracts for protected identity reads."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from trading_api.read_contracts import AccountView, FinancialPage, PageQuery, PositionQuery
from trading_db.financial_reads import page_result


@pytest.mark.parametrize("limit", [True, False, 0, -1, 101, 1.0, "25", None])
def test_page_size_never_coerces_or_exceeds_bounds(limit):
    with pytest.raises(ValidationError):
        PageQuery.model_validate({"limit": limit})


@pytest.mark.parametrize(
    "after",
    [
        "",
        "0" * 32,
        "00000000-0000-0000-0000-000000000000",
        "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
        1,
        True,
    ],
)
def test_cursor_requires_canonical_nonzero_string(after):
    with pytest.raises(ValidationError):
        PageQuery.model_validate({"after": after})


@pytest.mark.parametrize("field", ["owner_id", "balance", "reference", "search", "offset"])
def test_unknown_query_fields_are_rejected(field):
    with pytest.raises(ValidationError):
        PageQuery.model_validate({field: "synthetic"})


def test_json_identifier_roundtrips_and_missing_parent_cannot_be_inferred():
    value = str(uuid4())
    query = PositionQuery.model_validate_json('{"account_id":"' + value + '"}')
    assert query.account_id == value and query.limit == 25 and query.after is None
    assert PositionQuery.model_validate(query.model_dump()) == query
    with pytest.raises(ValidationError):
        PositionQuery.model_validate({})
    with pytest.raises(ValidationError):
        PageQuery.model_validate(PageQuery().model_copy(update={"limit": 101}))


def test_concrete_response_type_preserves_all_allowlisted_fields():
    rows = [
        dict(
            id=str(uuid4()),
            kind="bank",
            institution="hdfc",
            market="IN",
            label="Synthetic account",
            currencies=("INR",),
            revision=1,
            state="active",
        )
        for _ in range(2)
    ]
    page = page_result(AccountView, FinancialPage[AccountView], rows, 1)
    assert page.model_dump()["items"] == (rows[0],)
    assert page.next_after == rows[0]["id"]
    assert "Synthetic account" not in repr(page)
    final = page_result(AccountView, FinancialPage[AccountView], rows[1:], 1)
    assert final.next_after is None
    assert page_result(AccountView, FinancialPage[AccountView], [], 1).items == ()
