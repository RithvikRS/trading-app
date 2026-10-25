"""Owned immutable current checkpoints; no selected balance or financial posting."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import URL, text
from sqlalchemy.exc import SQLAlchemyError

from trading_api.credit_cards import CardCurrentValues
from trading_api.finance import FinancialDate, FinancialInstant, FinancialValue
from trading_db.connections import DatabaseFailure
from trading_db.workspace import WorkspaceDatabase, WorkspaceTransaction

MAX_RECORDS = 1000
MAX_REVISION = 9007199254740991
ROLES = ("outstanding", "unbilled", "credit_limit", "available_credit")
DAYS = ("as_of_date",)


class CreditCurrentUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__(
            "Credit current operation is unavailable or conflicts with retained evidence."
        )


def new_current_id() -> UUID:
    """Allocate server-side before record(); retain this ID across explicit retries."""
    return uuid4()


def identifier(value: UUID) -> UUID:
    if type(value) is not UUID or not value.int:
        raise CreditCurrentUnavailable()
    return value


def revision(value: int, *, initial: bool = False) -> int:
    if type(value) is not int or not (0 if initial else 1) <= value <= MAX_REVISION:
        raise CreditCurrentUnavailable()
    return value


def validate_current(value: CardCurrentValues) -> CardCurrentValues:
    """Reject invalid nested objects and cached values, without repairing tampering."""
    try:
        if type(value) is not CardCurrentValues:
            raise CreditCurrentUnavailable()
        fields: dict[str, Any] = {}
        for name in DAYS:
            item = getattr(value, name)
            if type(item) is not FinancialDate:
                raise CreditCurrentUnavailable()
            parsed_day = FinancialDate(item.source)
            if type(item.value) is not date or item.value != parsed_day.value:
                raise CreditCurrentUnavailable()
            fields[name] = parsed_day
        instant = value.as_of_instant
        if instant is None:
            fields["as_of_instant"] = None
        else:
            if type(instant) is not FinancialInstant:
                raise CreditCurrentUnavailable()
            parsed_instant = FinancialInstant(instant.source)
            if (
                type(instant.value) is not datetime
                or instant.value.tzinfo is not UTC
                or instant.value.fold != 0
                or instant.value != parsed_instant.value
                or type(instant.source_offset) is not str
                or instant.source_offset != parsed_instant.source_offset
                or type(instant.fractional_digits) is not int
                or instant.fractional_digits != parsed_instant.fractional_digits
            ):
                raise CreditCurrentUnavailable()
            fields["as_of_instant"] = parsed_instant
        for name in ROLES:
            item = getattr(value, name)
            if type(item) is not FinancialValue:
                raise CreditCurrentUnavailable()
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
                    raise CreditCurrentUnavailable()
            elif (
                type(item.value) is not Decimal or item.value.as_tuple() != parsed.value.as_tuple()
            ):
                raise CreditCurrentUnavailable()
            fields[name] = parsed
        return CardCurrentValues(**fields)
    except AttributeError, TypeError, ValueError:
        raise CreditCurrentUnavailable() from None


@dataclass(frozen=True, slots=True, repr=False)
class CurrentEvidence:
    id: UUID
    revision: int
    previous_revision: int | None
    source_id: UUID
    mapping_revision: int
    account_id: UUID
    created_at: datetime
    values: CardCurrentValues


SELECT = (
    "SELECT o.id,o.revision,o.previous_revision,o.source_id,o.mapping_revision,o.account_id,"
    "o.created_at,v.as_of_date,v.as_of_instant,"
    + ",".join(f"v.{role}_source,v.{role}_amount,v.{role}_missing" for role in ROLES)
    + " FROM app.credit_evidence_observations o JOIN app.credit_current_values v "
    "ON v.owner_id=o.owner_id AND v.observation_id=o.id AND v.revision=o.revision "
    "WHERE o.owner_id=:owner "
)


def _current(row: Any) -> CardCurrentValues:
    fields: dict[str, Any] = {
        name: FinancialDate(row[name].isoformat()) if row[name] is not None else None
        for name in DAYS
    }
    fields["as_of_instant"] = (
        FinancialInstant(row["as_of_instant"]) if row["as_of_instant"] is not None else None
    )
    for role in ROLES:
        value = FinancialValue(
            "cash", row[f"{role}_source"], currency="INR", missing_reason=row[f"{role}_missing"]
        )
        if value.value != row[f"{role}_amount"]:
            raise CreditCurrentUnavailable()
        fields[role] = value
    return validate_current(CardCurrentValues(**fields))


def _evidence(row: Any) -> CurrentEvidence:
    try:
        return CurrentEvidence(
            row["id"],
            row["revision"],
            row["previous_revision"],
            row["source_id"],
            row["mapping_revision"],
            row["account_id"],
            row["created_at"],
            _current(row),
        )
    except AttributeError, TypeError, ValueError:
        raise CreditCurrentUnavailable() from None


class CreditCurrentTransaction:
    def __init__(self, unit: WorkspaceTransaction) -> None:
        self._unit = unit

    def _execute(self, sql: str, **parameters: Any) -> Any:
        self._unit._require_open()
        try:
            return self._unit._connection.execute(
                text(sql), {"owner": self._unit._owner_id, **parameters}
            )
        except SQLAlchemyError:
            raise CreditCurrentUnavailable() from None

    def _owner(self) -> None:
        if not self._execute(
            "SELECT current_setting('transaction_isolation')='read committed' "
            "AND app.current_owner_id()=CAST(:owner AS uuid) AND EXISTS ("
            "SELECT 1 FROM app.owners WHERE id=:owner AND is_active)"
        ).scalar_one():
            raise CreditCurrentUnavailable()

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
            raise CreditCurrentUnavailable() from None

    def get(self, current_id: UUID, *, at_revision: int) -> CurrentEvidence | None:
        row = (
            self._execute(
                SELECT + "AND o.id=:id AND o.revision=:revision",
                id=identifier(current_id),
                revision=revision(at_revision),
            )
            .mappings()
            .one_or_none()
        )
        return _evidence(row) if row else None

    def history(
        self, current_id: UUID, *, limit: int = 25, before: int | None = None
    ) -> tuple[CurrentEvidence, ...]:
        current_id = identifier(current_id)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CreditCurrentUnavailable()
        if before is not None:
            revision(before)
        rows = self._execute(
            SELECT + "AND o.id=:id AND (CAST(:before AS bigint) IS NULL OR o.revision<:before) "
            "ORDER BY o.revision DESC LIMIT :limit",
            id=current_id,
            before=before,
            limit=limit,
        ).mappings()
        return tuple(_evidence(row) for row in rows)

    def list(
        self, account_id: UUID, *, limit: int = 25, after: UUID | None = None
    ) -> tuple[CurrentEvidence, ...]:
        account_id = identifier(account_id)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CreditCurrentUnavailable()
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
        current_id: UUID,
        source_id: UUID,
        mapping_revision: int,
        values: CardCurrentValues,
        *,
        expected_revision: int = 0,
    ) -> CurrentEvidence:
        current_id, source_id = identifier(current_id), identifier(source_id)
        mapping_revision = revision(mapping_revision)
        expected = revision(expected_revision, initial=True)
        if expected == MAX_REVISION:
            raise CreditCurrentUnavailable()
        values = validate_current(values)
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
                raise CreditCurrentUnavailable()
            account_id = mapping.account_id
            account = self._execute(
                "SELECT archived_at FROM app.credit_billing_accounts "
                "WHERE owner_id=:owner AND id=:account FOR UPDATE",
                account=account_id,
            ).one_or_none()
            self._owner()
            if account is None or account.archived_at is not None:
                raise CreditCurrentUnavailable()
            retained = self.get(current_id, at_revision=expected + 1)
            if retained is not None:
                if (
                    retained.source_id != source_id
                    or retained.mapping_revision != mapping_revision
                    or retained.account_id != account_id
                    or retained.values != values
                ):
                    raise CreditCurrentUnavailable()
                return retained
            current = self.history(current_id, limit=1)
            if (current[0].revision if current else 0) != expected:
                raise CreditCurrentUnavailable()
            if current and (
                current[0].source_id != source_id or current[0].account_id != account_id
            ):
                raise CreditCurrentUnavailable()
            if (
                self._execute(
                    "SELECT count(*) FROM app.credit_evidence_observations WHERE owner_id=:owner"
                ).scalar_one()
                >= MAX_RECORDS
            ):
                raise CreditCurrentUnavailable()
            self._execute(
                "INSERT INTO app.credit_evidence_observations "
                "(owner_id,id,revision,previous_revision,source_id,mapping_revision,account_id,"
                "kind,statement_child_kind,current_child_kind,contract_version,reason) "
                "VALUES (:owner,:id,:revision,:previous,:source,:mapping,:account,"
                "'current',NULL,'current',1,:reason)",
                id=current_id,
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
            parameters["as_of_instant"] = (
                values.as_of_instant.source if values.as_of_instant is not None else None
            )
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
                "as_of_instant",
                *(f"{role}_{part}" for role in ROLES for part in ("source", "amount", "missing")),
            )
            self._execute(
                "INSERT INTO app.credit_current_values (owner_id,observation_id,revision,"
                + ",".join(columns)
                + ") VALUES (:owner,:id,:revision,"
                + ",".join(":" + name for name in columns)
                + ")",
                id=current_id,
                revision=expected + 1,
                **parameters,
            )
            # Validate reciprocal completeness before releasing this write's savepoint.
            self._execute("SET CONSTRAINTS app.credit_current_required IMMEDIATE")
            self._execute("SET CONSTRAINTS app.credit_current_required DEFERRED")
            result = self.get(current_id, at_revision=expected + 1)
            if result is None:
                raise CreditCurrentUnavailable()
            return result


class CreditCurrentDatabase:
    """Internal caller must authenticate the owner and retain server-allocated retry IDs."""

    def __init__(self, url: URL, project: str) -> None:
        self._workspace = WorkspaceDatabase(url, project)

    def close(self) -> None:
        self._workspace.close()

    @contextmanager
    def transaction(self, owner_id: UUID) -> Iterator[CreditCurrentTransaction]:
        try:
            with self._workspace.transaction(owner_id) as unit:
                yield CreditCurrentTransaction(unit)
        except SQLAlchemyError:
            raise CreditCurrentUnavailable() from None
