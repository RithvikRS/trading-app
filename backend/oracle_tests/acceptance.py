"""Synthetic two-owner, custody, concurrency and interrupted-DDL checks on real Oracle."""

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier, Event
from time import monotonic
from typing import Any
from uuid import UUID

import oracledb

from trading_db.workspace import PreferenceSnapshot, PreferenceUpdate
from trading_oracle.bootstrap import BootstrapResult, _sql, unlock_clients
from trading_oracle.connections import (
    ClientPool,
    _parameters,
    migration_connection,
    oracle_error_code,
)
from trading_oracle.contracts import (
    IdentityKey,
    OracleMigrationInterrupted,
    OracleOwnerDenied,
    OracleUnavailable,
)
from trading_oracle.identity import IdentityDirectory
from trading_oracle.local import LocalRun
from trading_oracle.metadata import integer, require, rows, table_exact, validate_schema
from trading_oracle.migrate import install, journal, reconcile
from trading_oracle.schema import OWNER_TABLE, STEPS, normalize_sql
from trading_oracle.workspace import WorkspaceDatabase

A = UUID("11111111-1111-1111-1111-11111111111a")
B = UUID("22222222-2222-2222-2222-22222222222b")
INACTIVE = UUID("33333333-3333-3333-3333-33333333333c")
UNKNOWN = UUID("44444444-4444-4444-4444-44444444444d")
KEY_A = IdentityKey(issuer="https://issuer.example/", subject="subject-A")
KEY_B = IdentityKey(issuer="https://issuer.example/", subject="subject-B")
# Oracle 26ai also reports a missing object privilege as ORA-41900. This code is
# accepted only around deliberately forbidden operations, never positive reads/writes.
MISSING_OBJECT_PRIVILEGE = 41900


class Interrupted(BaseException):
    pass


@contextmanager
def denial(*codes: int) -> Iterator[None]:
    try:
        yield
    except oracledb.Error as error:
        require(oracle_error_code(error) in codes)
    else:
        raise OracleUnavailable()


@contextmanager
def lock_expiry() -> Iterator[None]:
    """A deliberate WAIT 5 must actually wait and report a server lock-acquisition failure."""
    began = monotonic()
    with denial(30006, 54):
        yield
    require(4 <= monotonic() - began < 12)


def must_fail(function: Callable[[], Any], exception: type[BaseException]) -> None:
    try:
        function()
    except exception:
        return
    raise OracleUnavailable()


def execute(connection: Any, sql: str, **parameters: Any) -> int:
    with connection.cursor() as cursor:
        cursor.execute(sql, parameters)
        return int(cursor.rowcount)


def enter(connection: Any, owner: str | None) -> None:
    with connection.cursor() as cursor:
        cursor.callproc("TRADING_MIGRATOR.OWNER_CONTEXT.ENTER_OWNER", [owner])


def context(connection: Any) -> list[tuple[Any, ...]]:
    return rows(connection, "SELECT SYS_CONTEXT('TRADING_OWNER_CTX','OWNER_ID') FROM dual", limit=1)


def physical(connection: Any) -> tuple[Any, ...]:
    return rows(
        connection,
        "SELECT SYS_CONTEXT('USERENV','SID'),SYS_CONTEXT('USERENV','SESSIONID') FROM dual",
        limit=1,
    )[0]


def locked(result: BootstrapResult) -> None:
    for role in ("TRADING_RUNTIME", "TRADING_AUTH"):
        with denial(28000):
            connection = oracledb.connect(**_parameters(result.target, result.secrets, role))
            connection.close()


def migrations(result: BootstrapResult) -> None:
    locked(result)
    for step in STEPS:
        for stage in ("before_ddl", "after_ddl"):

            def checkpoint(
                key: str,
                location: str,
                *,
                expected_key: str = step.key,
                expected_stage: str = stage,
            ) -> None:
                if key == expected_key and location == expected_stage:
                    raise Interrupted()

            with migration_connection(result.target, result.secrets) as connection:
                must_fail(
                    lambda: install(connection, result.target, checkpoint=checkpoint), Interrupted
                )
            with migration_connection(result.target, result.secrets) as connection:
                require(journal(connection)[step.key][1] == "STARTED")
                must_fail(lambda: install(connection, result.target), OracleMigrationInterrupted)
                expected = "ABANDONED" if stage == "before_ddl" else "APPLIED"
                require(reconcile(connection, result.target, step.key) == expected)
    with migration_connection(result.target, result.secrets) as connection:
        install(connection, result.target)
        require(len(journal(connection)) == len(STEPS))
        require(
            integer(rows(connection, "SELECT COUNT(*) FROM migration_journal", limit=1)[0][0])
            == len(STEPS) * 2
        )
        install(connection, result.target)
        execute(
            connection,
            "UPDATE migration_journal SET checksum=:checksum WHERE step_key=:key",
            checksum="0" * 64,
            key=STEPS[0].key,
        )
        must_fail(lambda: install(connection, result.target), OracleUnavailable)
        connection.rollback()
        install(connection, result.target)
    locked(result)


