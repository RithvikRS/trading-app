"""Internal atomic event persistence; native movements, no balance inference."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import URL
from sqlalchemy.exc import SQLAlchemyError

from trading_db.accounts import AccountTransaction, AccountUnavailable, identifier, page, revision
from trading_db.connections import DatabaseFailure
from trading_db.import_contracts import EVENT_KINDS, TRADE_KINDS, StagedValue
from trading_db.imports import ImportTransaction, ImportUnavailable
from trading_db.workspace import WorkspaceDatabase, WorkspaceTransaction

MAX_RECORDS = 1000


class EventUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__("Financial event is unavailable or conflicts with the reviewed evidence.")


@dataclass(frozen=True, repr=False)
class FinancialEvent:
    id: UUID
    revision: int
    source_row_id: UUID
    source_review_revision: int
    account_id: UUID
    position_id: UUID | None
    instrument_id: UUID | None
    status: str
    correction_reason: str | None
    kind: str
    posting_state: str
    trade_date: date | None
    settlement_date: date | None
    booking_date: date | None
    value_date: date | None
    components: tuple[StagedValue, ...]


@dataclass(frozen=True, repr=False)
class Movement:
    event: FinancialEvent
    amount: Decimal
    currency: str | None


class EventTransaction:
    def __init__(self, unit: WorkspaceTransaction) -> None:
        self._accounts = AccountTransaction(unit, None)
        self._imports = ImportTransaction(unit)

    def _execute(self, sql: str, **parameters: Any) -> Any:
        return self._accounts._execute(sql, **parameters)

    def _event(self, row: Any) -> FinancialEvent:
        fields = {
            key: row[key] for key in FinancialEvent.__dataclass_fields__ if key != "components"
        }
        values = self._execute(
            "SELECT role,source,currency,missing_reason FROM app.event_components WHERE "
            "owner_id=:owner AND event_id=:id AND revision=:revision ORDER BY role",
            id=row["id"],
            revision=row["revision"],
        ).mappings()
        fields["components"] = tuple(StagedValue.model_validate(dict(value)) for value in values)
        return FinancialEvent(**fields)

    def get(self, event_id: UUID) -> FinancialEvent | None:
        row = (
            self._execute(
                "SELECT * FROM app.financial_events WHERE owner_id=:owner AND id=:id ORDER "
                "BY revision DESC LIMIT 1",
                id=identifier(event_id),
            )
            .mappings()
            .one_or_none()
        )
        return self._event(row) if row else None

    def by_source(self, row_id: UUID) -> FinancialEvent | None:
        row = (
            self._execute(
                "SELECT * FROM app.financial_events WHERE owner_id=:owner AND source_row_id=:id",
                id=identifier(row_id),
            )
            .mappings()
            .one_or_none()
        )
        return self._event(row) if row else None

    def record(
        self,
        row_id: UUID,
        *,
        expected_review_revision: int,
        position_id: UUID | None = None,
    ) -> FinancialEvent:
        identifier(row_id)
        expected = revision(expected_review_revision)
        if position_id is not None:
            identifier(position_id)
        try:
            with self._accounts._write():
                prior = self.by_source(row_id)
                if prior:
                    if (
                        prior.revision != 1
                        or prior.source_review_revision != expected
                        or prior.position_id != position_id
                    ):
                        raise EventUnavailable()
                    return prior
                return self._persist(row_id, expected, position_id, None, None)
        except AccountUnavailable, ImportUnavailable:
            raise EventUnavailable() from None

    def correct(
        self,
        event_id: UUID,
        row_id: UUID,
        *,
        expected_revision: int,
        expected_review_revision: int,
        reason: str,
    ) -> FinancialEvent:
        identifier(event_id)
        identifier(row_id)
        expected = revision(expected_revision)
        review = revision(expected_review_revision)
        if type(reason) is not str or reason not in {
            "source_correction",
            "posting_update",
            "cancellation",
            "reinstatement",
        }:
            raise EventUnavailable()
        try:
            with self._accounts._write():
                replay = self.by_source(row_id)
                if replay:
                    if (
                        replay.id != event_id
                        or replay.revision != expected + 1
                        or replay.source_review_revision != review
                        or replay.correction_reason != reason
                    ):
                        raise EventUnavailable()
                    return replay
                current = self.get(event_id)
                if current is None or current.revision != expected:
                    raise EventUnavailable()
                return self._persist(row_id, review, current.position_id, current, reason)
        except AccountUnavailable, ImportUnavailable:
            raise EventUnavailable() from None

    def _persist(
        self,
        row_id: UUID,
        review: int,
        position_id: UUID | None,
        previous: FinancialEvent | None,
        reason: str | None,
    ) -> FinancialEvent:
        source, context = self._imports.reviewed(row_id, review)
        candidate = source.definition
        cancelled = candidate.kind == "cancellation"
        account, instrument = context["account"], context["instrument"]
        if account is None or (candidate.kind not in EVENT_KINDS and not cancelled):
            raise EventUnavailable()
        status = "cancelled" if cancelled else "active"
        if previous:
            if (
                account.id != previous.account_id
                or (not cancelled and instrument != previous.instrument_id)
                or (
                    cancelled
                    and candidate.instrument_identifier_id is not None
                    and instrument != previous.instrument_id
                )
            ):
                raise EventUnavailable()
            if (
                (cancelled and (previous.status != "active" or reason != "cancellation"))
                or (not cancelled and previous.status == "cancelled" and reason != "reinstatement")
                or (
                    not cancelled
                    and previous.status == "active"
                    and reason not in {"source_correction", "posting_update"}
                )
            ):
                raise EventUnavailable()
            if not cancelled and candidate.kind != previous.kind:
                raise EventUnavailable()
            if cancelled:
                instrument = previous.instrument_id
        elif cancelled:
            raise EventUnavailable()
        if (position_id is None) != (instrument is None):
            raise EventUnavailable()
        if (
            position_id is not None
            and not self._execute(
                "SELECT EXISTS(SELECT 1 FROM app.account_positions WHERE owner_id=:owner AND "
                "id=:id AND account_id=:account AND instrument_id=:instrument)",
                id=position_id,
                account=account.id,
                instrument=instrument,
            ).scalar_one()
        ):
            raise EventUnavailable()
        values = {value.role: value for value in candidate.values}
        if not cancelled:
            cash = values["net_cash"]
            native = context["quote_currency"] or context["fund_currency"]
            if (native is not None and cash.currency != native) or any(
                value.currency is not None and value.currency != cash.currency
                for value in candidate.values
            ):
                raise EventUnavailable()
        if reason == "posting_update":
            assert previous is not None
            old_values = {
                value.role: (value.financial().value, value.currency, value.missing_reason)
                for value in previous.components
            }
            new_values = {
                value.role: (value.financial().value, value.currency, value.missing_reason)
                for value in candidate.values
            }
            old_date = previous.trade_date.isoformat() if previous.trade_date else None
            if (
                previous.posting_state != "pending"
                or candidate.posting_state != "posted"
                or old_values != new_values
                or old_date != candidate.trade_date
            ):
                raise EventUnavailable()
        quantity = not cancelled and candidate.kind in TRADE_KINDS
        for table, additional in (
            ("financial_events", 1),
            ("event_components", len(values)),
            ("cash_movements", int(not cancelled)),
            ("quantity_movements", int(quantity)),
        ):
            if (
                self._execute(
                    f"SELECT count(*) FROM app.{table} WHERE owner_id=:owner"
                ).scalar_one()
                + additional
                > MAX_RECORDS
            ):
                raise EventUnavailable()
        event_id = previous.id if previous else uuid4()
        version = previous.revision + 1 if previous else 1
        self._execute(
            "INSERT INTO app.financial_events (owner_id,id,revision,previous_revision,"
            "source_row_id,source_review_revision,account_id,position_id,instrument_id,kind,"
            "posting_state,status,correction_reason,trade_date,settlement_date,booking_date,"
            "value_date,value_count) VALUES (:owner,:id,:revision,:previous,:row,:review,"
            ":account,:position,:instrument,:kind,:state,:status,:reason,:trade,:settlement,"
            ":booking,:value,:count)",
            id=event_id,
            revision=version,
            previous=previous.revision if previous else None,
            row=row_id,
            review=review,
            account=account.id,
            position=position_id,
            instrument=instrument,
            kind=previous.kind if cancelled and previous else candidate.kind,
            state=previous.posting_state if cancelled and previous else candidate.posting_state,
            status=status,
            reason=reason,
            trade=candidate.trade_date,
            settlement=candidate.settlement_date,
            booking=candidate.booking_date,
            value=candidate.value_date,
            count=len(values),
        )
        for component in candidate.values:
            self._execute(
                "INSERT INTO app.event_components (owner_id,event_id,revision,role,source,"
                "amount,currency,missing_reason) VALUES (:owner,:event,:revision,:role,"
                ":source,:amount,:currency,:missing_reason)",
                event=event_id,
                revision=version,
                amount=component.financial().value,
                **component.model_dump(),
            )
        if quantity:
            self._execute(
                "INSERT INTO app.quantity_movements (owner_id,event_id,revision,position_id,"
                "amount) VALUES (:owner,:event,:revision,:position,:amount)",
                event=event_id,
                revision=version,
                position=position_id,
                amount=values["quantity"].financial().value,
            )
        if not cancelled:
            cash = values["net_cash"]
            self._execute(
                "INSERT INTO app.cash_movements (owner_id,event_id,revision,account_id,"
                "currency,amount) VALUES (:owner,:event,:revision,:account,:currency,:amount)",
                event=event_id,
                revision=version,
                account=account.id,
                currency=cash.currency,
                amount=cash.financial().value,
            )
        result = self.get(event_id)
        assert result is not None
        return result

    def history(
        self,
        event_id: UUID,
        *,
        limit: int = 25,
        before: int | None = None,
    ) -> tuple[FinancialEvent, ...]:
        page(limit, None)
        if before is not None:
            revision(before)
        rows = self._execute(
            "SELECT * FROM app.financial_events WHERE owner_id=:owner AND id=:id AND "
            "(CAST(:before AS bigint) IS NULL OR revision<:before) ORDER BY revision DESC "
            "LIMIT :limit",
            id=identifier(event_id),
            before=before,
            limit=limit,
        ).mappings()
        return tuple(self._event(row) for row in rows)

    def list(
        self, account_id: UUID, *, limit: int = 25, after: UUID | None = None
    ) -> tuple[FinancialEvent, ...]:
        page(limit, after)
        rows = self._execute(
            "SELECT e.* FROM app.financial_events e WHERE e.owner_id=:owner AND "
            "e.account_id=:account AND (CAST(:after AS uuid) IS NULL OR e.id>CAST(:after AS "
            "uuid)) AND NOT EXISTS (SELECT 1 FROM app.financial_events n WHERE "
            "n.owner_id=e.owner_id AND n.id=e.id AND n.revision>e.revision) ORDER BY e.id "
            "LIMIT :limit",
            account=identifier(account_id),
            after=after,
            limit=limit,
        ).mappings()
        return tuple(self._event(row) for row in rows)

    def movements(
        self,
        parent_id: UUID,
        *,
        kind: Literal["cash", "quantity"],
        posting_state: Literal["posted", "pending"],
        limit: int = 25,
        after: UUID | None = None,
    ) -> tuple[Movement, ...]:
        page(limit, after)
        if (
            type(kind) is not str
            or kind not in ("cash", "quantity")
            or type(posting_state) is not str
            or posting_state not in ("posted", "pending")
        ):
            raise EventUnavailable()
        parent = "account" if kind == "cash" else "position"
        currency = "m.currency" if kind == "cash" else "NULL"
        rows = self._execute(
            f"SELECT e.*,m.amount,{currency} AS currency FROM app.{kind}_movements m "
            "JOIN app.financial_events e ON e.owner_id=m.owner_id AND e.id=m.event_id AND "
            f"e.revision=m.revision WHERE e.owner_id=:owner AND m.{parent}_id=:parent "
            "AND e.status='active' AND e.posting_state=:state AND (CAST(:after AS uuid) IS "
            "NULL OR e.id>CAST(:after AS uuid)) AND NOT EXISTS (SELECT 1 FROM "
            "app.financial_events n WHERE n.owner_id=e.owner_id AND n.id=e.id AND "
            "n.revision>e.revision) ORDER BY e.id LIMIT :limit",
            parent=identifier(parent_id),
            state=posting_state,
            after=after,
            limit=limit,
        ).mappings()
        return tuple(Movement(self._event(row), row["amount"], row["currency"]) for row in rows)


class EventDatabase:
    def __init__(self, url: URL, project: str) -> None:
        self._workspace = WorkspaceDatabase(url, project)

    def close(self) -> None:
        self._workspace.close()

    @contextmanager
    def transaction(self, owner_id: UUID) -> Iterator[EventTransaction]:
        try:
            with self._workspace.transaction(owner_id) as unit:
                yield EventTransaction(unit)
        except SQLAlchemyError, AccountUnavailable, ImportUnavailable:
            raise EventUnavailable() from None
