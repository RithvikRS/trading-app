"""Fabricated public-report rows verify parsing; no customer or provider fixture."""

import hashlib
from datetime import date, datetime
from decimal import localcontext

import pytest

from trading_api import amfi
from trading_api.amfi import HEADER, NavTarget, NavUnavailable, match_nav, parse_report

ISIN = "ZZ0000000016"
REINVESTMENT = "ZZ0000000024"
OTHER = "ZZ0000000032"


def row(**changes):
    fields = (
        dict(
            code="900001",
            first=ISIN,
            second="-",
            name="Synthetic Mutual Fund",
            plan="Direct Plan",
            option="Growth Option",
            nav="12.340000000001",
            day="23-Oct-2026",
        )
        | changes
    )
    return ";".join(fields.values())


def report(*rows, newline="\n", prefix=""):
    return (
        prefix
        + newline.join(
            (
                HEADER,
                "",
                "Open Ended Schemes(Synthetic category)",
                "",
                "Synthetic AMC",
                "",
                *rows,
                "",
            )
        )
    ).encode("utf-8")


def target(**changes):
    return NavTarget(
        **(dict(scheme_code="900001", isin=ISIN, plan="direct", option="growth") | changes)
    )


def match(data, mapping=None, **changes):
    return match_nav(
        parse_report(data),
        mapping or target(),
        **(dict(as_of=date(2026, 10, 24), max_age_days=1) | changes),
    )


def test_source_strings_dates_positions_and_exact_digest_survive_bom_crlf():
    data = report(row(), newline="\r\n", prefix="\ufeff")
    result = parse_report(data)
    evidence = result.rows[0]
    assert result.digest == hashlib.sha256(data).hexdigest() and result.byte_count == len(data)
    assert evidence.line_number == 7 and evidence.occurrence == 1
    assert evidence.nav_source == "12.340000000001" and evidence.date_source == "23-Oct-2026"
    assert evidence.observed_on == date(2026, 10, 23)
    with localcontext() as context:
        context.prec = 2
        assert str(evidence.reported().value) == "12.340000000001"
        assert match(data).usable == evidence
    assert (
        parse_report(data.replace(b"Synthetic AMC", b"123 Synthetic Mutual Fund")).rows
        == result.rows
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"plan": "Regular Plan"},
        {"first": OTHER},
        {"code": "900002"},
        {"option": "IDCW Option"},
        {"second": REINVESTMENT},
    ],
)
def test_mapping_conflicts_never_choose_a_different_variant(changes):
    result = match(report(row(**changes)))
    assert result.status == "identity_conflict" and result.usable is None


@pytest.mark.parametrize(
    "changes",
    [
        {"plan": ""},
        {"plan": "Institutional Plan"},
        {"option": ""},
        {"option": "Bonus Option"},
        {"option": "Unknown Growth"},
    ],
)
def test_unknown_variants_never_use_fund_names_for_inference(changes):
    result = match(report(row(name="Synthetic Direct Growth", **changes)))
    assert result.status == "unsupported_variant" and result.usable is None


def test_idcw_columns_are_separate_targets_and_conflicting_labels_fail():
    data = report(row(second=REINVESTMENT, option="IDCW Option"))
    assert match(data, target(option="idcw_payout")).status == "usable"
    assert match(data, target(isin=REINVESTMENT, option="idcw_reinvestment")).status == "usable"
    assert (
        match(data, target(isin=REINVESTMENT, option="idcw_payout")).status == "identity_conflict"
    )
    assert (
        match(
            report(row(first=ISIN, second=ISIN, option="IDCW")), target(option="idcw_payout")
        ).status
        == "identity_conflict"
    )
    for option, desired, isin in (
        ("IDCW Payout", "idcw_reinvestment", REINVESTMENT),
        ("IDCW Reinvestment", "idcw_payout", ISIN),
    ):
        result = match(
            report(row(second=REINVESTMENT, option=option)), target(isin=isin, option=desired)
        )
        assert result.status == "identity_conflict" and result.usable is None


@pytest.mark.parametrize(
    "nav,status",
    [
        ("", "missing_price"),
        ("-", "missing_price"),
        ("0.0000", "nonpositive_price"),
        ("-12.30", "nonpositive_price"),
    ],
)
def test_unusable_prices_keep_original_evidence_without_becoming_zero(nav, status):
    result = match(report(row(nav=nav)))
    assert result.status == status and result.usable is None
    assert result.evidence.nav_source == nav


@pytest.mark.parametrize(
    "day,status",
    [
        ("25-Oct-2026", "future_price"),
        ("22-Oct-2026", "stale_price"),
        ("23-Oct-2026", "usable"),
        ("24-Oct-2026", "usable"),
    ],
)
def test_freshness_uses_explicit_market_date_and_age_boundary(day, status):
    assert match(report(row(day=day))).status == status


