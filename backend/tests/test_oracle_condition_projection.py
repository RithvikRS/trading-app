"""Closed projection regressions; synthetic rows do not establish Oracle formatting."""

from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import oracledb
import pytest

from oracle_tests import acceptance
from trading_oracle import metadata
from trading_oracle.baseline_protocol import SOURCE_FILES, STAGES
from trading_oracle.bootstrap import INSTALLATION_TABLE, JOURNAL_TABLE
from trading_oracle.contracts import OracleUnavailable
from trading_oracle.schema import (
    BASELINE_CHECKSUM,
    OBJECT_STEPS,
    OWNER_TABLE,
    normalize_sql,
)

TABLES = (INSTALLATION_TABLE, JOURNAL_TABLE) + tuple(
    step.table for step in OBJECT_STEPS if step.table is not None
)
CONDITIONS = tuple(
    (table, constraint)
    for table in TABLES
    for constraint in table.constraints
    if constraint.expression is not None
)


def dictionary(monkeypatch, table, overrides=None):
    overrides = overrides or {}

    def supplied(connection, statement, parameters=None, *, limit=256):
        if "FROM user_tab_columns" in statement:
            assert parameters == {"name": table.name}
            return [
                (
                    column.name,
                    column.data_type,
                    column.size or 22,
                    None,
                    None,
                    column.default,
                    "Y" if column.nullable else "N",
                    "B" if column.data_type in {"CHAR", "VARCHAR2"} else None,
                )
                for column in table.columns
            ]
        if "FROM user_constraints" in statement:
            assert parameters == {"name": table.name}
            return [
                (
                    constraint.name,
                    constraint.kind,
                    "ENABLED",
                    "VALIDATED",
                    "NOT DEFERRABLE",
                    "IMMEDIATE",
                    "TRADING_MIGRATOR" if constraint.parent else None,
                    constraint.parent,
                    "NO ACTION" if constraint.parent else None,
                    overrides.get(constraint.name, constraint.expression),
                )
                for constraint in table.constraints
            ]
        assert "FROM user_cons_columns" in statement
        constraint = next(c for c in table.constraints if c.name == parameters["name"])
        return [(column,) for column in constraint.columns]

    monkeypatch.setattr(metadata, "rows", supplied)


def test_frozen_baseline_profile_and_receipt_protocol_remain_exact():
    expressions = [constraint.expression for _, constraint in CONDITIONS]
    assert len(expressions) == 40
    assert all(type(value) is str and value and value.isascii() for value in expressions)
    assert max(map(len, expressions)) == 109
    assert metadata.MAX_CONDITION_CHARS == 512
    assert BASELINE_CHECKSUM == "ed8301243c313157805dcacc487a4715ea5eca8bc7211a8c1f9a972cd134d679"
    assert STAGES == (
        "setup",
        "bootstrap",
        "migration",
        "seed",
        "unlock",
        "ownership",
        "identity",
        "preferences",
        "custody",
        "concurrency",
        "schema",
        "clients_closed",
    )
    assert "backend/trading_oracle/metadata.py" in SOURCE_FILES
    assert "backend/oracle_tests/acceptance.py" in SOURCE_FILES


@pytest.mark.parametrize("table", TABLES, ids=lambda table: table.name)
def test_each_full_dictionary_control_passes(monkeypatch, table):
    dictionary(monkeypatch, table)
    metadata.table_exact(object(), table)


@pytest.mark.parametrize("table,constraint", CONDITIONS, ids=[c.name for _, c in CONDITIONS])
@pytest.mark.parametrize("length", [None, 512], ids=["ordinary", "raw-boundary"])
def test_every_expected_condition_accepts_ordinary_and_exact_raw_boundary(
    monkeypatch, table, constraint, length
):
    expected = constraint.expression
    actual = expected if length is None else expected + " " * (length - len(expected))
    assert metadata.normalized_condition(actual) == normalize_sql(expected)
    dictionary(monkeypatch, table, {constraint.name: actual})
    metadata.table_exact(object(), table)


@pytest.mark.parametrize("table,constraint", CONDITIONS, ids=[c.name for _, c in CONDITIONS])
@pytest.mark.parametrize("length", [513, 4000])
def test_padded_prefix_denies_after_a_valid_full_table_control(
    monkeypatch, table, constraint, length
):
    dictionary(monkeypatch, table)
    metadata.table_exact(object(), table)
    expected = constraint.expression
    prefix = expected + " " * (length - len(expected))
    assert len(prefix) == length
    assert normalize_sql(prefix) == normalize_sql(expected)
    assert normalize_sql(prefix + " OR 1=1") != normalize_sql(expected)
    dictionary(monkeypatch, table, {constraint.name: prefix})
    with pytest.raises(OracleUnavailable):
        metadata.table_exact(object(), table)


def test_raw_guard_is_the_only_rejection_for_a_complete_padded_projection(monkeypatch):
    expression = "is_active IN (0,1)"
    dictionary(monkeypatch, OWNER_TABLE)
    metadata.table_exact(object(), OWNER_TABLE)
    prefix = expression + " " * (4000 - len(expression))
    dictionary(monkeypatch, OWNER_TABLE, {"OWNERS_ACTIVE_EXACT": prefix})
    with pytest.raises(OracleUnavailable):
        metadata.table_exact(object(), OWNER_TABLE)
    # The historical normalize-only comparator admits this same complete fixture.
    monkeypatch.setattr(metadata, "normalized_condition", normalize_sql)
    metadata.table_exact(object(), OWNER_TABLE)


