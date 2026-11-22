"""Fail-closed inspection of the fixed Oracle baseline's objects and direct grants."""

from decimal import Decimal
from typing import Any

from trading_oracle.contracts import OracleUnavailable
from trading_oracle.schema import (
    GRANTS,
    OBJECT_STEPS,
    SCHEMA,
    STEPS,
    Grant,
    Step,
    Table,
    normalize_sql,
)

MAX_CONDITION_CHARS = 512


def require(condition: bool) -> None:
    if not condition:
        raise OracleUnavailable()


def normalized_condition(value: object) -> str:
    """Closed ASCII profile below SEARCH_CONDITION_VC's truncating projection limit."""
    require(type(value) is str)
    assert isinstance(value, str)
    require(0 < len(value) <= MAX_CONDITION_CHARS and value.isascii())
    return normalize_sql(value)


def rows(
    connection: Any, statement: str, parameters: dict[str, Any] | None = None, *, limit: int = 256
) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(statement, parameters or {}, fetch_decimals=True)
        result = cursor.fetchmany(limit + 1)
    require(len(result) <= limit)
    return list(result)


def integer(value: object) -> int:
    if type(value) is int:
        result = value
    elif isinstance(value, Decimal):
        require(value.is_finite() and value == value.to_integral_value())
        result = int(value)
    else:
        raise OracleUnavailable()
    require(abs(result) <= 9007199254740991)
    return result


def table_exact(connection: Any, table: Table) -> None:
    columns = rows(
        connection,
        "SELECT column_name,data_type,data_length,data_precision,data_scale,"
        "data_default,nullable,char_used FROM user_tab_columns "
        "WHERE table_name=:name ORDER BY column_id",
        {"name": table.name},
    )
    require(len(columns) == len(table.columns))
    for actual, expected in zip(columns, table.columns, strict=True):
        name, kind, size, precision, scale, default, nullable, char_used = actual
        require(
            name == expected.name
            and kind == expected.data_type
            and nullable == ("Y" if expected.nullable else "N")
        )
        if expected.size is not None:
            require(integer(size) == expected.size)
        if kind in {"VARCHAR2", "CHAR"}:
            require(char_used == "B")
        if kind == "NUMBER":
            require(precision is None and scale is None)
        require((normalize_sql(default.strip()) if default else None) == expected.default)
    constraints = rows(
        connection,
        "SELECT constraint_name,constraint_type,status,validated,deferrable,"
        "deferred,r_owner,r_constraint_name,delete_rule,search_condition_vc "
        "FROM user_constraints WHERE table_name=:name",
        {"name": table.name},
    )
    require(len(constraints) == len(table.constraints))
    found = {row[0]: row for row in constraints}
    for expected_constraint in table.constraints:
        require(expected_constraint.name in found)
        actual = found[expected_constraint.name]
        require(
            actual[1:6]
            == (expected_constraint.kind, "ENABLED", "VALIDATED", "NOT DEFERRABLE", "IMMEDIATE")
        )
        actual_columns = rows(
            connection,
            "SELECT column_name FROM user_cons_columns "
            "WHERE constraint_name=:name ORDER BY position",
            {"name": expected_constraint.name},
        )
        actual_names = tuple(row[0] for row in actual_columns)
        require(
            sorted(actual_names) == sorted(expected_constraint.columns)
            if expected_constraint.kind == "C"
            else actual_names == expected_constraint.columns
        )
        if expected_constraint.expression is not None:
            require(
                normalized_condition(actual[9]) == normalize_sql(expected_constraint.expression)
            )
        if expected_constraint.parent is not None:
            require(actual[6:9] == (SCHEMA, expected_constraint.parent, "NO ACTION"))


def grant_rows(connection: Any, grant: Grant) -> list[tuple[Any, ...]]:
    if grant.columns:
        return rows(
            connection,
            "SELECT column_name,grantor,grantable FROM user_col_privs "
            "WHERE owner=:owner AND table_name=:object AND grantee=:grantee "
            "AND privilege=:privilege ORDER BY column_name",
            {
                "owner": SCHEMA,
                "object": grant.object,
                "grantee": grant.grantee,
                "privilege": grant.privilege,
            },
        )
    return rows(
        connection,
        "SELECT grantor,grantable FROM user_tab_privs WHERE owner=:owner "
        "AND table_name=:object AND grantee=:grantee AND privilege=:privilege",
        {
            "owner": SCHEMA,
            "object": grant.object,
            "grantee": grant.grantee,
            "privilege": grant.privilege,
        },
    )


