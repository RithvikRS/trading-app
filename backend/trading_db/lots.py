"""Independent acquisition/remaining evidence and append-only lot corrections."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import URL
from sqlalchemy.exc import SQLAlchemyError

from trading_db.accounts import AccountTransaction, AccountUnavailable, identifier, page, revision
from trading_db.connections import DatabaseFailure
from trading_db.import_contracts import LOT_KINDS, StagedValue
from trading_db.imports import ImportTransaction, ImportUnavailable
from trading_db.workspace import WorkspaceDatabase, WorkspaceTransaction

MAX_RECORDS = 1000


class LotUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__("Lot evidence is unavailable or conflicts with the current revision.")


@dataclass(frozen=True, repr=False)
class Lot:
    id: UUID
    position_id: UUID


@dataclass(frozen=True, repr=False)
class LotObservation:
    id: UUID
    revision: int
    lot_id: UUID
    scope: str
    source_row_id: UUID
    source_review_revision: int
    status: str
    correction_reason: str | None
    as_of_date: date | None
    acquisition_date: date | None
    booking_date: date | None
    components: tuple[StagedValue, ...]


class LotTransaction:
    def __init__(self, unit: WorkspaceTransaction) -> None:
        self._accounts = AccountTransaction(unit, None)
        self._imports = ImportTransaction(unit)

    def _execute(self, sql: str, **parameters: Any) -> Any:
        return self._accounts._execute(sql, **parameters)

    def _budget(self, table: str, additional: int = 1) -> None:
        if (
            self._execute(f"SELECT count(*) FROM app.{table} WHERE owner_id=:owner").scalar_one()
            + additional
            > MAX_RECORDS
        ):
            raise LotUnavailable()

    def get_lot(self, lot_id: UUID) -> Lot | None:
        row = (
            self._execute(
                "SELECT id,position_id FROM app.lots WHERE owner_id=:owner AND id=:id",
                id=identifier(lot_id),
            )
            .mappings()
            .one_or_none()
        )
        return Lot(**row) if row else None

    def list(
        self, position_id: UUID, *, limit: int = 25, after: UUID | None = None
    ) -> tuple[Lot, ...]:
        page(limit, after)
        rows = self._execute(
            "SELECT id,position_id FROM app.lots WHERE owner_id=:owner AND "
            "position_id=:position AND (CAST(:after AS uuid) IS NULL OR id>CAST(:after AS "
            "uuid)) ORDER BY id LIMIT :limit",
            position=identifier(position_id),
            after=after,
            limit=limit,
        ).mappings()
        return tuple(Lot(**row) for row in rows)

    def _observation(self, row: Any) -> LotObservation:
        fields = {
            key: row[key] for key in LotObservation.__dataclass_fields__ if key != "components"
        }
        values = self._execute(
            "SELECT role,source,currency,missing_reason FROM app.lot_components WHERE "
            "owner_id=:owner AND observation_id=:id AND revision=:revision ORDER BY role",
            id=row["id"],
            revision=row["revision"],
        ).mappings()
        fields["components"] = tuple(StagedValue.model_validate(dict(value)) for value in values)
        return LotObservation(**fields)

    def get(self, observation_id: UUID) -> LotObservation | None:
        row = (
            self._execute(
                "SELECT * FROM app.lot_observations WHERE owner_id=:owner AND id=:id ORDER "
                "BY revision DESC LIMIT 1",
                id=identifier(observation_id),
            )
            .mappings()
            .one_or_none()
        )
        return self._observation(row) if row else None

    def by_source(self, row_id: UUID) -> LotObservation | None:
        row = (
            self._execute(
                "SELECT * FROM app.lot_observations WHERE owner_id=:owner AND source_row_id=:id",
                id=identifier(row_id),
            )
            .mappings()
            .one_or_none()
        )
        return self._observation(row) if row else None

    def record(
        self,
        row_id: UUID,
        position_id: UUID,
        *,
        expected_review_revision: int,
        lot_id: UUID | None = None,
    ) -> LotObservation:
        identifier(row_id)
        identifier(position_id)
        expected = revision(expected_review_revision)
        if lot_id is not None:
            identifier(lot_id)
        try:
            with self._accounts._write():
                replay = self.by_source(row_id)
                if replay:
                    saved_lot = self.get_lot(replay.lot_id)
                    if (
                        replay.revision != 1
                        or replay.source_review_revision != expected
                        or saved_lot is None
                        or saved_lot.position_id != position_id
                        or (lot_id is not None and lot_id != replay.lot_id)
                    ):
                        raise LotUnavailable()
                    return replay
                return self._persist(row_id, expected, position_id, lot_id, None, None)
        except AccountUnavailable, ImportUnavailable:
            raise LotUnavailable() from None

    def correct(
        self,
        observation_id: UUID,
        row_id: UUID,
        *,
        expected_revision: int,
        expected_review_revision: int,
        reason: str,
    ) -> LotObservation:
        identifier(observation_id)
        identifier(row_id)
        expected, review = revision(expected_revision), revision(expected_review_revision)
        if type(reason) is not str or reason not in {
            "source_correction",
            "cancellation",
            "reinstatement",
        }:
            raise LotUnavailable()
        try:
            with self._accounts._write():
                replay = self.by_source(row_id)
                if replay:
                    if (
                        replay.id != observation_id
                        or replay.revision != expected + 1
                        or replay.source_review_revision != review
                        or replay.correction_reason != reason
                    ):
                        raise LotUnavailable()
                    return replay
                current = self.get(observation_id)
                if current is None or current.revision != expected:
                    raise LotUnavailable()
                lot = self.get_lot(current.lot_id)
                if lot is None:
                    raise LotUnavailable()
                return self._persist(row_id, review, lot.position_id, lot.id, current, reason)
        except AccountUnavailable, ImportUnavailable:
            raise LotUnavailable() from None

    def _persist(
        self,
        row_id: UUID,
        review: int,
        position_id: UUID,
        lot_id: UUID | None,
        previous: LotObservation | None,
        reason: str | None,
    ) -> LotObservation:
        source, context = self._imports.reviewed(row_id, review)
        candidate = source.definition
        cancelled = candidate.kind == "cancellation"
        if candidate.kind not in LOT_KINDS and not cancelled:
            raise LotUnavailable()
        if previous:
            if (
                (cancelled and (previous.status != "active" or reason != "cancellation"))
                or (not cancelled and previous.status == "cancelled" and reason != "reinstatement")
                or (not cancelled and previous.status == "active" and reason != "source_correction")
                or (not cancelled and previous.scope != candidate.kind)
            ):
                raise LotUnavailable()
        elif cancelled:
            raise LotUnavailable()
        position = (
            self._execute(
                "SELECT * FROM app.account_positions WHERE owner_id=:owner AND id=:id",
                id=position_id,
            )
            .mappings()
            .one_or_none()
        )
        account = context["account"]
        if (
            position is None
            or account is None
            or position["account_id"] != account.id
            or (
                (not cancelled or candidate.instrument_identifier_id is not None)
                and position["instrument_id"] != context["instrument"]
            )
        ):
            raise LotUnavailable()
        native = context["quote_currency"] or context["fund_currency"]
        if native is not None and any(
            value.role == "unit_price" and value.currency != native for value in candidate.values
        ):
            raise LotUnavailable()
        self._budget("lot_observations")
        self._budget("lot_components", len(candidate.values))
        if lot_id is None:
            self._budget("lots")
            lot_id = uuid4()
            self._execute(
                "INSERT INTO app.lots (owner_id,id,position_id) VALUES (:owner,:id,:position)",
                id=lot_id,
                position=position_id,
            )
        else:
            lot = self.get_lot(lot_id)
            if lot is None or lot.position_id != position_id:
                raise LotUnavailable()
        record_id, version = (previous.id, previous.revision + 1) if previous else (uuid4(), 1)
        self._execute(
            "INSERT INTO app.lot_observations (owner_id,id,revision,previous_revision,lot_id,"
            "scope,source_row_id,source_review_revision,status,correction_reason,as_of_date,"
            "acquisition_date,booking_date,value_count) VALUES (:owner,:id,:revision,"
            ":previous,:lot,:scope,:row,:review,:status,:reason,:as_of,:acquisition,:booking,"
            ":count)",
            id=record_id,
            revision=version,
            previous=previous.revision if previous else None,
            lot=lot_id,
            scope=previous.scope if cancelled and previous else candidate.kind,
            row=row_id,
            review=review,
            status="cancelled" if cancelled else "active",
            reason=reason,
            as_of=candidate.as_of_date,
            acquisition=candidate.acquisition_date,
            booking=candidate.booking_date,
            count=len(candidate.values),
        )
        for value in candidate.values:
            self._execute(
                "INSERT INTO app.lot_components (owner_id,observation_id,revision,role,"
                "source,amount,currency,missing_reason) VALUES (:owner,:id,:revision,:role,"
                ":source,:amount,:currency,:missing_reason)",
                id=record_id,
                revision=version,
                amount=value.financial().value,
                **value.model_dump(),
            )
        result = self.get(record_id)
        assert result is not None
        return result

    def observations(
        self,
        lot_id: UUID,
        *,
        include_cancelled: bool = False,
        limit: int = 25,
        after: UUID | None = None,
    ) -> tuple[LotObservation, ...]:
        page(limit, after)
        if type(include_cancelled) is not bool:
            raise LotUnavailable()
        rows = self._execute(
            "SELECT e.* FROM app.lot_observations e WHERE e.owner_id=:owner AND "
            "e.lot_id=:lot AND (:cancelled OR e.status='active') AND (CAST(:after AS uuid) "
            "IS NULL OR e.id>CAST(:after AS uuid)) AND NOT EXISTS (SELECT 1 FROM "
            "app.lot_observations n WHERE n.owner_id=e.owner_id AND n.id=e.id AND "
            "n.revision>e.revision) ORDER BY e.id LIMIT :limit",
            lot=identifier(lot_id),
            cancelled=include_cancelled,
            after=after,
            limit=limit,
        ).mappings()
        return tuple(self._observation(row) for row in rows)

    def history(
        self,
        observation_id: UUID,
        *,
        limit: int = 25,
        before: int | None = None,
    ) -> tuple[LotObservation, ...]:
        page(limit, None)
        if before is not None:
            revision(before)
        rows = self._execute(
            "SELECT * FROM app.lot_observations WHERE owner_id=:owner AND id=:id AND "
            "(CAST(:before AS bigint) IS NULL OR revision<:before) ORDER BY revision DESC "
            "LIMIT :limit",
            id=identifier(observation_id),
            before=before,
            limit=limit,
        ).mappings()
        return tuple(self._observation(row) for row in rows)


class LotDatabase:
    def __init__(self, url: URL, project: str) -> None:
        self._workspace = WorkspaceDatabase(url, project)

    def close(self) -> None:
        self._workspace.close()

    @contextmanager
    def transaction(self, owner_id: UUID) -> Iterator[LotTransaction]:
        try:
            with self._workspace.transaction(owner_id) as unit:
                yield LotTransaction(unit)
        except SQLAlchemyError, AccountUnavailable, ImportUnavailable:
            raise LotUnavailable() from None
