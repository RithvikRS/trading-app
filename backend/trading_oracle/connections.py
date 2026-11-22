"""One bounded native pool with explicit custody, for the disposable local baseline only."""

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from typing import Any

import oracledb

from trading_oracle.bootstrap import MIGRATOR_PACKAGES, MIGRATOR_PRIVILEGES
from trading_oracle.contracts import ROLES, LocalTarget, OracleUnavailable, Role, RoleSecrets
from trading_oracle.local import ROOT, guarded
from trading_oracle.metadata import integer, require, rows
from trading_oracle.migrate import installation
from trading_oracle.schema import GRANTS, SCHEMA


def validate_role(connection: Any, role: Role) -> None:
    """Detect direct/role/system elevation before trusting a leased connection."""
    require(role in ROLES)
    identity = rows(
        connection,
        "SELECT SYS_CONTEXT('USERENV','SESSION_USER'),"
        "SYS_CONTEXT('USERENV','CURRENT_USER'),SYS_CONTEXT('USERENV','CURRENT_SCHEMA'),"
        "SYS_CONTEXT('USERENV','CON_NAME') FROM dual",
        limit=1,
    )
    require(identity == [(role, role, role, "FREEPDB1")])
    privileges = MIGRATOR_PRIVILEGES if role == "TRADING_MIGRATOR" else {"CREATE SESSION"}
    require(
        set(rows(connection, "SELECT privilege,admin_option FROM user_sys_privs"))
        == {(privilege, "NO") for privilege in privileges}
    )
    require(
        set(rows(connection, "SELECT privilege FROM session_privs"))
        == {(privilege,) for privilege in privileges}
    )
    require(not rows(connection, "SELECT granted_role FROM user_role_privs"))
    require(not rows(connection, "SELECT role FROM session_roles"))
    direct = set(
        rows(
            connection,
            "SELECT owner,table_name,privilege,grantor,grantable,hierarchy "
            "FROM user_tab_privs_recd",
        )
    )
    expected = {
        (SCHEMA, grant.object, grant.privilege, SCHEMA, "NO", "NO")
        for grant in GRANTS
        if grant.grantee == role and not grant.columns
    }
    if role == "TRADING_MIGRATOR":
        expected = {("SYS", package, "EXECUTE", "SYS", "NO", "NO") for package in MIGRATOR_PACKAGES}
    require(direct == expected)
    expected_columns = {
        (SCHEMA, grant.object, grant.privilege, column, SCHEMA, "NO")
        for grant in GRANTS
        if grant.grantee == role
        for column in grant.columns
    }
    require(
        set(
            rows(
                connection,
                "SELECT owner,table_name,privilege,column_name,grantor,grantable "
                "FROM user_col_privs_recd",
            )
        )
        == expected_columns
    )
    # PUBLIC or inherited role grants on the application schema may not widen this identity.
    require(
        set(
            rows(
                connection,
                "SELECT grantee,table_name,privilege,grantable FROM all_tab_privs_recd "
                "WHERE owner=:owner",
                {"owner": SCHEMA},
            )
        )
        == {
            (role, grant.object, grant.privilege, "NO")
            for grant in GRANTS
            if grant.grantee == role and not grant.columns
        }
    )
    require(
        set(
            rows(
                connection,
                "SELECT grantee,table_name,privilege,column_name,grantable "
                "FROM all_col_privs_recd WHERE owner=:owner",
                {"owner": SCHEMA},
            )
        )
        == {
            (role, grant.object, grant.privilege, column, "NO")
            for grant in GRANTS
            if grant.grantee == role
            for column in grant.columns
        }
    )
    if role != "TRADING_MIGRATOR":
        require(not rows(connection, "SELECT object_name FROM user_objects"))
        require(
            all(
                integer(row[0]) == 0
                for row in rows(connection, "SELECT max_bytes FROM user_ts_quotas")
            )
        )
    else:
        require(
            rows(connection, "SELECT tablespace_name,max_bytes FROM user_ts_quotas")
            == [("USERS", 8388608)]
        )


def _parameters(target: LocalTarget, secrets: RoleSecrets, role: Role) -> dict[str, Any]:
    target = LocalTarget.model_validate(target.model_dump())
    secrets = RoleSecrets.model_validate(secrets.model_dump())
    require(role in ROLES and sys.flags.isolated == 1 and sys.flags.no_site == 1)
    require(os.environ.get("ORA_SDTZ") == "UTC")
    require(
        not any(
            key.startswith(("ORACLE_", "TNS_", "NLS_")) or key in {"TWO_TASK", "LOCAL"}
            for key in os.environ
        )
    )
    config = guarded(ROOT / ".cache/oracle/runs" / target.run_id / "config")
    require(config.is_dir() and not list(config.iterdir()))
    require(oracledb.is_thin_mode())
    return {
        "user": role,
        "password": secrets.for_role(role).get_secret_value(),
        "host": "127.0.0.1",
        "port": target.port,
        "service_name": "FREEPDB1",
        "config_dir": str(config),
        "tcp_connect_timeout": 5,
        "retry_count": 0,
    }


