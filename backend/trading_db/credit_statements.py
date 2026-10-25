"""Owned immutable statement checkpoints; no selected balance or financial posting."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import URL, text
from sqlalchemy.exc import SQLAlchemyError

from trading_api.credit_cards import CardStatementValues
from trading_api.finance import FinancialDate, FinancialValue
from trading_db.connections import DatabaseFailure
from trading_db.workspace import WorkspaceDatabase, WorkspaceTransaction

MAX_RECORDS = 1000
MAX_REVISION = 9007199254740991
ROLES = ("opening_liability", "closing_liability", "total_due", "minimum_due")
DAYS = ("period_start", "period_end", "statement_date", "due_date")


class CreditStatementUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__(
            "Credit statement operation is unavailable or conflicts with retained evidence."
        )


def new_statement_id() -> UUID:
    """Allocate server-side before record(); retain this ID across explicit retries."""
    return uuid4()


def identifier(value: UUID) -> UUID:
    if type(value) is not UUID or not value.int:
        raise CreditStatementUnavailable()
    return value


def revision(value: int, *, initial: bool = False) -> int:
    if type(value) is not int or not (0 if initial else 1) <= value <= MAX_REVISION:
        raise CreditStatementUnavailable()
    return value


def validate_statement(value: CardStatementValues) -> CardStatementValues:
    """Reject invalid nested objects and cached values, without repairing tampering."""
    try:
        if type(value) is not CardStatementValues:
            raise CreditStatementUnavailable()
        fields: dict[str, Any] = {}
        for name in DAYS:
            item = getattr(value, name)
            if item is None and name == "due_date":
                fields[name] = None
                continue
            if type(item) is not FinancialDate:
                raise CreditStatementUnavailable()
            parsed_day = FinancialDate(item.source)
            if type(item.value) is not date or item.value != parsed_day.value:
                raise CreditStatementUnavailable()
            fields[name] = parsed_day
        for name in ROLES:
            item = getattr(value, name)
            if type(item) is not FinancialValue:
                raise CreditStatementUnavailable()
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
                    raise CreditStatementUnavailable()
            elif (
                type(item.value) is not Decimal or item.value.as_tuple() != parsed.value.as_tuple()
            ):
                raise CreditStatementUnavailable()
            fields[name] = parsed
        return CardStatementValues(**fields)
    except AttributeError, TypeError, ValueError:
        raise CreditStatementUnavailable() from None


@dataclass(frozen=True, slots=True, repr=False)
class StatementEvidence:
    id: UUID
    revision: int
    previous_revision: int | None
    source_id: UUID
    mapping_revision: int
    account_id: UUID
    created_at: datetime
    values: CardStatementValues


SELECT = (
    "SELECT o.id,o.revision,o.previous_revision,o.source_id,o.mapping_revision,o.account_id,"
    "o.created_at,v.period_start,v.period_end,v.statement_date,v.due_date,"
    + ",".join(f"v.{role}_source,v.{role}_amount,v.{role}_missing" for role in ROLES)
    + " FROM app.credit_evidence_observations o JOIN app.credit_statement_values v "
    "ON v.owner_id=o.owner_id AND v.observation_id=o.id AND v.revision=o.revision "
    "WHERE o.owner_id=:owner "
)


def _statement(row: Any) -> CardStatementValues:
    fields: dict[str, Any] = {
        name: FinancialDate(row[name].isoformat()) if row[name] is not None else None
        for name in DAYS
    }
    for role in ROLES:
        value = FinancialValue(
            "cash", row[f"{role}_source"], currency="INR", missing_reason=row[f"{role}_missing"]
        )
        if value.value != row[f"{role}_amount"]:
            raise CreditStatementUnavailable()
        fields[role] = value
    return validate_statement(CardStatementValues(**fields))


def _evidence(row: Any) -> StatementEvidence:
    try:
        return StatementEvidence(
            row["id"],
            row["revision"],
            row["previous_revision"],
            row["source_id"],
            row["mapping_revision"],
            row["account_id"],
            row["created_at"],
            _statement(row),
        )
    except AttributeError, TypeError, ValueError:
        raise CreditStatementUnavailable() from None


class CreditStatementTransaction:
    def __init__(self, unit: WorkspaceTransaction) -> None:
        self._unit = unit

    def _execute(self, sql: str, **parameters: Any) -> Any:
        self._unit._require_open()
        try:
            return self._unit._connection.execute(
                text(sql), {"owner": self._unit._owner_id, **parameters}
            )
        except SQLAlchemyError:
            raise CreditStatementUnavailable() from None

    def _owner(self) -> None:
        if not self._execute(
            "SELECT current_setting('transaction_isolation')='read committed' "
            "AND app.current_owner_id()=CAST(:owner AS uuid) AND EXISTS ("
            "SELECT 1 FROM app.owners WHERE id=:owner AND is_active)"
        ).scalar_one():
            raise CreditStatementUnavailable()

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
            raise CreditStatementUnavailable() from None

    def get(self, statement_id: UUID, *, at_revision: int) -> StatementEvidence | None:
        row = (
            self._execute(
                SELECT + "AND o.id=:id AND o.revision=:revision",
                id=identifier(statement_id),
                revision=revision(at_revision),
            )
            .mappings()
            .one_or_none()
        )
        return _evidence(row) if row else None

    def history(
        self, statement_id: UUID, *, limit: int = 25, before: int | None = None
    ) -> tuple[StatementEvidence, ...]:
        statement_id = identifier(statement_id)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CreditStatementUnavailable()
        if before is not None:
            revision(before)
        rows = self._execute(
            SELECT + "AND o.id=:id AND (CAST(:before AS bigint) IS NULL OR o.revision<:before) "
            "ORDER BY o.revision DESC LIMIT :limit",
            id=statement_id,
            before=before,
            limit=limit,
        ).mappings()
        return tuple(_evidence(row) for row in rows)

    def list(
        self, account_id: UUID, *, limit: int = 25, after: UUID | None = None
    ) -> tuple[StatementEvidence, ...]:
        account_id = identifier(account_id)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CreditStatementUnavailable()
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
        statement_id: UUID,
        source_id: UUID,
        mapping_revision: int,
        values: CardStatementValues,
        *,
        expected_revision: int = 0,
    ) -> StatementEvidence:
        statement_id, source_id = identifier(statement_id), identifier(source_id)
        mapping_revision = revision(mapping_revision)
        expected = revision(expected_revision, initial=True)
        if expected == MAX_REVISION:
            raise CreditStatementUnavailable()
        values = validate_statement(values)
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
                raise CreditStatementUnavailable()
            account_id = mapping.account_id
            account = self._execute(
                "SELECT archived_at FROM app.credit_billing_accounts "
                "WHERE owner_id=:owner AND id=:account FOR UPDATE",
                account=account_id,
            ).one_or_none()
            self._owner()
            if account is None or account.archived_at is not None:
                raise CreditStatementUnavailable()
            retained = self.get(statement_id, at_revision=expected + 1)
            if retained is not None:
                if (
                    retained.source_id != source_id
                    or retained.mapping_revision != mapping_revision
                    or retained.account_id != account_id
                    or retained.values != values
                ):
                    raise CreditStatementUnavailable()
                return retained
            current = self.history(statement_id, limit=1)
            if (current[0].revision if current else 0) != expected:
                raise CreditStatementUnavailable()
            if current and (
                current[0].source_id != source_id or current[0].account_id != account_id
            ):
                raise CreditStatementUnavailable()
            if (
                self._execute(
                    "SELECT count(*) FROM app.credit_evidence_observations WHERE owner_id=:owner"
                ).scalar_one()
                >= MAX_RECORDS
            ):
                raise CreditStatementUnavailable()
            self._execute(
                "INSERT INTO app.credit_evidence_observations "
                "(owner_id,id,revision,previous_revision,source_id,mapping_revision,account_id,"
                "kind,contract_version,reason) "
                "VALUES (:owner,:id,:revision,:previous,:source,:mapping,:account,"
                "'statement',1,:reason)",
                id=statement_id,
                revision=expected + 1,
                previous=expected or None,
                source=source_id,
                mapping=mapping_revision,
                account=account_id,
                reason="initial" if expected == 0 else "correction",
            )
            parameters: dict[str, Any] = {
                name: getattr(values, name).value if getattr(values, name) is not None else None
                for name in DAYS
            }
            for role in ROLES:
                value = getattr(values, role)
                parameters.update(
                    {
                        f"{role}_source": value.source,
                        f"{role}_amount": value.value,
                        f"{role}_missing": value.missing_reason,
                    }
                )
            columns = (
                *DAYS,
                *(f"{role}_{part}" for role in ROLES for part in ("source", "amount", "missing")),
            )
            self._execute(
                "INSERT INTO app.credit_statement_values (owner_id,observation_id,revision,"
                + ",".join(columns)
                + ") VALUES (:owner,:id,:revision,"
                + ",".join(":" + name for name in columns)
                + ")",
                id=statement_id,
                revision=expected + 1,
                **parameters,
            )
            # Validate reciprocal completeness before releasing this write's savepoint.
            self._execute("SET CONSTRAINTS app.credit_statement_required IMMEDIATE")
            self._execute("SET CONSTRAINTS app.credit_statement_required DEFERRED")
            result = self.get(statement_id, at_revision=expected + 1)
            if result is None:
                raise CreditStatementUnavailable()
            return result


class CreditStatementDatabase:
    """Internal caller must authenticate the owner and retain server-allocated retry IDs."""

    def __init__(self, url: URL, project: str) -> None:
        self._workspace = WorkspaceDatabase(url, project)

    def close(self) -> None:
        self._workspace.close()

    @contextmanager
    def transaction(self, owner_id: UUID) -> Iterator[CreditStatementTransaction]:
        try:
            with self._workspace.transaction(owner_id) as unit:
                yield CreditStatementTransaction(unit)
        except SQLAlchemyError:
            raise CreditStatementUnavailable() from None