def test_duplicate_even_identical_or_conflicting_scheme_is_ambiguous():
    for second in (row(), row(nav="13.0"), row(code="900002"), row(first=OTHER)):
        result = match(report(row(), second))
        assert result.status == "ambiguous" and result.evidence is result.usable is None
    missing = match(report(row(code="900002", first=OTHER)))
    assert missing.status == "missing" and missing.evidence is None


@pytest.mark.parametrize(
    "line",
    [
        row(nav="1,000.00"),
        row(nav="1e2"),
        row(nav="NaN"),
        row(nav="Infinity"),
        row(nav="12.1234567890123"),
        row(nav=" 12.30"),
        row(day="31-Feb-2026"),
        row(day="1-Oct-2026"),
        row(day="23-OCT-2026"),
        row(code="0900001"),
        row(code="900001.0"),
        row(name=""),
        row() + ";extra",
        row().rsplit(";", 1)[0],
    ],
)
def test_invalid_rows_reject_whole_report_without_echoing_source(line):
    with pytest.raises(NavUnavailable) as failure:
        parse_report(report(row(), line))
    assert str(failure.value) == "NAV evidence is unavailable or unsupported."
    assert line not in str(failure.value)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\xff",
        b"<html>error</html>",
        HEADER.encode(),
        report(row()).replace(b";Plan;Option", b""),
        report(row()).replace(b"Synthetic AMC", b"900001 broken row"),
        report(row()).replace(b"Synthetic AMC", b"bad\x00header"),
        report(row()).replace(b"Synthetic AMC", b"bad\ttab"),
        report(row()).replace(b"\n", b"\r"),
    ],
)
def test_encoding_header_control_and_empty_reports_fail_closed(data):
    with pytest.raises(NavUnavailable):
        parse_report(data)


def test_exact_limits_use_overflow_sentinels_without_unbounded_allocation(monkeypatch):
    data = report(row())
    with monkeypatch.context() as patch:
        patch.setattr(amfi, "MAX_BYTES", len(data))
        assert parse_report(data).byte_count == len(data)
        with pytest.raises(NavUnavailable):
            parse_report(data + b"\n")
    for constant, value, overflow in (
        ("MAX_ROWS", 1, report(row(), row(code="900002"))),
        ("MAX_LINES", 8, data + b"\n"),
        ("MAX_LINE_LENGTH", len(row()), report(row(name="Z" * 256))),
    ):
        with monkeypatch.context() as patch:
            patch.setattr(amfi, constant, value)
            assert len(parse_report(data).rows) == 1
            with pytest.raises(NavUnavailable):
                parse_report(overflow)


@pytest.mark.parametrize(
    "changes",
    [
        {"max_age_days": True},
        {"max_age_days": -1},
        {"max_age_days": 366},
        {"max_age_days": "1"},
        {"as_of": "2026-10-24"},
        {"as_of": datetime(2026, 10, 24)},
    ],
)
def test_freshness_contract_never_coerces_dates_or_counts(changes):
    with pytest.raises(NavUnavailable):
        match(report(row()), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"isin": "-"},
        {"isin": OTHER.lower()},
        {"plan": "Direct"},
        {"option": "idcw"},
        {"scheme_code": 900001},
    ],
)
def test_mapping_requires_exact_existing_identity_fields(changes):
    with pytest.raises(NavUnavailable):
        target(**changes)


def test_report_larger_than_existing_market_occurrence_bound_keeps_original_positions():
    data = report(*(row(code=str(900000 + index)) for index in range(1, 1003)))
    result = parse_report(data)
    assert result.rows[-1].occurrence == 1002 and result.rows[-1].line_number == 1008
    assert result.rows[-1].scheme_code == "901002"


@pytest.mark.parametrize(
    "changes",
    [
        {"first": "ZZ0000000017"},
        {"second": "Redeemed"},
        {"second": "PROVIDER-CODE"},
        {"second": REINVESTMENT + " "},
    ],
)
def test_unsupported_identifier_text_stays_inspectable_but_cannot_value(changes):
    data = report(row(**changes))
    result = match(data)
    assert result.status == "unsupported_identity" and result.usable is None
    assert not result.evidence.identity_supported
    expected = row(**changes).split(";")
    assert result.evidence.payout_or_growth_isin == expected[1]
    assert result.evidence.reinvestment_isin == expected[2]
    # Invalid unrelated identity evidence cannot be selected through its fund name.
    assert (
        match(
            report(
                row(
                    code="900002", first=OTHER, **{k: v for k, v in changes.items() if k != "first"}
                ),
                row(),
            )
        ).status
        == "usable"
    )