def condition_projection(result: BootstrapResult) -> None:
    """Prove the real VC prefix is refused, then restore before clients can unlock."""
    expected = "is_active IN (0,1)"
    prefix = expected + " " * (4000 - len(expected))
    weakened = prefix + " OR 1=1"
    drop = "ALTER TABLE owners DROP CONSTRAINT owners_active_exact"
    add = "ALTER TABLE owners ADD CONSTRAINT owners_active_exact CHECK ("
    with migration_connection(result.target, result.secrets) as connection:
        validate_schema(connection)
        with denial(2290):
            execute(
                connection,
                "INSERT INTO owners(id,is_active) VALUES (:owner,2)",
                owner=UNKNOWN.bytes,
            )
        connection.rollback()
        try:
            execute(connection, drop)
            execute(connection, add + weakened + ")")
            projected = rows(
                connection,
                "SELECT search_condition_vc FROM user_constraints "
                "WHERE table_name='OWNERS' AND constraint_name='OWNERS_ACTIVE_EXACT'",
                limit=1,
            )
            require(len(projected) == 1)
            actual = projected[0][0]
            # This case must reproduce the actual dictionary projection; a
            # differently formatted short result cannot count as truncation proof.
            require(type(actual) is str and len(actual) == 4000 and actual.isascii())
            require(normalize_sql(actual) == normalize_sql(expected))
            require(normalize_sql(weakened) != normalize_sql(expected))
            # The same column/named constraint now admits a formerly forbidden
            # synthetic value. Roll it back before any restoring DDL can commit it.
            require(
                execute(
                    connection,
                    "INSERT INTO owners(id,is_active) VALUES (:owner,2)",
                    owner=UNKNOWN.bytes,
                )
                == 1
            )
            connection.rollback()
            must_fail(lambda: table_exact(connection, OWNER_TABLE), OracleUnavailable)
            must_fail(lambda: validate_schema(connection), OracleUnavailable)
        finally:
            connection.rollback()
            existing = rows(
                connection,
                "SELECT constraint_name FROM user_constraints "
                "WHERE table_name='OWNERS' AND constraint_name='OWNERS_ACTIVE_EXACT'",
                limit=1,
            )
            require(existing in ([], [("OWNERS_ACTIVE_EXACT",)]))
            if existing:
                execute(connection, drop)
            execute(connection, add + expected + ")")
            validate_schema(connection)
        with denial(2290):
            execute(
                connection,
                "INSERT INTO owners(id,is_active) VALUES (:owner,2)",
                owner=UNKNOWN.bytes,
            )
        connection.rollback()
    locked(result)


def seed(result: BootstrapResult) -> None:
    with migration_connection(result.target, result.secrets) as connection:
        for owner in (A, B):
            execute(
                connection, "INSERT INTO owners(id,is_active) VALUES (:owner,1)", owner=owner.bytes
            )
        execute(connection, "INSERT INTO owners(id) VALUES (:owner)", owner=INACTIVE.bytes)
        require(
            rows(
                connection,
                "SELECT is_active FROM owners WHERE id=:owner",
                {"owner": INACTIVE.bytes},
                limit=1,
            )
            == [(0,)]
        )
        bindings = (
            (KEY_A, A),
            (KEY_B, B),
            (IdentityKey(issuer="https://issuer.example/", subject="inactive"), INACTIVE),
            (IdentityKey(issuer="https://issuer.example/", subject="é"), A),
            (IdentityKey(issuer="https://issuer.example/", subject="e\u0301"), B),
        )
        for key, owner in bindings:
            execute(
                connection,
                "INSERT INTO owner_identities(issuer,subject,owner_id) "
                "VALUES (:issuer,:subject,:owner)",
                issuer=key.issuer.encode(),
                subject=key.subject.encode(),
                owner=owner.bytes,
            )
        connection.commit()
        with denial(20004):
            execute(connection, "UPDATE owner_identities SET owner_id=:owner", owner=B.bytes)
        with denial(20004):
            execute(connection, "DELETE FROM owner_identities")
        connection.rollback()