def _server(connection: Any, target: LocalTarget, role: Role, *, ready: bool) -> None:
    require(connection.thin and connection.version.startswith("23.26.3."))
    require(connection.autocommit is False)
    validate_role(connection, role)
    installation(connection, target, ready=ready)


def _clean(connection: Any, target: LocalTarget, role: Role) -> None:
    """Rollback before clearing; a failed check never returns the connection to another owner."""
    connection.call_timeout = 5000
    connection.rollback()
    _server(connection, target, role, ready=True)
    if role == "TRADING_RUNTIME":
        with connection.cursor() as cursor:
            cursor.callproc("TRADING_MIGRATOR.OWNER_CONTEXT.CLEAR_OWNER")
    require(
        rows(connection, "SELECT SYS_CONTEXT('TRADING_OWNER_CTX','OWNER_ID') FROM dual", limit=1)
        == [(None,)]
    )
    with connection.cursor() as cursor:
        cursor.execute("BEGIN SYS.DBMS_SESSION.CLEAR_IDENTIFIER; END;")
        cursor.execute("ALTER SESSION SET TIME_ZONE = '+00:00'")
    require(
        rows(
            connection,
            "SELECT SYS_CONTEXT('USERENV','CLIENT_IDENTIFIER'),SESSIONTIMEZONE FROM dual",
            limit=1,
        )
        == [(None, "+00:00")]
    )
    require(connection.transaction_in_progress is False)


@contextmanager
def migration_connection(target: LocalTarget, secrets: RoleSecrets) -> Iterator[Any]:
    """Unpooled fixed migrator; DDL journal owns commits, and an exit never retries a commit."""
    connection = None
    try:
        connection = oracledb.connect(**_parameters(target, secrets, "TRADING_MIGRATOR"))
        connection.call_timeout = 5000
        _server(connection, target, "TRADING_MIGRATOR", ready=False)
        yield connection
    except oracledb.Error:
        raise OracleUnavailable() from None
    finally:
        if connection is not None:
            failed = False
            try:
                connection.rollback()
            except BaseException:
                failed = True
            try:
                connection.close()
            except BaseException:
                failed = True
            if failed:
                raise OracleUnavailable() from None


class ClientPool:
    """Synchronous custody only; never release while a worker still owns a connection."""

    def __init__(self, target: LocalTarget, secrets: RoleSecrets, role: Role) -> None:
        require(role in {"TRADING_RUNTIME", "TRADING_AUTH"})
        self.target = LocalTarget.model_validate(target.model_dump())
        self.role = role
        self._lock = Lock()
        self._active = 0
        self._closed = False
        self._admission_closed = False
        self._closing = False
        self._close_attempts = 0
        self._poisoned = False
        try:
            self._pool = oracledb.create_pool(
                **_parameters(self.target, secrets, role),
                min=0,
                max=2,
                increment=1,
                getmode=oracledb.POOL_GETMODE_TIMEDWAIT,
                wait_timeout=5000,
                timeout=60,
                homogeneous=True,
                ping_interval=60,
                ping_timeout=5000,
                max_lifetime_session=300,
            )
        except oracledb.Error:
            raise OracleUnavailable() from None

    def _drop(self, connection: Any) -> None:
        try:
            self._pool.drop(connection)
        except BaseException:
            with self._lock:
                self._poisoned = True
            raise OracleUnavailable() from None

    @contextmanager
    def checkout(self) -> Iterator[Any]:
        with self._lock:
            require(not self._admission_closed and not self._closed and not self._poisoned)
            self._active += 1
        connection = None
        admitted = False
        driver_failure = False
        try:
            try:
                connection = self._pool.acquire()
                _clean(connection, self.target, self.role)
                with self._lock:
                    require(not self._admission_closed and not self._closed and not self._poisoned)
                    admitted = True
                yield connection
            except oracledb.Error:
                driver_failure = True
                raise OracleUnavailable() from None
            finally:
                if connection is not None:
                    if not admitted or driver_failure:
                        self._drop(connection)
                    else:
                        try:
                            _clean(connection, self.target, self.role)
                            self._pool.release(connection)
                        except BaseException:
                            self._drop(connection)
                            raise OracleUnavailable() from None
        finally:
            with self._lock:
                self._active -= 1

    def close(self) -> None:
        with self._lock:
            require(self._active == 0)
            if self._closed:
                return
            require(not self._closing and self._close_attempts < 2)
            self._admission_closed = True
            self._closing = True
            self._close_attempts += 1
            poisoned = self._poisoned
        try:
            self._pool.close(force=poisoned)
        except BaseException:
            with self._lock:
                self._closing = False
            raise OracleUnavailable() from None
        with self._lock:
            self._closing = False
            self._closed = True


def oracle_error_code(error: oracledb.Error) -> int | None:
    value = getattr(error.args[0], "code", None) if error.args else None
    return value if type(value) is int else None
