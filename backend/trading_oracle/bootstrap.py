"""One-shot control-plane bootstrap inside an already owned disposable Oracle PDB."""

from dataclasses import dataclass

from trading_oracle.contracts import (
    ROLES,
    LocalTarget,
    OracleUnavailable,
    RoleSecrets,
    new_role_secrets,
)
from trading_oracle.local import LocalRun
from trading_oracle.schema import BASELINE_CHECKSUM, Column, Constraint, Table

MIGRATOR_PRIVILEGES = frozenset(
    {"CREATE SESSION", "CREATE TABLE", "CREATE PROCEDURE", "CREATE TRIGGER"}
)
MIGRATOR_PACKAGES = frozenset({"DBMS_LOCK", "DBMS_RLS", "DBMS_SESSION", "UTL_RAW"})

INSTALLATION_DDL = """CREATE TABLE trading_migrator.installation (
 id NUMBER CONSTRAINT installation_id_nn NOT NULL,
 format NUMBER CONSTRAINT installation_format_nn NOT NULL,
 run_marker CHAR(32 BYTE) CONSTRAINT installation_marker_nn NOT NULL,
 baseline_checksum CHAR(64 BYTE) CONSTRAINT installation_checksum_nn NOT NULL,
 state VARCHAR2(12 BYTE) CONSTRAINT installation_state_nn NOT NULL,
 CONSTRAINT installation_pk PRIMARY KEY(id),
 CONSTRAINT installation_id_exact CHECK(id=1),
 CONSTRAINT installation_format_exact CHECK(format=1),
 CONSTRAINT installation_state_exact CHECK(state IN ('INITIALIZING','READY')),
 CONSTRAINT installation_marker_exact CHECK(REGEXP_LIKE(run_marker,'^[0-9a-f]{32}$','c')),
 CONSTRAINT installation_checksum_exact CHECK(REGEXP_LIKE(baseline_checksum,'^[0-9a-f]{64}$','c'))
)"""

JOURNAL_DDL = """CREATE TABLE trading_migrator.migration_journal (
 step_key VARCHAR2(40 BYTE) CONSTRAINT journal_step_nn NOT NULL,
 attempt NUMBER CONSTRAINT journal_attempt_nn NOT NULL,
 checksum CHAR(64 BYTE) CONSTRAINT journal_checksum_nn NOT NULL,
 state VARCHAR2(12 BYTE) CONSTRAINT journal_state_nn NOT NULL,
 started_at TIMESTAMP(6) WITH TIME ZONE DEFAULT SYSTIMESTAMP CONSTRAINT journal_started_nn NOT NULL,
 completed_at TIMESTAMP(6) WITH TIME ZONE,
 CONSTRAINT migration_journal_pk PRIMARY KEY(step_key,attempt),
 CONSTRAINT journal_attempt_exact CHECK(attempt=TRUNC(attempt) AND attempt BETWEEN 1 AND 3),
 CONSTRAINT journal_state_exact CHECK(state IN ('STARTED','APPLIED','ABANDONED')),
 CONSTRAINT journal_checksum_exact CHECK(REGEXP_LIKE(checksum,'^[0-9a-f]{64}$','c')),
 CONSTRAINT journal_completed_exact CHECK((state='STARTED' AND completed_at IS NULL) OR
   (state IN ('APPLIED','ABANDONED') AND completed_at IS NOT NULL))
)"""

INSTALLATION_TABLE = Table(
    "INSTALLATION",
    (
        Column("ID", "NUMBER"),
        Column("FORMAT", "NUMBER"),
        Column("RUN_MARKER", "CHAR", 32),
        Column("BASELINE_CHECKSUM", "CHAR", 64),
        Column("STATE", "VARCHAR2", 12),
    ),
    tuple(
        Constraint("INSTALLATION_" + suffix + "_NN", "C", (column,), f'"{column}" IS NOT NULL')
        for suffix, column in (
            ("ID", "ID"),
            ("FORMAT", "FORMAT"),
            ("MARKER", "RUN_MARKER"),
            ("CHECKSUM", "BASELINE_CHECKSUM"),
            ("STATE", "STATE"),
        )
    )
    + (
        Constraint("INSTALLATION_PK", "P", ("ID",)),
        Constraint("INSTALLATION_ID_EXACT", "C", ("ID",), "id=1"),
        Constraint("INSTALLATION_FORMAT_EXACT", "C", ("FORMAT",), "format=1"),
        Constraint(
            "INSTALLATION_STATE_EXACT", "C", ("STATE",), "state IN ('INITIALIZING','READY')"
        ),
        Constraint(
            "INSTALLATION_MARKER_EXACT",
            "C",
            ("RUN_MARKER",),
            "REGEXP_LIKE(run_marker,'^[0-9a-f]{32}$','c')",
        ),
        Constraint(
            "INSTALLATION_CHECKSUM_EXACT",
            "C",
            ("BASELINE_CHECKSUM",),
            "REGEXP_LIKE(baseline_checksum,'^[0-9a-f]{64}$','c')",
        ),
    ),
)

