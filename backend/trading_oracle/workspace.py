"""Revisioned preferences behind a trusted owner context and synchronous connection custody."""

from collections.abc import Iterator
from contextlib import contextmanager
from threading import get_ident
from typing import Any
from uuid import UUID

import oracledb

from trading_db.workspace import Preferences, PreferenceSnapshot, PreferenceUpdate
from trading_oracle.connections import ClientPool, oracle_error_code
from trading_oracle.contracts import MAX_REVISION, OracleOwnerDenied, owner_bytes
from trading_oracle.metadata import integer, require, rows


def snapshot(value: tuple[Any, ...]) -> PreferenceSnapshot:
    require(len(value) == 4)
    theme, currency, masked, revision = value
    mask = integer(masked)
    number = integer(revision)
    require(mask in {0, 1} and 1 <= number <= MAX_REVISION)
    return PreferenceSnapshot.model_validate(
        {
            "theme": theme,
            "display_currency": currency,
            "amount_masked": bool(mask),
            "revision": number,
        }
    )


class WorkspaceTransaction:
    """No owner override or raw SQL; a closed unit cannot reopen or move between threads."""

    def __init__(self, connection: Any, owner: UUID, *, read_only: bool) -> None:
        self._connection = connection
        self._owner = owner
        self._bytes = owner_bytes(owner)
        self._open = True
        self._read_only = read_only
        self._thread = get_ident()

    def _require_open(self) -> None:
        require(self._open and self._thread == get_ident())
        require(
            rows(
                self._connection,
                "SELECT SYS_CONTEXT('TRADING_OWNER_CTX','OWNER_ID') FROM dual",
                limit=1,
            )
            == [(self._owner.hex,)]
        )
        active = rows(
            self._connection,
            "SELECT id FROM trading_migrator.owners WHERE id=:owner AND is_active=1",
            {"owner": self._bytes},
            limit=1,
        )
        if active != [(self._bytes,)]:
            raise OracleOwnerDenied()

    def _snapshot(self) -> PreferenceSnapshot:
        found = rows(
            self._connection,
            "SELECT theme,display_currency,amount_masked,revision "
            "FROM trading_migrator.workspace_preferences WHERE owner_id=:owner",
            {"owner": self._bytes},
            limit=1,
        )
        return snapshot(found[0]) if found else PreferenceSnapshot()

    def preference_snapshot(self) -> PreferenceSnapshot:
        self._require_open()
        return self._snapshot()

    def get_preferences(self) -> Preferences | None:
        found = self.preference_snapshot()
        return (
            Preferences.model_validate(found.model_dump(exclude={"revision"}))
            if found.revision
            else None
        )

    def compare_preferences(self, update: PreferenceUpdate) -> PreferenceSnapshot | None:
        self._require_open()
        require(not self._read_only)
        validated = PreferenceUpdate.model_validate(update.model_dump(warnings=False))
        # The same owner lock serializes preference writers and administrative deactivation.
        active = rows(
            self._connection,
            "SELECT id FROM trading_migrator.owners "
            "WHERE id=:owner AND is_active=1 FOR UPDATE WAIT 5",
            {"owner": self._bytes},
            limit=1,
        )
        if active != [(self._bytes,)]:
            raise OracleOwnerDenied()
        # Recheck after a possible wait: the statement snapshot may predate deactivation.
        self._require_open()
        previous = self._snapshot()
        if previous.revision != validated.revision or previous.revision == MAX_REVISION:
            return None
        parameters = {
            "owner": self._bytes,
            "theme": validated.theme,
            "currency": validated.display_currency,
            "masked": int(validated.amount_masked),
        }
        statement = (
            "INSERT INTO trading_migrator.workspace_preferences"
            "(owner_id,theme,display_currency,amount_masked) "
            "VALUES (:owner,:theme,:currency,:masked)"
            if previous.revision == 0
            else "UPDATE trading_migrator.workspace_preferences SET "
            "theme=:theme,display_currency=:currency,amount_masked=:masked WHERE owner_id=:owner"
        )
        with self._connection.cursor() as cursor:
            cursor.execute(statement, parameters)
            require(cursor.rowcount == 1)
        saved = self._snapshot()
        require(saved.revision == previous.revision + 1)
        require(
            saved.model_dump(exclude={"revision"}) == validated.model_dump(exclude={"revision"})
        )
        return saved


class WorkspaceDatabase:
    def __init__(self, pool: ClientPool) -> None:
        require(pool.role == "TRADING_RUNTIME")
        self._pool = pool

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def transaction(
        self, owner_id: UUID, *, read_only: bool = False
    ) -> Iterator[WorkspaceTransaction]:
        owner_bytes(owner_id)
        require(type(read_only) is bool)
        unit = None
        try:
            with self._pool.checkout() as connection:
                try:
                    with connection.cursor() as cursor:
                        if read_only:
                            cursor.execute("SET TRANSACTION READ ONLY")
                        cursor.callproc(
                            "TRADING_MIGRATOR.OWNER_CONTEXT.ENTER_OWNER", [str(owner_id)]
                        )
                except oracledb.Error as error:
                    if oracle_error_code(error) == 20001:
                        raise OracleOwnerDenied() from None
                    raise
                unit = WorkspaceTransaction(connection, owner_id, read_only=read_only)
                try:
                    unit._require_open()
                    yield unit
                finally:
                    unit._open = False
                # Never retry a failed/uncertain commit. The pool drops a driver-failed connection.
                connection.commit()
        finally:
            if unit is not None:
                unit._open = False