def step_exists(connection: Any, step: Step) -> bool:
    if step.kind == "GRANT":
        require(step.grant is not None)
        return bool(grant_rows(connection, step.grant))  # type: ignore[arg-type]
    if step.kind == "POLICY":
        return bool(
            rows(
                connection,
                "SELECT policy_name FROM user_policies WHERE object_name=:name "
                "AND policy_name='OWNER_SCOPE'",
                {"name": step.name},
            )
        )
    return bool(
        rows(
            connection,
            "SELECT object_name FROM user_objects WHERE object_name=:name AND object_type=:kind",
            {"name": step.name, "kind": step.kind},
        )
    )


def step_exact(connection: Any, step: Step) -> None:
    require(step_exists(connection, step))
    if step.kind == "GRANT":
        grant = step.grant
        require(grant is not None)
        assert grant is not None
        expected = (
            [(column, SCHEMA, "NO") for column in sorted(grant.columns)]
            if grant.columns
            else [(SCHEMA, "NO")]
        )
        require(grant_rows(connection, grant) == expected)
        return
    if step.kind == "POLICY":
        policy = rows(
            connection,
            "SELECT policy_group,pf_owner,package,function,sel,ins,upd,del,idx,"
            "chk_option,enable,policy_type,long_predicate FROM user_policies "
            "WHERE object_name=:name AND policy_name='OWNER_SCOPE'",
            {"name": step.name},
        )
        function = "OWNER_FILTER" if step.name == "OWNERS" else "PREFERENCE_FILTER"
        require(
            policy
            == [
                (
                    "SYS_DEFAULT",
                    SCHEMA,
                    None,
                    function,
                    "YES",
                    "YES",
                    "YES",
                    "YES",
                    "NO",
                    "YES",
                    "YES",
                    "CONTEXT_SENSITIVE",
                    "NO",
                )
            ]
        )
        return
    require(
        rows(
            connection,
            "SELECT status FROM user_objects WHERE object_name=:name AND object_type=:kind",
            {"name": step.name, "kind": step.kind},
        )
        == [("VALID",)]
    )
    if step.table is not None:
        table_exact(connection, step.table)
        return
    source = rows(
        connection,
        "SELECT text FROM user_source WHERE name=:name AND type=:kind ORDER BY line",
        {"name": step.name, "kind": step.kind},
        limit=256,
    )
    require(all(type(row[0]) is str for row in source))
    expected_source = normalize_sql(step.sql).removeprefix("CREATE OR REPLACE ")
    require(normalize_sql("".join(row[0] for row in source)) == expected_source)
    if step.kind == "TRIGGER":
        require(
            rows(
                connection,
                "SELECT status FROM user_triggers WHERE trigger_name=:name",
                {"name": step.name},
            )
            == [("ENABLED",)]
        )


def validate_schema(connection: Any) -> None:
    for step in STEPS:
        step_exact(connection, step)
    expected_objects = {
        (step.name, step.kind, "VALID") for step in OBJECT_STEPS if step.kind != "POLICY"
    }
    expected_objects |= {
        (name, kind, "VALID")
        for name, kind in (
            ("INSTALLATION", "TABLE"),
            ("INSTALLATION_PK", "INDEX"),
            ("MIGRATION_JOURNAL", "TABLE"),
            ("MIGRATION_JOURNAL_PK", "INDEX"),
            ("OWNERS_PK", "INDEX"),
            ("IDENTITY_PK", "INDEX"),
            ("PREFERENCES_PK", "INDEX"),
        )
    }
    require(
        set(rows(connection, "SELECT object_name,object_type,status FROM user_objects"))
        == expected_objects
    )
    require(
        set(rows(connection, "SELECT object_name,policy_name FROM user_policies"))
        == {("OWNERS", "OWNER_SCOPE"), ("WORKSPACE_PREFERENCES", "OWNER_SCOPE")}
    )
    actual_grants = set(
        rows(
            connection,
            "SELECT grantee,table_name,privilege,grantor,grantable "
            "FROM user_tab_privs WHERE owner=:owner",
            {"owner": SCHEMA},
        )
    )
    expected_grants = {
        (grant.grantee, grant.object, grant.privilege, SCHEMA, "NO")
        for grant in GRANTS
        if not grant.columns
    }
    require(actual_grants == expected_grants)
    actual_columns = set(
        rows(
            connection,
            "SELECT grantee,table_name,privilege,column_name,grantor,grantable "
            "FROM user_col_privs WHERE owner=:owner",
            {"owner": SCHEMA},
        )
    )
    expected_columns = {
        (grant.grantee, grant.object, grant.privilege, column, SCHEMA, "NO")
        for grant in GRANTS
        for column in grant.columns
    }
    require(actual_columns == expected_columns)
