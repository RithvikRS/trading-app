"""Opaque credit-source streams and immutable billing-account mapping decisions."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import URL, text
from sqlalchemy.exc import SQLAlchemyError

from trading_db.connections import DatabaseFailure
from trading_db.workspace import WorkspaceDatabase, WorkspaceTransaction

MAX_RECORDS = 1000
MAX_REVISION = 9007199254740991
FAMILY = "hdfc_credit_statement"


class CreditSourceUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__("Credit source operation is unavailable or conflicts with the revision.")


@dataclass(frozen=True, slots=True, repr=False)
class CreditSource:
    id: UUID
    family: str
    created_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class CreditMapping:
    source_id: UUID
    revision: int
    previous_revision: int | None
    account_id: UUID | None
    reason: Literal["initial", "correction", "unlinked"]
    created_at: datetime


def identifier(value: UUID) -> UUID:
    if type(value) is not UUID or not value.int:
        raise CreditSourceUnavailable()
    return value


def revision(value: int, *, initial: bool = False) -> int:
    if type(value) is not int or not (0 if initial else 1) <= value < MAX_REVISION:
        raise CreditSourceUnavailable()
    return value


def page(limit: int, after: UUID | None = None) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise CreditSourceUnavailable()
    if after is not None:
        identifier(after)


class CreditSourceTransaction:
    def __init__(self, unit: WorkspaceTransaction) -> None:
        self._unit = unit

    def _execute(self, sql: str, **parameters: Any) -> Any:
        self._unit._require_open()
        return self._unit._connection.execute(
            text(sql), {"owner": self._unit._owner_id, **parameters}
        )

    @contextmanager
    def _write(self) -> Iterator[None]:
        self._unit._require_open()
        try:
            with self._unit._connection.begin_nested():
                self._execute(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended('credit-accounts/v1:' || CAST(:owner AS text), 0))"
                )
                yield
        except SQLAlchemyError:
            raise CreditSourceUnavailable() from None

    def create(self) -> CreditSource:
        """Create a distinct application stream, never a matched issuer identity."""
        with self._write():
            source_id = uuid4()
            row = (
                self._execute(
                    "INSERT INTO app.credit_source_handles (owner_id,id,family) "
                    "VALUES (:owner,:id,:family) RETURNING id,family,created_at",
                    id=source_id,
                    family=FAMILY,
                )
                .mappings()
                .one()
            )
            return CreditSource(**row)

    def get(self, source_id: UUID) -> CreditSource | None:
        row = (
            self._execute(
                "SELECT id,family,created_at FROM app.credit_source_handles "
                "WHERE owner_id=:owner AND id=:id",
                id=identifier(source_id),
            )
            .mappings()
            .one_or_none()
        )
        return CreditSource(**row) if row else None

    def list(self, *, limit: int = 25, after: UUID | None = None) -> tuple[CreditSource, ...]:
        page(limit, after)
        rows = self._execute(
            "SELECT id,family,created_at FROM app.credit_source_handles WHERE owner_id=:owner "
            "AND (CAST(:after AS uuid) IS NULL OR id>CAST(:after AS uuid)) "
            "ORDER BY id LIMIT :limit",
            after=after,
            limit=limit,
        ).mappings()
        return tuple(CreditSource(**row) for row in rows)

    def history(
        self, source_id: UUID, *, limit: int = 25, before: int | None = None
    ) -> tuple[CreditMapping, ...]:
        source_id = identifier(source_id)
        page(limit)
        if before is not None:
            revision(before)
        rows = self._execute(
            "SELECT source_id,revision,previous_revision,account_id,reason,created_at "
            "FROM app.credit_source_account_mappings WHERE owner_id=:owner AND source_id=:id "
            "AND (CAST(:before AS bigint) IS NULL OR revision<:before) "
            "ORDER BY revision DESC LIMIT :limit",
            id=source_id,
            before=before,
            limit=limit,
        ).mappings()
        return tuple(CreditMapping(**row) for row in rows)

    def mapping(self, source_id: UUID) -> CreditMapping | None:
        """Return retained intent, including an archived target or explicit unlink."""
        rows = self.history(source_id, limit=1)
        return rows[0] if rows else None

    def resolve(self, source_id: UUID) -> CreditMapping | None:
        """One-statement active binding read; not a future authorization to post."""
        row = (
            self._execute(
                "SELECT m.source_id,m.revision,m.previous_revision,m.account_id,"
                "m.reason,m.created_at "
                "FROM app.credit_source_account_mappings m JOIN app.credit_billing_accounts a "
                "ON a.owner_id=m.owner_id AND a.id=m.account_id WHERE m.owner_id=:owner "
                "AND m.source_id=:id AND a.archived_at IS NULL AND NOT EXISTS ("
                "SELECT 1 FROM app.credit_source_account_mappings n WHERE n.owner_id=m.owner_id "
                "AND n.source_id=m.source_id AND n.revision>m.revision)",
                id=identifier(source_id),
            )
            .mappings()
            .one_or_none()
        )
        return CreditMapping(**row) if row else None

    def map(
        self, source_id: UUID, account_id: UUID | None, *, expected_revision: int
    ) -> CreditMapping:
        source_id = identifier(source_id)
        expected = revision(expected_revision, initial=True)
        if account_id is not None:
            identifier(account_id)
        with self._write():
            if self.get(source_id) is None:
                raise CreditSourceUnavailable()
            current = self.mapping(source_id)
            if (current.revision if current else 0) != expected:
                raise CreditSourceUnavailable()
            if account_id is not None:
                account = self._execute(
                    "SELECT archived_at FROM app.credit_billing_accounts "
                    "WHERE owner_id=:owner AND id=:id FOR UPDATE",
                    id=account_id,
                ).one_or_none()
                if account is None or account.archived_at is not None:
                    raise CreditSourceUnavailable()
            elif current is None:
                raise CreditSourceUnavailable()
            if current and current.account_id == account_id:
                return current
            reason = (
                "unlinked" if account_id is None else "initial" if expected == 0 else "correction"
            )
            row = (
                self._execute(
                    "INSERT INTO app.credit_source_account_mappings "
                    "(owner_id,source_id,revision,previous_revision,account_id,reason) "
                    "VALUES (:owner,:source,:revision,:previous,:account,:reason) "
                    "RETURNING source_id,revision,previous_revision,account_id,reason,created_at",
                    source=source_id,
                    revision=expected + 1,
                    previous=expected if expected else None,
                    account=account_id,
                    reason=reason,
                )
                .mappings()
                .one()
            )
            return CreditMapping(**row)


class CreditSourceDatabase:
    """Internal service requiring an independently authenticated owner UUID."""

    def __init__(self, url: URL, project: str) -> None:
        self._workspace = WorkspaceDatabase(url, project)

    def close(self) -> None:
        self._workspace.close()

    @contextmanager
    def transaction(self, owner_id: UUID) -> Iterator[CreditSourceTransaction]:
        try:
            with self._workspace.transaction(owner_id) as unit:
                yield CreditSourceTransaction(unit)
        except SQLAlchemyError:
            raise CreditSourceUnavailable() from None
