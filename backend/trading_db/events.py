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
                    if prior.source_review_revision != expected or prior.position_id != position_id:
                        raise EventUnavailable()
                    return prior
                source = self._imports.get_row(row_id)
                if (
                    source is None
                    or source.status != "included"
                    or source.decision is None
                    or source.decision.revision != expected
                    or source.definition.kind not in EVENT_KINDS
                ):
                    raise EventUnavailable()
                candidate = source.definition
                raw = (
                    self._execute(
                        "SELECT * FROM app.staged_rows WHERE owner_id=:owner AND id=:id",
                        id=row_id,
                    )
                    .mappings()
                    .one()
                )
                context = self._imports._context(raw)
                account, instrument = context["account"], context["instrument"]
                if account is None or (position_id is None) != (instrument is None):
                    raise EventUnavailable()
                if (
                    position_id is not None
                    and not self._execute(
                        "SELECT EXISTS(SELECT 1 FROM app.account_positions WHERE "
                        "owner_id=:owner AND id=:id AND account_id=:account AND "
                        "instrument_id=:instrument)",
                        id=position_id,
                        account=account.id,
                        instrument=instrument,
                    ).scalar_one()
                ):
                    raise EventUnavailable()
                values = {value.role: value for value in candidate.values}
                cash = values["net_cash"]
                native = context["quote_currency"] or context["fund_currency"]
                if (native is not None and cash.currency != native) or any(
                    value.currency is not None and value.currency != cash.currency
                    for value in candidate.values
                ):
                    raise EventUnavailable()
                # Validate the immutable batch's versioned digest before consuming its evidence.
                self._imports.get_batch(source.batch_id)
                for table, additional in (
                    ("financial_events", 1),
                    ("event_components", len(values)),
                    ("cash_movements", 1),
                    ("quantity_movements", int(candidate.kind in TRADE_KINDS)),
                ):
                    if (
                        self._execute(
                            f"SELECT count(*) FROM app.{table} WHERE owner_id=:owner"
                        ).scalar_one()
                        + additional
                        > MAX_RECORDS
                    ):
                        raise EventUnavailable()
                event_id = uuid4()
                self._execute(
                    "INSERT INTO app.financial_events (owner_id,id,revision,source_row_id,"
                    "source_review_revision,account_id,position_id,instrument_id,kind,"
                    "posting_state,trade_date,settlement_date,booking_date,value_date,"
                    "value_count) VALUES (:owner,:id,1,:row,:review,:account,:position,"
                    ":instrument,:kind,:state,:trade,:settlement,:booking,:value,:count)",
                    id=event_id,
                    row=row_id,
                    review=expected,
                    account=account.id,
                    position=position_id,
                    instrument=instrument,
                    kind=candidate.kind,
                    state=candidate.posting_state,
                    trade=candidate.trade_date,
                    settlement=candidate.settlement_date,
                    booking=candidate.booking_date,
                    value=candidate.value_date,
                    count=len(values),
                )
                for component in candidate.values:
                    self._execute(
                        "INSERT INTO app.event_components (owner_id,event_id,revision,role,"
                        "source,amount,currency,missing_reason) VALUES (:owner,:event,1,"
                        ":role,:source,:amount,:currency,:missing_reason)",
                        event=event_id,
                        amount=component.financial().value,
                        **component.model_dump(),
                    )
                if candidate.kind in TRADE_KINDS:
                    self._execute(
                        "INSERT INTO app.quantity_movements (owner_id,event_id,revision,"
                        "position_id,amount) VALUES (:owner,:event,1,:position,:amount)",
                        event=event_id,
                        position=position_id,
                        amount=values["quantity"].financial().value,
                    )
                self._execute(
                    "INSERT INTO app.cash_movements (owner_id,event_id,revision,account_id,"
                    "currency,amount) VALUES (:owner,:event,1,:account,:currency,:amount)",
                    event=event_id,
                    account=account.id,
                    currency=cash.currency,
                    amount=cash.financial().value,
                )
                result = self.get(event_id)
                assert result is not None
                return result
        except AccountUnavailable, ImportUnavailable:
            raise EventUnavailable() from None

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
            "AND e.posting_state=:state AND (CAST(:after AS uuid) IS NULL OR "
            "e.id>CAST(:after AS uuid)) AND NOT EXISTS (SELECT 1 FROM app.financial_events n "
            "WHERE n.owner_id=e.owner_id AND n.id=e.id AND n.revision>e.revision) ORDER BY "
            "e.id LIMIT :limit",
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
