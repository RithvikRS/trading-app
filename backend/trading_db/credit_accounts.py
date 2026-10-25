"""Owned credit billing-account identity, independent from asset and bank accounts."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import URL, text
from sqlalchemy.exc import SQLAlchemyError

from trading_db.connections import DatabaseFailure
from trading_db.workspace import WorkspaceDatabase, WorkspaceTransaction

MAX_RECORDS = 1000
MAX_REVISION = 9007199254740991


class CreditAccountUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__("Credit account operation is unavailable or conflicts with the revision.")


class CreditAccountDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)
    issuer: Literal["hdfc"] = "hdfc"
    billing_currency: Literal["INR"] = "INR"
    label: str = Field(pattern=r"^[A-Za-z][A-Za-z .()-]{0,63}$", repr=False)


@dataclass(frozen=True, repr=False)
class CreditAccount:
    id: UUID
    definition: CreditAccountDefinition
    revision: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


def identifier(value: UUID) -> UUID:
    if type(value) is not UUID or not value.int:
        raise CreditAccountUnavailable()
    return value


def revision(value: int) -> int:
    if type(value) is not int or not 1 <= value < MAX_REVISION:
        raise CreditAccountUnavailable()
    return value


def page(limit: int, after: UUID | None) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise CreditAccountUnavailable()
    if after is not None:
        identifier(after)


class CreditAccountTransaction:
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
            raise CreditAccountUnavailable() from None

    @staticmethod
    def _account(row: Any) -> CreditAccount:
        return CreditAccount(
            row["id"],
            CreditAccountDefinition(
                issuer=row["issuer"], billing_currency=row["billing_currency"], label=row["label"]
            ),
            row["revision"],
            row["created_at"],
            row["updated_at"],
            row["archived_at"],
        )

    def get(self, account_id: UUID) -> CreditAccount | None:
        row = (
            self._execute(
                "SELECT id,issuer,billing_currency,label,revision,"
                "created_at,updated_at,archived_at "
                "FROM app.credit_billing_accounts WHERE owner_id=:owner AND id=:id",
                id=identifier(account_id),
            )
            .mappings()
            .one_or_none()
        )
        return self._account(row) if row else None

    def list(self, *, limit: int = 25, after: UUID | None = None) -> tuple[CreditAccount, ...]:
        page(limit, after)
        rows = self._execute(
            "SELECT id,issuer,billing_currency,label,revision,created_at,updated_at,archived_at "
            "FROM app.credit_billing_accounts WHERE owner_id=:owner "
            "AND (CAST(:after AS uuid) IS NULL OR id>CAST(:after AS uuid)) "
            "ORDER BY id LIMIT :limit",
            after=after,
            limit=limit,
        ).mappings()
        return tuple(self._account(row) for row in rows)

    def create(self, definition: CreditAccountDefinition) -> CreditAccount:
        if type(definition) is not CreditAccountDefinition:
            raise CreditAccountUnavailable()
        try:
            valid = CreditAccountDefinition.model_validate(definition.model_dump(warnings=False))
        except ValidationError:
            raise CreditAccountUnavailable() from None
        with self._write():
            count = self._execute(
                "SELECT count(*) FROM app.credit_billing_accounts WHERE owner_id=:owner"
            ).scalar_one()
            if count >= MAX_RECORDS:
                raise CreditAccountUnavailable()
            account_id = uuid4()
            self._execute(
                "INSERT INTO app.credit_billing_accounts "
                "(owner_id,id,issuer,billing_currency,label) "
                "VALUES (:owner,:id,:issuer,:billing_currency,:label)",
                id=account_id,
                **valid.model_dump(),
            )
            result = self.get(account_id)
            assert result is not None
            return result

    def archive(self, account_id: UUID, *, expected_revision: int) -> CreditAccount:
        account_id = identifier(account_id)
        expected = revision(expected_revision)
        with self._write():
            row = self._execute(
                "UPDATE app.credit_billing_accounts SET archived_at=statement_timestamp() "
                "WHERE owner_id=:owner AND id=:id AND revision=:revision AND archived_at IS NULL "
                "RETURNING id",
                id=account_id,
                revision=expected,
            ).one_or_none()
            if row is None:
                raise CreditAccountUnavailable()
            result = self.get(account_id)
            assert result is not None
            return result


class CreditAccountDatabase:
    """Internal service: a caller must independently authenticate the owner UUID."""

    def __init__(self, url: URL, project: str) -> None:
        self._workspace = WorkspaceDatabase(url, project)

    def close(self) -> None:
        self._workspace.close()

    @contextmanager
    def transaction(self, owner_id: UUID) -> Iterator[CreditAccountTransaction]:
        try:
            with self._workspace.transaction(owner_id) as unit:
                yield CreditAccountTransaction(unit)
        except SQLAlchemyError:
            raise CreditAccountUnavailable() from None
