"""Checksum-bound, explicitly reconciled Oracle DDL installation journal."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import oracledb

from trading_oracle.bootstrap import INSTALLATION_TABLE, JOURNAL_TABLE
from trading_oracle.contracts import LocalTarget, OracleMigrationInterrupted, OracleUnavailable
from trading_oracle.metadata import (
    integer,
    require,
    rows,
    step_exact,
    step_exists,
    table_exact,
    validate_schema,
)
from trading_oracle.schema import BASELINE_CHECKSUM, LOCK_ID, STEPS, Step


def installation(connection: Any, target: LocalTarget, *, ready: bool) -> str:
    found = rows(
        connection,
        "SELECT id,format,run_marker,baseline_checksum,state FROM trading_migrator.installation",
        limit=1,
    )
    require(len(found) == 1)
    item = found[0]
    require(
        integer(item[0]) == 1
        and integer(item[1]) == 1
        and item[2:4] == (target.run_id, BASELINE_CHECKSUM)
    )
    require(item[4] == "READY" if ready else item[4] in {"INITIALIZING", "READY"})
    return str(item[4])


@contextmanager
def migration_lock(connection: Any) -> Iterator[None]:
    with connection.cursor() as cursor:
        result = cursor.var(oracledb.DB_TYPE_NUMBER)
        cursor.execute(
            f"BEGIN :result:=SYS.DBMS_LOCK.REQUEST(id=>{LOCK_ID},lockmode=>6,"
            "timeout=>5,release_on_commit=>FALSE); END;",
            result=result,
        )
        require(integer(result.getvalue()) == 0)
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            result = cursor.var(oracledb.DB_TYPE_NUMBER)
            cursor.execute(f"BEGIN :result:=SYS.DBMS_LOCK.RELEASE({LOCK_ID}); END;", result=result)
            require(integer(result.getvalue()) == 0)


def journal(connection: Any) -> dict[str, tuple[int, str]]:
    entries = rows(
        connection,
        "SELECT step_key,attempt,checksum,state,completed_at "
        "FROM migration_journal ORDER BY step_key,attempt",
        limit=len(STEPS) * 3,
    )
    known = {step.key: step for step in STEPS}
    result: dict[str, tuple[int, str]] = {}
    for key, attempt, checksum, state, completed in entries:
        require(key in known and checksum == known[key].checksum)
        number = integer(attempt)
        previous = result.get(key)
        require(number == (previous[0] + 1 if previous else 1) and number <= 3)
        require(previous is None or previous[1] == "ABANDONED")
        require(state in {"STARTED", "APPLIED", "ABANDONED"})
        require((completed is None) == (state == "STARTED"))
        result[key] = (number, state)
    incomplete = False
    for step in STEPS:
        record = result.get(step.key)
        if incomplete:
            require(record is None)
        if record is None or record[1] != "APPLIED":
            incomplete = True
    return result


def _control_plane(connection: Any, target: LocalTarget) -> str:
    require(
        rows(
            connection,
            "SELECT SYS_CONTEXT('USERENV','SESSION_USER'),"
            "SYS_CONTEXT('USERENV','CURRENT_USER'),"
            "SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM dual",
        )
        == [("TRADING_MIGRATOR", "TRADING_MIGRATOR", "TRADING_MIGRATOR")]
    )
    table_exact(connection, INSTALLATION_TABLE)
    table_exact(connection, JOURNAL_TABLE)
    return installation(connection, target, ready=False)


def install(
    connection: Any, target: LocalTarget, *, checkpoint: Callable[[str, str], None] | None = None
) -> None:
    """Only fixed steps execute. The optional test checkpoint never receives SQL or secrets."""
    target = LocalTarget.model_validate(target.model_dump())
    with migration_lock(connection):
        state = _control_plane(connection, target)
        records = journal(connection)
        if state == "READY":
            require(
                len(records) == len(STEPS)
                and all(record[1] == "APPLIED" for record in records.values())
            )
            validate_schema(connection)
            return
        for step in STEPS:
            previous = records.get(step.key)
            if previous and previous[1] == "APPLIED":
                step_exact(connection, step)
                continue
            if previous and previous[1] == "STARTED":
                raise OracleMigrationInterrupted()
            attempt = previous[0] + 1 if previous else 1
            require(attempt <= 3 and not step_exists(connection, step))
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO migration_journal(step_key,attempt,checksum,state) "
                    "VALUES (:key,:attempt,:checksum,'STARTED')",
                    key=step.key,
                    attempt=attempt,
                    checksum=step.checksum,
                )
            connection.commit()
            if checkpoint:
                checkpoint(step.key, "before_ddl")
            with connection.cursor() as cursor:
                cursor.execute(step.sql)
            if checkpoint:
                checkpoint(step.key, "after_ddl")
            step_exact(connection, step)
            if checkpoint:
                checkpoint(step.key, "after_postcondition")
            _applied(connection, step, attempt)
        validate_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE installation SET state='READY' WHERE id=1 AND state='INITIALIZING'"
            )
            require(cursor.rowcount == 1)
        connection.commit()


def _applied(connection: Any, step: Step, attempt: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE migration_journal SET state='APPLIED',completed_at=SYSTIMESTAMP "
            "WHERE step_key=:key AND attempt=:attempt AND checksum=:checksum AND state='STARTED'",
            key=step.key,
            attempt=attempt,
            checksum=step.checksum,
        )
        require(cursor.rowcount == 1)
    connection.commit()


def reconcile(connection: Any, target: LocalTarget, step_key: str) -> str:
    """Confirm one interrupted step's exact post-state or its known absent pre-state."""
    known = {step.key: step for step in STEPS}
    if type(step_key) is not str or step_key not in known:
        raise OracleUnavailable()
    target = LocalTarget.model_validate(target.model_dump())
    with migration_lock(connection):
        require(_control_plane(connection, target) == "INITIALIZING")
        records = journal(connection)
        record = records.get(step_key)
        require(record is not None and record[1] == "STARTED")
        assert record is not None
        step = known[step_key]
        for predecessor in STEPS[: STEPS.index(step)]:
            require(records.get(predecessor.key, (0, ""))[1] == "APPLIED")
            step_exact(connection, predecessor)
        if step_exists(connection, step):
            step_exact(connection, step)
            _applied(connection, step, record[0])
            return "APPLIED"
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE migration_journal SET state='ABANDONED',completed_at=SYSTIMESTAMP "
                "WHERE step_key=:key AND attempt=:attempt "
                "AND checksum=:checksum AND state='STARTED'",
                key=step.key,
                attempt=record[0],
                checksum=step.checksum,
            )
            require(cursor.rowcount == 1)
        connection.commit()
        return "ABANDONED"