JOURNAL_TABLE = Table(
    "MIGRATION_JOURNAL",
    (
        Column("STEP_KEY", "VARCHAR2", 40),
        Column("ATTEMPT", "NUMBER"),
        Column("CHECKSUM", "CHAR", 64),
        Column("STATE", "VARCHAR2", 12),
        Column("STARTED_AT", "TIMESTAMP(6) WITH TIME ZONE", default="SYSTIMESTAMP"),
        Column("COMPLETED_AT", "TIMESTAMP(6) WITH TIME ZONE", nullable=True),
    ),
    tuple(
        Constraint("JOURNAL_" + suffix + "_NN", "C", (column,), f'"{column}" IS NOT NULL')
        for suffix, column in (
            ("STEP", "STEP_KEY"),
            ("ATTEMPT", "ATTEMPT"),
            ("CHECKSUM", "CHECKSUM"),
            ("STATE", "STATE"),
            ("STARTED", "STARTED_AT"),
        )
    )
    + (
        Constraint("MIGRATION_JOURNAL_PK", "P", ("STEP_KEY", "ATTEMPT")),
        Constraint(
            "JOURNAL_ATTEMPT_EXACT",
            "C",
            ("ATTEMPT",),
            "attempt=TRUNC(attempt) AND attempt BETWEEN 1 AND 3",
        ),
        Constraint(
            "JOURNAL_STATE_EXACT", "C", ("STATE",), "state IN ('STARTED','APPLIED','ABANDONED')"
        ),
        Constraint(
            "JOURNAL_CHECKSUM_EXACT",
            "C",
            ("CHECKSUM",),
            "REGEXP_LIKE(checksum,'^[0-9a-f]{64}$','c')",
        ),
        Constraint(
            "JOURNAL_COMPLETED_EXACT",
            "C",
            ("STATE", "COMPLETED_AT"),
            "(state='STARTED' AND completed_at IS NULL) OR "
            "(state IN ('APPLIED','ABANDONED') AND completed_at IS NOT NULL)",
        ),
    ),
)


@dataclass(frozen=True, repr=False)
class BootstrapResult:
    target: LocalTarget
    secrets: RoleSecrets


def _sql(run: LocalRun, command: str) -> str:
    return run.sql("ALTER SESSION SET CONTAINER=FREEPDB1;\n" + command)


def _verify_owned_target(run: LocalRun) -> LocalTarget:
    state = run.validate_manifest()
    if state["status"] != "started":
        raise OracleUnavailable()
    target = LocalTarget(run_id=run.run_id, port=run.port())
    if _sql(run, "SELECT marker FROM trading_smoke.run_marker;") != target.run_id:
        raise OracleUnavailable()
    return target


def prepare(run: LocalRun) -> BootstrapResult:
    """A failed bootstrap is discarded with its owned container; never partially replay it."""
    target = _verify_owned_target(run)
    if (
        _sql(
            run,
            "SELECT COUNT(*) FROM dba_users WHERE username IN "
            "('TRADING_MIGRATOR','TRADING_RUNTIME','TRADING_AUTH');",
        )
        != "0"
    ):
        raise OracleUnavailable()
    if _sql(run, "SELECT COUNT(*) FROM dba_context WHERE namespace='TRADING_OWNER_CTX';") != "0":
        raise OracleUnavailable()
    credentials = new_role_secrets()
    for role in ROLES:
        # Revalidation precedes interpolation; role names and generated password shape are closed.
        valid = RoleSecrets.model_validate(credentials.model_dump())
        secret = valid.for_role(role).get_secret_value()
        state = "ACCOUNT UNLOCK" if role == "TRADING_MIGRATOR" else "ACCOUNT LOCK"
        quota = "QUOTA 8M ON users" if role == "TRADING_MIGRATOR" else "QUOTA 0 ON users"
        _sql(
            run,
            f'CREATE USER {role} IDENTIFIED BY "{secret}" '
            f"DEFAULT TABLESPACE users {quota} {state};",
        )
        _sql(run, f"GRANT CREATE SESSION TO {role};")
        _sql(run, f"REVOKE INHERIT PRIVILEGES ON USER {role} FROM PUBLIC;")
    for privilege in sorted(MIGRATOR_PRIVILEGES - {"CREATE SESSION"}):
        _sql(run, f"GRANT {privilege} TO TRADING_MIGRATOR;")
    for package in sorted(MIGRATOR_PACKAGES):
        _sql(run, f"GRANT EXECUTE ON SYS.{package} TO TRADING_MIGRATOR;")
    _sql(run, INSTALLATION_DDL + ";")
    _sql(run, JOURNAL_DDL + ";")
    _sql(run, "CREATE CONTEXT TRADING_OWNER_CTX USING TRADING_MIGRATOR.OWNER_CONTEXT;")
    _sql(
        run,
        "INSERT INTO trading_migrator.installation VALUES "
        f"(1,1,'{target.run_id}','{BASELINE_CHECKSUM}','INITIALIZING');\nCOMMIT;",
    )
    return BootstrapResult(target, credentials)