def ownership(pool: ClientPool, result: BootstrapResult) -> None:
    with migration_connection(result.target, result.secrets) as administrator:
        for owner in (A, B):
            execute(
                administrator,
                "INSERT INTO workspace_preferences"
                "(owner_id,theme,display_currency,amount_masked) VALUES (:owner,'light','INR',1)",
                owner=owner.bytes,
            )
        administrator.commit()
    with pool.checkout() as connection:
        require(rows(connection, "SELECT id FROM trading_migrator.owners") == [])
        require(
            rows(connection, "SELECT owner_id FROM trading_migrator.workspace_preferences") == []
        )
        execute(connection, "BEGIN SYS.DBMS_SESSION.SET_IDENTIFIER(:owner); END;", owner=str(A))
        require(rows(connection, "SELECT id FROM trading_migrator.owners") == [])
        require(
            rows(connection, "SELECT owner_id FROM trading_migrator.workspace_preferences") == []
        )
        with denial(1031):
            execute(
                connection,
                "BEGIN SYS.DBMS_SESSION.SET_CONTEXT('TRADING_OWNER_CTX','OWNER_ID',:owner); END;",
                owner=A.hex,
            )
        for invalid in (
            None,
            "",
            str(A).upper(),
            str(A) + " ",
            "malformed",
            str(INACTIVE),
            str(UNKNOWN),
        ):
            enter(connection, str(A))
            require(context(connection) == [(A.hex,)])
            with denial(20001):
                enter(connection, invalid)
            require(context(connection) == [(None,)])
            require(rows(connection, "SELECT id FROM trading_migrator.owners") == [])
            require(
                rows(connection, "SELECT owner_id FROM trading_migrator.workspace_preferences")
                == []
            )
        for owner in (A, B):
            enter(connection, str(owner))
            require(
                rows(connection, "SELECT owner_id FROM trading_migrator.workspace_preferences")
                == [(owner.bytes,)]
            )
        enter(connection, str(A))
        require(rows(connection, "SELECT id FROM trading_migrator.owners") == [(A.bytes,)])
        require(
            rows(
                connection,
                "SELECT id FROM trading_migrator.owners WHERE id=:owner",
                {"owner": B.bytes},
            )
            == []
        )
        with denial(28115):
            execute(
                connection,
                "INSERT INTO trading_migrator.workspace_preferences"
                "(owner_id,theme,display_currency,amount_masked) "
                "VALUES (:owner,'dark','USD',0)",
                owner=B.bytes,
            )
        require(
            execute(
                connection,
                "UPDATE trading_migrator.workspace_preferences "
                "SET theme='dark' WHERE owner_id=:owner",
                owner=B.bytes,
            )
            == 0
        )
        for statement in (
            "SELECT * FROM trading_migrator.owner_identities",
            "INSERT INTO trading_migrator.owners(id,is_active) "
            "VALUES (HEXTORAW('55555555555555555555555555555555'),1)",
            "UPDATE trading_migrator.owners SET is_active=0",
            "UPDATE trading_migrator.workspace_preferences SET revision=7",
            "UPDATE trading_migrator.workspace_preferences "
            "SET owner_id=HEXTORAW('55555555555555555555555555555555')",
            "DELETE FROM trading_migrator.workspace_preferences",
            "CREATE TABLE forbidden_ownership_test (id NUMBER)",
            "BEGIN SYS.DBMS_RLS.DROP_POLICY('TRADING_MIGRATOR','OWNERS','OWNER_SCOPE'); END;",
        ):
            with denial(942, 1031, 6550, MISSING_OBJECT_PRIVILEGE):
                execute(connection, statement)
        connection.rollback()
    with migration_connection(result.target, result.secrets) as administrator:
        require(
            rows(
                administrator,
                "SELECT theme FROM workspace_preferences WHERE owner_id=:owner",
                {"owner": B.bytes},
                limit=1,
            )
            == [("light",)]
        )
        execute(administrator, "DELETE FROM workspace_preferences")
        administrator.commit()


