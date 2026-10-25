"""Owned immutable credit entry interpretations; no posting or withdrawal."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import URL, text
from sqlalchemy.exc import SQLAlchemyError

from trading_api.credit_cards import CardEntryValues
from trading_api.finance import Currency, FinancialDate, FinancialValue
from trading_db.connections import DatabaseFailure
from trading_db.workspace import WorkspaceDatabase, WorkspaceTransaction

MAX_RECORDS = 1000
MAX_REVISION = 9007199254740991
DAYS = ("transaction_date", "posting_date")
VALUE_COLUMNS = (
    "role",
    "treatment",
    *DAYS,
    "billing_source",
    "billing_amount",
    "billing_missing",
    "original_source",
    "original_amount",
    "original_missing",
    "original_currency",
)


class CreditEntryUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__(
            "Credit entry operation is unavailable or conflicts with retained evidence."
        )


def new_entry_id() -> UUID:
    """Allocate server-side before record(); retain this ID across explicit retries."""
    return uuid4()


def identifier(value: UUID) -> UUID:
    if type(value) is not UUID or not value.int:
        raise CreditEntryUnavailable()
    return value


def revision(value: int, *, initial: bool = False) -> int:
    if type(value) is not int or not (0 if initial else 1) <= value <= MAX_REVISION:
        raise CreditEntryUnavailable()
    return value


def validate_entry(value: CardEntryValues) -> CardEntryValues:
    """Revalidate every nested value/cache privately without repairing tampering."""
    try:
        if type(value) is not CardEntryValues:
            raise CreditEntryUnavailable()
        fields: dict[str, Any] = {}
        for name in DAYS:
            item = getattr(value, name)
            if item is None:
                fields[name] = None
                continue
            if type(item) is not FinancialDate:
                raise CreditEntryUnavailable()
            parsed_day = FinancialDate(item.source)
            if type(item.value) is not date or item.value != parsed_day.value:
                raise CreditEntryUnavailable()
            fields[name] = parsed_day
        for name in ("billing_amount", "original_amount"):
            item = getattr(value, name)
            if item is None and name == "original_amount":
                fields[name] = None
                continue
            if type(item) is not FinancialValue:
                raise CreditEntryUnavailable()
            parsed = FinancialValue(
                item.kind,
                item.source,
                currency=item.currency,
                meaning=item.meaning,
                base_currency=item.base_currency,
                quote_currency=item.quote_currency,
                missing_reason=item.missing_reason,
            )
            if parsed.value is None:
                if item.value is not None:
                    raise CreditEntryUnavailable()
            elif (
                type(item.value) is not Decimal or item.value.as_tuple() != parsed.value.as_tuple()
            ):
                raise CreditEntryUnavailable()
            fields[name] = parsed
        return CardEntryValues(role=value.role, treatment=value.treatment, **fields)
    except AttributeError, TypeError, ValueError:
        raise CreditEntryUnavailable() from None


@dataclass(frozen=True, slots=True, repr=False)
class EntryEvidence:
    id: UUID
    revision: int
    previous_revision: int | None
    source_id: UUID
    mapping_revision: int
    account_id: UUID
    created_at: datetime
    values: CardEntryValues


SELECT = (
    "SELECT o.id,o.revision,o.previous_revision,o.source_id,o.mapping_revision,o.account_id,"
    "o.created_at,"
    + ",".join("v." + name for name in VALUE_COLUMNS)
    + " FROM app.credit_evidence_observations o JOIN app.credit_entry_values v "
    "ON v.owner_id=o.owner_id AND v.observation_id=o.id AND v.revision=o.revision "
    "WHERE o.owner_id=:owner "
)


def _cash(row: Any, prefix: str, currency: Currency) -> FinancialValue:
    value = FinancialValue(
        "cash", row[prefix + "_source"], currency=currency, missing_reason=row[prefix + "_missing"]
    )
    amount = row[prefix + "_amount"]
    if value.value is None:
        if amount is not None:
            raise CreditEntryUnavailable()
    elif type(amount) is not Decimal or not amount.is_finite() or amount != value.value:
        raise CreditEntryUnavailable()
    return value


def _entry(row: Any) -> CardEntryValues:
    fields: dict[str, Any] = {
        name: FinancialDate(row[name].isoformat()) if row[name] is not None else None
        for name in DAYS
    }
    original = None
    if row["original_currency"] is None:
        if any(row["original_" + part] is not None for part in ("source", "amount", "missing")):
            raise CreditEntryUnavailable()
    else:
        original = _cash(row, "original", row["original_currency"])
    return validate_entry(
        CardEntryValues(
            role=row["role"],
            treatment=row["treatment"],
            billing_amount=_cash(row, "billing", "INR"),
            original_amount=original,
            **fields,
        )
    )


def _parameters(values: CardEntryValues) -> dict[str, Any]:
    result: dict[str, Any] = {"role": values.role, "treatment": values.treatment}
    for name in DAYS:
        day = getattr(values, name)
        result[name] = day.value if day is not None else None
    for prefix, value in (("billing", values.billing_amount), ("original", values.original_amount)):
        result.update(
            {
                prefix + "_source": value.source if value is not None else None,
                prefix + "_amount": value.value if value is not None else None,
                prefix + "_missing": value.missing_reason if value is not None else None,
            }
        )
    result["original_currency"] = (
        values.original_amount.currency if values.original_amount is not None else None
    )
    return result


def _evidence(row: Any) -> EntryEvidence:
    try:
        return EntryEvidence(
            row["id"],
            row["revision"],
            row["previous_revision"],
            row["source_id"],
            row["mapping_revision"],
            row["account_id"],
            row["created_at"],
            _entry(row),
        )
    except AttributeError, TypeError, ValueError:
        raise CreditEntryUnavailable() from None


class CreditEntryTransaction:
    def __init__(self, unit: WorkspaceTransaction) -> None:
        self._unit = unit

    def _execute(self, sql: str, **parameters: Any) -> Any:
        self._unit._require_open()
        try:
            return self._unit._connection.execute(
                text(sql), {"owner": self._unit._owner_id, **parameters}
            )
        except SQLAlchemyError:
            raise CreditEntryUnavailable() from None

    def _owner(self) -> None:
        if not self._execute(
            "SELECT current_setting('transaction_isolation')='read committed' "
            "AND app.current_owner_id()=CAST(:owner AS uuid) AND EXISTS ("
            "SELECT 1 FROM app.owners WHERE id=:owner AND is_active)"
        ).scalar_one():
            raise CreditEntryUnavailable()

    @contextmanager
    def _write(self) -> Iterator[None]:
        self._unit._require_open()
        try:
            with self._unit._connection.begin_nested():
                self._owner()
                self._execute(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended('credit-accounts/v1:' || CAST(:owner AS text),0))"
                )
                self._owner()
                yield
        except SQLAlchemyError:
            raise CreditEntryUnavailable() from None

    def get(self, entry_id: UUID, *, at_revision: int) -> EntryEvidence | None:
        row = (
            self._execute(
                SELECT + "AND o.id=:id AND o.revision=:revision",
                id=identifier(entry_id),
                revision=revision(at_revision),
            )
            .mappings()
            .one_or_none()
        )
        return _evidence(row) if row else None

    def history(
        self, entry_id: UUID, *, limit: int = 25, before: int | None = None
    ) -> tuple[EntryEvidence, ...]:
        entry_id = identifier(entry_id)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CreditEntryUnavailable()
        if before is not None:
            revision(before)
        rows = self._execute(
            SELECT + "AND o.id=:id AND (CAST(:before AS bigint) IS NULL OR o.revision<:before) "
            "ORDER BY o.revision DESC LIMIT :limit",
            id=entry_id,
            before=before,
            limit=limit,
        ).mappings()
        return tuple(_evidence(row) for row in rows)

    def list(
        self, account_id: UUID, *, limit: int = 25, after: UUID | None = None
    ) -> tuple[EntryEvidence, ...]:
        account_id = identifier(account_id)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CreditEntryUnavailable()
        if after is not None:
            identifier(after)
        rows = self._execute(
            SELECT + "AND o.account_id=:account "
            "AND (CAST(:after AS uuid) IS NULL OR o.id>CAST(:after AS uuid)) "
            "AND NOT EXISTS (SELECT 1 FROM app.credit_evidence_observations n "
            "WHERE n.owner_id=o.owner_id AND n.id=o.id AND n.revision>o.revision) "
            "ORDER BY o.id LIMIT :limit",
            account=account_id,
            after=after,
            limit=limit,
        ).mappings()
        return tuple(_evidence(row) for row in rows)

    def record(
        self,
        entry_id: UUID,
        source_id: UUID,
        mapping_revision: int,
        values: CardEntryValues,
        *,
        expected_revision: int = 0,
    ) -> EntryEvidence:
        entry_id, source_id = identifier(entry_id), identifier(source_id)
        mapping_revision = revision(mapping_revision)
        expected = revision(expected_revision, initial=True)
        if expected == MAX_REVISION:
            raise CreditEntryUnavailable()
        values = validate_entry(values)
        with self._write():
            mapping = self._execute(
                "SELECT account_id FROM app.credit_source_account_mappings m "
                "WHERE owner_id=:owner AND source_id=:source AND revision=:mapping "
                "AND account_id IS NOT NULL AND NOT EXISTS ("
                "SELECT 1 FROM app.credit_source_account_mappings n WHERE n.owner_id=m.owner_id "
                "AND n.source_id=m.source_id AND n.revision>m.revision)",
                source=source_id,
                mapping=mapping_revision,
            ).one_or_none()
            if mapping is None:
                raise CreditEntryUnavailable()
            account_id = mapping.account_id
            account = self._execute(
                "SELECT archived_at FROM app.credit_billing_accounts "
                "WHERE owner_id=:owner AND id=:account FOR UPDATE",
                account=account_id,
            ).one_or_none()
            self._owner()
            if account is None or account.archived_at is not None:
                raise CreditEntryUnavailable()
            retained = self.get(entry_id, at_revision=expected + 1)
            if retained is not None:
                if (
                    retained.source_id != source_id
                    or retained.mapping_revision != mapping_revision
                    or retained.account_id != account_id
                    or retained.values != values
                ):
                    raise CreditEntryUnavailable()
                return retained
            current = self.history(entry_id, limit=1)
            if (current[0].revision if current else 0) != expected:
                raise CreditEntryUnavailable()
            if current and (
                current[0].source_id != source_id or current[0].account_id != account_id
            ):
                raise CreditEntryUnavailable()
            if (
                self._execute(
                    "SELECT count(*) FROM app.credit_evidence_observations WHERE owner_id=:owner"
                ).scalar_one()
                >= MAX_RECORDS
            ):
                raise CreditEntryUnavailable()
            self._execute(
                "INSERT INTO app.credit_evidence_observations "
                "(owner_id,id,revision,previous_revision,source_id,mapping_revision,account_id,"
                "kind,statement_child_kind,current_child_kind,entry_child_kind,"
                "contract_version,reason) "
                "VALUES (:owner,:id,:revision,:previous,:source,:mapping,:account,"
                "'entry',NULL,NULL,'entry',1,:reason)",
                id=entry_id,
                revision=expected + 1,
                previous=expected or None,
                source=source_id,
                mapping=mapping_revision,
                account=account_id,
                reason="initial" if expected == 0 else "correction",
            )
            parameters = _parameters(values)
            columns = VALUE_COLUMNS
            self._execute(
                "INSERT INTO app.credit_entry_values (owner_id,observation_id,revision,"
                + ",".join(columns)
                + ") VALUES (:owner,:id,:revision,"
                + ",".join(":" + name for name in columns)
                + ")",
                id=entry_id,
                revision=expected + 1,
                **parameters,
            )
            # Validate reciprocal completeness before releasing this write's savepoint.
            self._execute("SET CONSTRAINTS app.credit_entry_required IMMEDIATE")
            self._execute("SET CONSTRAINTS app.credit_entry_required DEFERRED")
            result = self.get(entry_id, at_revision=expected + 1)
            if result is None:
                raise CreditEntryUnavailable()
            return result


class CreditEntryDatabase:
    """Internal caller must authenticate the owner and retain server-allocated retry IDs."""

    def __init__(self, url: URL, project: str) -> None:
        self._workspace = WorkspaceDatabase(url, project)

    def close(self) -> None:
        self._workspace.close()

    @contextmanager
    def transaction(self, owner_id: UUID) -> Iterator[CreditEntryTransaction]:
        try:
            with self._workspace.transaction(owner_id) as unit:
                yield CreditEntryTransaction(unit)
        except SQLAlchemyError:
            raise CreditEntryUnavailable() from None