def verify_context_binding(run: LocalRun) -> None:
    result = _sql(
        run,
        "SELECT COUNT(*) FROM dba_context WHERE namespace='TRADING_OWNER_CTX' "
        "AND schema='TRADING_MIGRATOR' AND package='OWNER_CONTEXT' "
        "AND type='ACCESSED LOCALLY';",
    )
    if result != "1":
        raise OracleUnavailable()


def unlock_clients(run: LocalRun, result: BootstrapResult) -> None:
    """Recheck actual metadata through the migrator before making client logins available."""
    from trading_oracle.connections import migration_connection
    from trading_oracle.migrate import install

    target = _verify_owned_target(run)
    if target != result.target:
        raise OracleUnavailable()
    verify_context_binding(run)
    if (
        _sql(
            run,
            "SELECT COUNT(*) FROM trading_migrator.installation "
            "WHERE id=1 AND format=1 AND state='READY' "
            f"AND baseline_checksum='{BASELINE_CHECKSUM}' AND run_marker='{target.run_id}';",
        )
        != "1"
    ):
        raise OracleUnavailable()
    locked = _sql(
        run,
        "SELECT COUNT(*) FROM dba_users WHERE username IN "
        "('TRADING_AUTH','TRADING_RUNTIME') AND account_status='LOCKED';",
    )
    if locked != "2":
        raise OracleUnavailable()
    with migration_connection(target, result.secrets) as connection:
        install(connection, target)
    verify_client_grants(run)
    _sql(run, "ALTER USER TRADING_RUNTIME ACCOUNT UNLOCK;\nALTER USER TRADING_AUTH ACCOUNT UNLOCK;")


def verify_client_grants(run: LocalRun) -> None:
    """Locked clients cannot inspect their own privileges; use the owned bootstrap admin."""
    # Scalar predicates avoid SQLPlus column wrapping, including for long checksum rows.
    if (
        _sql(
            run,
            "SELECT COUNT(*) FROM dba_sys_privs WHERE grantee IN "
            "('TRADING_RUNTIME','TRADING_AUTH');",
        )
        != "2"
    ):
        raise OracleUnavailable()
    if (
        _sql(
            run,
            "SELECT COUNT(*) FROM dba_sys_privs WHERE grantee IN "
            "('TRADING_RUNTIME','TRADING_AUTH') AND privilege='CREATE SESSION' "
            "AND admin_option='NO';",
        )
        != "2"
    ):
        raise OracleUnavailable()
    if (
        _sql(
            run,
            "SELECT COUNT(*) FROM dba_role_privs WHERE grantee IN "
            "('TRADING_RUNTIME','TRADING_AUTH');",
        )
        != "0"
    ):
        raise OracleUnavailable()
    if (
        _sql(
            run,
            "SELECT COUNT(*) FROM dba_objects WHERE owner IN ('TRADING_RUNTIME','TRADING_AUTH');",
        )
        != "0"
    ):
        raise OracleUnavailable()
    if (
        _sql(
            run,
            "SELECT COUNT(*) FROM dba_ts_quotas WHERE username IN "
            "('TRADING_RUNTIME','TRADING_AUTH') AND max_bytes<>0;",
        )
        != "0"
    ):
        raise OracleUnavailable()
    # validate_schema checks exact outgoing grants on the owned schema. Also reject any
    # unrelated direct object grants that could equip a client with an administrative path.
    if (
        _sql(
            run,
            "SELECT COUNT(*) FROM dba_tab_privs WHERE grantee IN "
            "('TRADING_RUNTIME','TRADING_AUTH') AND owner<>'TRADING_MIGRATOR';",
        )
        != "0"
    ):
        raise OracleUnavailable()
    if (
        _sql(
            run,
            "SELECT COUNT(*) FROM dba_col_privs WHERE grantee IN "
            "('TRADING_RUNTIME','TRADING_AUTH') AND owner<>'TRADING_MIGRATOR';",
        )
        != "0"
    ):
        raise OracleUnavailable()
    if _sql(run, "SELECT COUNT(*) FROM dba_sys_privs WHERE grantee='PUBLIC';") != "0":
        raise OracleUnavailable()