def identities(pool: ClientPool) -> None:
    directory = IdentityDirectory(pool)
    require(directory.resolve(KEY_A) == A and directory.resolve(KEY_B) == B)
    for key in (
        IdentityKey(issuer="https://issuer.example", subject="subject-A"),
        IdentityKey(issuer="https://issuer.example/", subject="Subject-A"),
        IdentityKey(issuer="https://issuer.example/", subject="inactive"),
        IdentityKey(issuer="https://issuer.example/", subject="unknown"),
    ):
        require(directory.resolve(key) is None)
    require(directory.resolve(IdentityKey(issuer=KEY_A.issuer, subject="é")) == A)
    require(directory.resolve(IdentityKey(issuer=KEY_A.issuer, subject="e\u0301")) == B)
    with pool.checkout() as connection:
        for table in ("OWNERS", "OWNER_IDENTITIES", "WORKSPACE_PREFERENCES"):
            with denial(942, 1031, MISSING_OBJECT_PRIVILEGE):
                execute(connection, "SELECT * FROM trading_migrator." + table)
        with denial(6550, 1031, MISSING_OBJECT_PRIVILEGE):
            enter(connection, str(A))


def update(revision: int) -> PreferenceUpdate:
    return PreferenceUpdate(
        theme="dark", display_currency="USD", amount_masked=False, revision=revision
    )


def preferences(database: WorkspaceDatabase, result: BootstrapResult) -> None:
    with database.transaction(A, read_only=True) as unit:
        require(unit.preference_snapshot() == PreferenceSnapshot())
        require(unit.get_preferences() is None)
        must_fail(lambda: unit.compare_preferences(update(0)), OracleUnavailable)
    must_fail(unit.preference_snapshot, OracleUnavailable)
    with migration_connection(result.target, result.secrets) as connection:
        require(rows(connection, "SELECT COUNT(*) FROM workspace_preferences", limit=1) == [(0,)])
    with database.transaction(A) as unit:
        require(unit.compare_preferences(update(0)) == PreferenceSnapshot(**update(1).model_dump()))
    with database.transaction(A) as unit:
        require(unit.compare_preferences(update(0)) is None)
        require(unit.preference_snapshot().revision == 1)
    with database.transaction(B, read_only=True) as unit:
        require(unit.preference_snapshot().revision == 0)
    with migration_connection(result.target, result.secrets) as connection:
        execute(connection, "ALTER TRIGGER preference_revision DISABLE")
        try:
            execute(
                connection,
                "UPDATE workspace_preferences SET revision=9007199254740991 WHERE owner_id=:owner",
                owner=A.bytes,
            )
            connection.commit()
        finally:
            execute(connection, "ALTER TRIGGER preference_revision ENABLE")
        validate_schema(connection)
    with database.transaction(A) as unit:
        require(unit.compare_preferences(update(9007199254740991)) is None)
        require(unit.preference_snapshot().revision == 9007199254740991)
    with migration_connection(result.target, result.secrets) as connection:
        execute(connection, "DELETE FROM workspace_preferences")
        connection.commit()


def custody(pool: ClientPool, local: LocalRun) -> None:
    with pool.checkout() as connection:
        initial = physical(connection)
        enter(connection, str(A))
    for error in (ValueError, Interrupted):
        try:
            with pool.checkout() as connection:
                require(physical(connection) == initial and context(connection) == [(None,)])
                enter(connection, str(B))
                raise error()
        except error:
            pass
    with pool.checkout() as connection:
        require(physical(connection) == initial and context(connection) == [(None,)])
    try:
        with pool.checkout() as connection:
            execute(connection, "SELECT * FROM forbidden_unknown_relation")
    except OracleUnavailable:
        pass
    else:
        raise OracleUnavailable()
    with pool.checkout() as connection:
        replacement = physical(connection)
        require(replacement != initial and context(connection) == [(None,)])
    try:
        try:
            with pool.checkout() as connection:
                _sql(local, "GRANT CREATE TABLE TO TRADING_RUNTIME;")
        except OracleUnavailable:
            pass
        else:
            raise OracleUnavailable()
        try:
            with pool.checkout():
                raise AssertionError("Privilege drift admitted")
        except OracleUnavailable:
            pass
    finally:
        _sql(local, "REVOKE CREATE TABLE FROM TRADING_RUNTIME;")
    with pool.checkout() as connection:
        require(physical(connection) != replacement and context(connection) == [(None,)])


