"""Internal account services; callers supply an independently authenticated owner context."""

import hashlib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import URL, text
from sqlalchemy.exc import SQLAlchemyError

from trading_db.account_keys import NAMESPACES, ReferenceKeys, ReferenceUnavailable, reference
from trading_db.connections import DatabaseFailure
from trading_db.workspace import WorkspaceDatabase, WorkspaceTransaction

MAX_RECORDS = 1000
MAX_REVISION = 9007199254740991


class AccountUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__("Account operation is unavailable or conflicts with the current revision.")


class AccountDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)
    kind: Literal["bank", "brokerage", "mutual_fund", "employee_stock"]
    institution: Literal["hdfc", "sbi", "indmoney", "fund_registrar", "ubs"]
    market: Literal["IN", "US"]
    label: str = Field(pattern=r"^[A-Za-z][A-Za-z .()-]{0,63}$", repr=False)
    currencies: tuple[Literal["INR", "USD"], ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def combination(self) -> AccountDefinition:
        valid = {
            ("bank", "hdfc", "IN"),
            ("bank", "sbi", "IN"),
            ("brokerage", "indmoney", "IN"),
            ("brokerage", "indmoney", "US"),
            ("mutual_fund", "fund_registrar", "IN"),
            ("employee_stock", "ubs", "US"),
        }
        if (self.kind, self.institution, self.market) not in valid or len(
            set(self.currencies)
        ) != len(self.currencies):
            raise ValueError("Unsupported account definition.")
        return self


@dataclass(frozen=True, repr=False)
class Account:
    id: UUID
    definition: AccountDefinition
    revision: int
    archived_at: datetime | None


@dataclass(frozen=True)
class SourceAccount:
    id: UUID
    namespace: str
    revision: int


@dataclass(frozen=True)
class MappingRevision:
    source_id: UUID
    revision: int
    account_id: UUID | None
    reason: str


def identifier(value: UUID) -> UUID:
    if not isinstance(value, UUID) or not value.int:
        raise AccountUnavailable()
    return value


def revision(value: int, *, initial: bool = False) -> int:
    if type(value) is not int or not (0 if initial else 1) <= value < MAX_REVISION:
        raise AccountUnavailable()
    return value


def page(limit: int, after: UUID | None) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise AccountUnavailable()
    if after is not None:
        identifier(after)


class AccountTransaction:
    def __init__(self, unit: WorkspaceTransaction, keys: ReferenceKeys | None) -> None:
        self._unit = unit
        self._keys = keys

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
                # Serializes account/mapping/key changes for this owner; no external I/O under lock.
                lock = int.from_bytes(
                    hashlib.sha256(b"accounts/v1" + self._unit._owner_id.bytes).digest()[:8],
                    "big",
                    signed=True,
                )
                self._execute("SELECT pg_advisory_xact_lock(:lock)", lock=lock)
                yield
        except SQLAlchemyError:
            raise AccountUnavailable() from None

    def _budget(self, table: str) -> None:
        # All callers pass committed table names, never request input.
        count = self._execute(
            f"SELECT count(*) FROM app.{table} WHERE owner_id=:owner"
        ).scalar_one()
        if count >= MAX_RECORDS:
            raise AccountUnavailable()

    def _account(self, row: Any) -> Account:
        currencies = tuple(
            self._execute(
                "SELECT currency FROM app.account_currencies "
                "WHERE owner_id=:owner AND account_id=:id ORDER BY currency",
                id=row["id"],
            ).scalars()
        )
        return Account(
            row["id"],
            AccountDefinition(
                kind=row["kind"],
                institution=row["institution"],
                market=row["market"],
                label=row["label"],
                currencies=currencies,
            ),
            row["revision"],
            row["archived_at"],
        )

    def get(self, account_id: UUID) -> Account | None:
        row = (
            self._execute(
                "SELECT id,kind,institution,market,label,revision,archived_at "
                "FROM app.financial_accounts WHERE owner_id=:owner AND id=:id",
                id=identifier(account_id),
            )
            .mappings()
            .one_or_none()
        )
        return self._account(row) if row else None

    def list(self, *, limit: int = 25, after: UUID | None = None) -> tuple[Account, ...]:
        page(limit, after)
        rows = self._execute(
            "SELECT id,kind,institution,market,label,revision,archived_at "
            "FROM app.financial_accounts "
            "WHERE owner_id=:owner AND (CAST(:after AS uuid) IS NULL OR id>CAST(:after AS uuid)) "
            "ORDER BY id LIMIT :limit",
            after=after,
            limit=limit,
        ).mappings()
        return tuple(self._account(row) for row in rows)

    def create(self, definition: AccountDefinition) -> Account:
        valid = AccountDefinition.model_validate(definition.model_dump(warnings=False))
        with self._write():
            self._budget("financial_accounts")
            account_id = uuid4()
            self._execute(
                "INSERT INTO app.financial_accounts (owner_id,id,kind,institution,market,label) "
                "VALUES (:owner,:id,:kind,:institution,:market,:label)",
                id=account_id,
                **valid.model_dump(exclude={"currencies"}),
            )
            for currency in valid.currencies:
                self._execute(
                    "INSERT INTO app.account_currencies (owner_id,account_id,currency) "
                    "VALUES (:owner,:id,:currency)",
                    id=account_id,
                    currency=currency,
                )
            result = self.get(account_id)
            assert result is not None
            return result

    def archive(self, account_id: UUID, *, expected_revision: int) -> Account:
        with self._write():
            row = self._execute(
                "UPDATE app.financial_accounts SET archived_at=statement_timestamp() "
                "WHERE owner_id=:owner AND id=:id AND revision=:revision AND archived_at IS NULL "
                "RETURNING id",
                id=identifier(account_id),
                revision=revision(expected_revision),
            ).one_or_none()
            if row is None:
                raise AccountUnavailable()
            result = self.get(account_id)
            assert result is not None
            return result

    def _source_rows(self) -> Sequence[Any]:
        rows = (
            self._execute(
                "SELECT * FROM app.source_accounts WHERE owner_id=:owner ORDER BY id LIMIT :limit",
                limit=MAX_RECORDS + 1,
            )
            .mappings()
            .all()
        )
        if len(rows) > MAX_RECORDS:
            raise AccountUnavailable()
        return list(rows)

    def _require_keys(self, rows: Sequence[Any]) -> ReferenceKeys:
        if self._keys is None:
            raise ReferenceUnavailable()
        for version, check in {(row["key_version"], row["key_check"]) for row in rows}:
            self._keys.check(self._unit._owner_id, version, check)
        return self._keys

    def source(self, namespace: str, external_reference: str) -> SourceAccount:
        """Find or create exactly this source identity; labels never participate in matching."""
        if type(namespace) is not str or namespace not in NAMESPACES:
            raise AccountUnavailable()
        reference(external_reference)
        with self._write():
            rows = self._source_rows()
            keys = self._require_keys(rows)
            # Authenticate the lookup index too: a damaged fingerprint must not turn a
            # previously known reference into a new source on a lookup miss.
            values = [(row, keys.open(row)) for row in rows]
            identities = [(row["namespace"], value) for row, value in values]
            if len(set(identities)) != len(identities):
                raise AccountUnavailable()
            matches = [
                (row, value)
                for row, value in values
                if row["namespace"] == namespace
                and row["fingerprint"]
                == keys.fingerprint(
                    self._unit._owner_id, namespace, external_reference, row["key_version"]
                )
            ]
            if len(matches) > 1:
                raise AccountUnavailable()
            if matches:
                row, value = matches[0]
                if value != external_reference:
                    raise AccountUnavailable()
                return SourceAccount(row["id"], namespace, row["revision"])
            if len(rows) >= MAX_RECORDS:
                raise AccountUnavailable()
            source_id = uuid4()
            self._execute(
                "INSERT INTO app.source_accounts "
                "(owner_id,id,namespace,key_version,key_check,fingerprint,encrypted_reference) "
                "VALUES (:owner,:id,:namespace,:key_version,:key_check,:fingerprint,"
                ":encrypted_reference)",
                id=source_id,
                namespace=namespace,
                **keys.seal(self._unit._owner_id, source_id, namespace, external_reference),
            )
            return SourceAccount(source_id, namespace, 1)

    def sources(self, *, limit: int = 25, after: UUID | None = None) -> tuple[SourceAccount, ...]:
        page(limit, after)
        rows = self._execute(
            "SELECT id,namespace,revision FROM app.source_accounts WHERE owner_id=:owner "
            "AND (CAST(:after AS uuid) IS NULL OR id>CAST(:after AS uuid)) "
            "ORDER BY id LIMIT :limit",
            after=after,
            limit=limit,
        ).mappings()
        return tuple(SourceAccount(**row) for row in rows)

    def mapping(self, source_id: UUID) -> MappingRevision | None:
        row = (
            self._execute(
                "SELECT source_id,revision,account_id,reason FROM app.source_account_mappings "
                "WHERE owner_id=:owner AND source_id=:id ORDER BY revision DESC LIMIT 1",
                id=identifier(source_id),
            )
            .mappings()
            .one_or_none()
        )
        return MappingRevision(**row) if row else None

    def history(
        self, source_id: UUID, *, limit: int = 25, before: int | None = None
    ) -> tuple[MappingRevision, ...]:
        page(limit, None)
        if before is not None:
            revision(before)
        rows = self._execute(
            "SELECT source_id,revision,account_id,reason FROM app.source_account_mappings "
            "WHERE owner_id=:owner AND source_id=:id "
            "AND (CAST(:before AS bigint) IS NULL OR revision<:before) "
            "ORDER BY revision DESC LIMIT :limit",
            id=identifier(source_id),
            before=before,
            limit=limit,
        ).mappings()
        return tuple(MappingRevision(**row) for row in rows)

    def map(
        self, source_id: UUID, account_id: UUID | None, *, expected_revision: int
    ) -> MappingRevision:
        expected = revision(expected_revision, initial=True)
        identifier(source_id)
        if account_id is not None:
            identifier(account_id)
        with self._write():
            present = self._execute(
                "SELECT id FROM app.source_accounts WHERE owner_id=:owner AND id=:id",
                id=source_id,
            ).one_or_none()
            current = self.mapping(source_id)
            if present is None or (current.revision if current else 0) != expected:
                raise AccountUnavailable()
            if current and current.account_id == account_id:
                return current
            if account_id is None and current is None:
                raise AccountUnavailable()
            self._budget("source_account_mappings")
            result = MappingRevision(
                source_id,
                expected + 1,
                account_id,
                "unlinked" if account_id is None else "initial" if expected == 0 else "correction",
            )
            self._execute(
                "INSERT INTO app.source_account_mappings "
                "(owner_id,source_id,revision,previous_revision,account_id,reason) "
                "VALUES (:owner,:source_id,:revision,:previous,:account_id,:reason)",
                source_id=source_id,
                revision=result.revision,
                previous=expected or None,
                account_id=account_id,
                reason=result.reason,
            )
            return result

    def rotate_references(self) -> int:
        with self._write():
            rows = self._source_rows()
            keys = self._require_keys(rows)
            changed = 0
            # Validate all ciphertext first; the savepoint also rolls back conflicts.
            values = [(row, keys.open(row)) for row in rows]
            identities = [(row["namespace"], value) for row, value in values]
            if len(set(identities)) != len(identities):
                raise AccountUnavailable()
            for row, value in values:
                if row["key_version"] == keys.active:
                    continue
                self._execute(
                    "UPDATE app.source_accounts SET key_version=:key_version,key_check=:key_check,"
                    "fingerprint=:fingerprint,encrypted_reference=:encrypted_reference "
                    "WHERE owner_id=:owner AND id=:id",
                    id=row["id"],
                    **keys.seal(self._unit._owner_id, row["id"], row["namespace"], value),
                )
                changed += 1
            return changed


class AccountDatabase:
    """No route or enrollment bypass; authentication remains the caller's responsibility."""

    def __init__(self, url: URL, project: str, keys: ReferenceKeys | None = None) -> None:
        self._workspace = WorkspaceDatabase(url, project)
        self._keys = keys

    def close(self) -> None:
        self._workspace.close()

    @contextmanager
    def transaction(self, owner_id: UUID) -> Iterator[AccountTransaction]:
        try:
            with self._workspace.transaction(owner_id) as unit:
                yield AccountTransaction(unit, self._keys)
        except SQLAlchemyError:
            raise AccountUnavailable() from None