class TextSubclass(str):
    pass


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        1,
        b"1=1",
        TextSubclass("1=1"),
        "",
        " " * 513 + "1=1",
        "1=1" + " " * 510,
        "1=1\u00a0",
        "1=1\u2003",
        "1=1\U0001f600",
        "1=1\ud800",
    ],
    ids=lambda value: type(value).__name__,
)
def test_invalid_raw_shape_rejected_before_normalization(monkeypatch, value):
    assert metadata.normalized_condition(" 1=1 ") == "1 = 1"

    def forbidden(untrusted):
        raise AssertionError("Invalid raw condition reached normalization")

    monkeypatch.setattr(metadata, "normalize_sql", forbidden)
    with pytest.raises(OracleUnavailable) as caught:
        metadata.normalized_condition(value)
    assert str(caught.value) == "Oracle baseline is unavailable."


def test_ascii_formatting_and_literal_semantics_are_preserved(monkeypatch):
    assert metadata.normalized_condition("\t name = 'MiXeD value'\r\n") == "NAME = 'MiXeD value'"
    dictionary(monkeypatch, OWNER_TABLE)
    metadata.table_exact(object(), OWNER_TABLE)
    for changed in ("is_active IN (0,1) OR 1=1", " " * 512):
        dictionary(monkeypatch, OWNER_TABLE, {"OWNERS_ACTIVE_EXACT": changed})
        with pytest.raises(OracleUnavailable):
            metadata.table_exact(object(), OWNER_TABLE)


def test_no_unrelated_constraint_semantic_is_relaxed(monkeypatch):
    dictionary(monkeypatch, OWNER_TABLE)
    metadata.table_exact(object(), OWNER_TABLE)
    altered = replace(
        OWNER_TABLE,
        constraints=tuple(
            replace(c, expression="is_active IN (0,1,2)") if c.name == "OWNERS_ACTIVE_EXACT" else c
            for c in OWNER_TABLE.constraints
        ),
    )
    with pytest.raises(OracleUnavailable):
        metadata.table_exact(object(), altered)


@pytest.mark.parametrize("fault", [None, "projection", "creation", "restoration"])
def test_acceptance_case_restores_exact_constraint_or_fails_before_unlock(monkeypatch, fault):
    expected = "is_active IN (0,1)"
    state = SimpleNamespace(condition=expected, pending=False, closed=False, locks=0)

    class Connection:
        def rollback(self):
            state.pending = False

    @contextmanager
    def connection(*args):
        try:
            yield Connection()
        finally:
            state.closed = True

    def execute(connection, sql, **parameters):
        if sql.startswith("ALTER TABLE owners DROP"):
            assert not state.pending
            state.condition = None
        elif sql.startswith("ALTER TABLE owners ADD"):
            assert not state.pending
            condition = sql.split("CHECK (", 1)[1][:-1]
            if fault == "creation" and "OR 1=1" in condition:
                raise OracleUnavailable()
            if fault == "restoration" and condition == expected:
                raise OracleUnavailable()
            state.condition = condition
        else:
            assert sql == "INSERT INTO owners(id,is_active) VALUES (:owner,2)"
            assert parameters == {"owner": acceptance.UNKNOWN.bytes}
            if state.condition == expected:
                raise oracledb.DatabaseError(SimpleNamespace(code=2290))
            assert state.condition and "OR 1=1" in state.condition
            state.pending = True
            return 1
        return 0

    def rows(connection, statement, *, limit):
        assert limit == 1
        if "search_condition_vc" in statement:
            return [(expected if fault == "projection" else state.condition[:4000],)]
        return [("OWNERS_ACTIVE_EXACT",)] if state.condition is not None else []

    def exact(*args):
        if state.condition != expected:
            raise OracleUnavailable()

    def locked(result):
        state.locks += 1

    monkeypatch.setattr(acceptance, "migration_connection", connection)
    monkeypatch.setattr(acceptance, "execute", execute)
    monkeypatch.setattr(acceptance, "rows", rows)
    monkeypatch.setattr(acceptance, "table_exact", exact)
    monkeypatch.setattr(acceptance, "validate_schema", exact)
    monkeypatch.setattr(acceptance, "locked", locked)
    result = SimpleNamespace(target=object(), secrets=object())
    if fault is None:
        acceptance.condition_projection(result)
        assert state.condition == expected and state.locks == 1
    else:
        with pytest.raises(OracleUnavailable):
            acceptance.condition_projection(result)
        assert state.locks == 0
        assert state.condition == (None if fault == "restoration" else expected)
    assert not state.pending and state.closed


def test_projection_failure_prevents_migration_completion_and_seed(monkeypatch):
    events = []
    monkeypatch.setattr(acceptance, "migrations", lambda result: events.append("migrations"))

    def fail(result):
        events.append("projection")
        raise OracleUnavailable()

    monkeypatch.setattr(acceptance, "condition_projection", fail)
    monkeypatch.setattr(acceptance, "seed", lambda result: events.append("seed"))
    with pytest.raises(OracleUnavailable):
        acceptance.check(object(), object(), lambda stage: events.append(stage))
    assert events == ["migrations", "projection"]