def concurrency(database: WorkspaceDatabase, result: BootstrapResult) -> None:
    barrier = Barrier(2, timeout=5)

    def contender() -> PreferenceSnapshot | None:
        barrier.wait()
        with database.transaction(A) as unit:
            return unit.compare_preferences(update(0))

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = [
            future.result(timeout=20)
            for future in (workers.submit(contender), workers.submit(contender))
        ]
    require(sum(outcome is not None for outcome in outcomes) == 1)
    with database.transaction(A) as unit:
        require(unit.preference_snapshot().revision == 1)

    # Hold the owner lock past WAIT 5. A wider test-only client deadline lets the
    # server lock-expiry response arrive before the production five-second client deadline.
    with migration_connection(result.target, result.secrets) as administrator:
        require(
            rows(
                administrator,
                "SELECT id FROM owners WHERE id=:owner FOR UPDATE WAIT 5",
                {"owner": A.bytes},
                limit=1,
            )
            == [(A.bytes,)]
        )
        with database.transaction(A) as unit:
            unit._connection.call_timeout = 10000
            try:
                with lock_expiry():
                    unit.compare_preferences(update(1))
            finally:
                unit._connection.call_timeout = 5000
            require(unit.preference_snapshot().revision == 1)
        administrator.rollback()

    def activate() -> None:
        with migration_connection(result.target, result.secrets) as connection:
            execute(connection, "UPDATE owners SET is_active=1 WHERE id=:owner", owner=A.bytes)
            connection.commit()

    started, finished = Event(), Event()

    def deactivate() -> None:
        with migration_connection(result.target, result.secrets) as connection:
            started.set()
            execute(connection, "UPDATE owners SET is_active=0 WHERE id=:owner", owner=A.bytes)
            connection.commit()
        finished.set()

    with ThreadPoolExecutor(max_workers=1) as workers:
        with database.transaction(A) as unit:
            require(unit.compare_preferences(update(1)) is not None)
            future = workers.submit(deactivate)
            require(started.wait(5) and not finished.wait(0.2))
        future.result(timeout=15)
    activate()

    started.clear()
    finished.clear()

    def denied_writer() -> None:
        try:
            with database.transaction(A) as unit:
                started.set()
                unit.compare_preferences(update(2))
        except OracleOwnerDenied:
            finished.set()
            return
        raise OracleUnavailable()

    with ThreadPoolExecutor(max_workers=1) as workers:
        with migration_connection(result.target, result.secrets) as connection:
            execute(connection, "UPDATE owners SET is_active=0 WHERE id=:owner", owner=A.bytes)
            future = workers.submit(denied_writer)
            require(started.wait(5) and not finished.wait(0.2))
            connection.commit()
        future.result(timeout=15)
    activate()
    with database.transaction(A, read_only=True) as unit:
        require(unit.preference_snapshot().revision == 2)
        with migration_connection(result.target, result.secrets) as connection:
            execute(connection, "UPDATE owners SET is_active=0 WHERE id=:owner", owner=A.bytes)
            connection.commit()
        # The existing read-only transaction retains its initial snapshot by design.
        require(unit.preference_snapshot().revision == 2)
    try:
        try:
            with database.transaction(A, read_only=True):
                raise AssertionError("New transaction admitted an inactive owner")
        except OracleOwnerDenied:
            pass
    finally:
        activate()


def check(local: LocalRun, result: BootstrapResult, complete: Callable[[str], None]) -> None:
    migrations(result)
    condition_projection(result)
    complete("migration")
    seed(result)
    complete("seed")
    unlock_clients(local, result)
    complete("unlock")
    runtime = ClientPool(result.target, result.secrets, "TRADING_RUNTIME")
    try:
        auth = ClientPool(result.target, result.secrets, "TRADING_AUTH")
        try:
            ownership(runtime, result)
            complete("ownership")
            identities(auth)
            complete("identity")
            database = WorkspaceDatabase(runtime)
            preferences(database, result)
            complete("preferences")
            custody(runtime, local)
            complete("custody")
            concurrency(database, result)
            complete("concurrency")
            with migration_connection(result.target, result.secrets) as connection:
                validate_schema(connection)
            complete("schema")
        finally:
            auth.close()
    finally:
        runtime.close()
    complete("clients_closed")
