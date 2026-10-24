"""Sourced checkpoints and explicit selection; no inferred trades or balances."""

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
from trading_db.import_contracts import StagedValue
from trading_db.imports import ImportTransaction, ImportUnavailable
from trading_db.workspace import WorkspaceDatabase, WorkspaceTransaction

MAX_RECORDS = 1000


class SnapshotUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__("Snapshot evidence is unavailable or conflicts with the current revision.")


@dataclass(frozen=True, repr=False)
class Snapshot:
    id: UUID
    revision: int
    source_row_id: UUID
    source_review_revision: int
    account_id: UUID
    position_id: UUID | None
    instrument_id: UUID | None
    currency: str | None
    kind: str
    status: str
    correction_reason: str | None
    as_of_date: date | None
    as_of_instant: str | None
    snapshot_scope: str | None
    booking_date: date | None
    observation_id: UUID
    source_id: UUID
    coverage: str
    period_start: date | None
    period_end: date | None
    components: tuple[StagedValue, ...]


@dataclass(frozen=True, repr=False)
class Selection:
    id: UUID
    revision: int
    account_id: UUID
    position_id: UUID | None
    currency: str | None
    snapshot_id: UUID | None
    snapshot_revision: int | None
    reason: str


@dataclass(frozen=True, repr=False)
class SelectedSnapshot:
    selection: Selection
    state: str
    snapshot: Snapshot | None


class SnapshotTransaction:
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
            raise SnapshotUnavailable()

    def _snapshot(self, row: Any) -> Snapshot:
        fields = {key: row[key] for key in Snapshot.__dataclass_fields__ if key != "components"}
        values = self._execute(
            "SELECT role,source,currency,missing_reason FROM app.snapshot_components WHERE "
            "owner_id=:owner AND snapshot_id=:id AND revision=:revision ORDER BY role",
            id=row["id"],
            revision=row["revision"],
        ).mappings()
        fields["components"] = tuple(StagedValue.model_validate(dict(value)) for value in values)
        return Snapshot(**fields)

    def _records(self, where: str, **parameters: Any) -> tuple[Snapshot, ...]:
        rows = self._execute(
            "SELECT e.*,b.observation_id,o.source_id,o.coverage,o.period_start,o.period_end "
            "FROM app.snapshot_records e JOIN app.staged_rows r ON r.owner_id=e.owner_id AND "
            "r.id=e.source_row_id JOIN app.import_batches b ON b.owner_id=r.owner_id AND "
            "b.id=r.batch_id JOIN app.source_observations o ON o.owner_id=b.owner_id AND "
            "o.id=b.observation_id WHERE e.owner_id=:owner AND " + where,
            **parameters,
        ).mappings()
        return tuple(self._snapshot(row) for row in rows)

    def get(self, snapshot_id: UUID) -> Snapshot | None:
        rows = self._records(
            "e.id=:id ORDER BY e.revision DESC LIMIT 1", id=identifier(snapshot_id)
        )
        return rows[0] if rows else None

    def by_source(self, row_id: UUID) -> Snapshot | None:
        rows = self._records("e.source_row_id=:id", id=identifier(row_id))
        return rows[0] if rows else None

    def history(
        self, snapshot_id: UUID, *, limit: int = 25, before: int | None = None
    ) -> tuple[Snapshot, ...]:
        page(limit, None)
        if before is not None:
            revision(before)
        return self._records(
            "e.id=:id AND (CAST(:before AS bigint) IS NULL OR e.revision<:before) ORDER BY "
            "e.revision DESC LIMIT :limit",
            id=identifier(snapshot_id),
            before=before,
            limit=limit,
        )

    def list(
        self, account_id: UUID, *, limit: int = 25, after: UUID | None = None
    ) -> tuple[Snapshot, ...]:
        page(limit, after)
        return self._records(
            "e.account_id=:account AND (CAST(:after AS uuid) IS NULL OR e.id>CAST(:after AS "
            "uuid)) AND NOT EXISTS (SELECT 1 FROM app.snapshot_records n WHERE "
            "n.owner_id=e.owner_id AND n.id=e.id AND n.revision>e.revision) ORDER BY e.id "
            "LIMIT :limit",
            account=identifier(account_id),
            after=after,
            limit=limit,
        )

    def record(
        self, row_id: UUID, *, expected_review_revision: int, position_id: UUID | None = None
    ) -> Snapshot:
        identifier(row_id)
        expected = revision(expected_review_revision)
        if position_id is not None:
            identifier(position_id)
        try:
            with self._accounts._write():
                replay = self.by_source(row_id)
                if replay:
                    if (
                        replay.revision != 1
                        or replay.source_review_revision != expected
                        or replay.position_id != position_id
                    ):
                        raise SnapshotUnavailable()
                    return replay
                return self._persist(row_id, expected, position_id, None, None)
        except AccountUnavailable, ImportUnavailable:
            raise SnapshotUnavailable() from None

    def correct(
        self,
        snapshot_id: UUID,
        row_id: UUID,
        *,
        expected_revision: int,
        expected_review_revision: int,
        reason: str,
    ) -> Snapshot:
        identifier(snapshot_id)
        identifier(row_id)
        expected, review = revision(expected_revision), revision(expected_review_revision)
        if type(reason) is not str or reason not in {
            "source_correction",
            "cancellation",
            "reinstatement",
        }:
            raise SnapshotUnavailable()
        try:
            with self._accounts._write():
                replay = self.by_source(row_id)
                if replay:
                    if (
                        replay.id != snapshot_id
                        or replay.revision != expected + 1
                        or replay.source_review_revision != review
                        or replay.correction_reason != reason
                    ):
                        raise SnapshotUnavailable()
                    return replay
                current = self.get(snapshot_id)
                if current is None or current.revision != expected:
                    raise SnapshotUnavailable()
                return self._persist(row_id, review, current.position_id, current, reason)
        except AccountUnavailable, ImportUnavailable:
            raise SnapshotUnavailable() from None

    def _persist(
        self,
        row_id: UUID,
        review: int,
        position_id: UUID | None,
        previous: Snapshot | None,
        reason: str | None,
    ) -> Snapshot:
        source, context = self._imports.reviewed(row_id, review)
        candidate = source.definition
        cancelled = candidate.kind == "cancellation"
        account, instrument = context["account"], context["instrument"]
        if account is None or candidate.kind not in {
            "position_snapshot",
            "cash_snapshot",
            "cancellation",
        }:
            raise SnapshotUnavailable()
        values = {value.role: value for value in candidate.values}
        currency: str | None = (
            values["net_cash"].currency if candidate.kind == "cash_snapshot" else None
        )
        if previous:
            if account.id != previous.account_id or (
                (not cancelled or candidate.instrument_identifier_id is not None)
                and instrument != previous.instrument_id
            ):
                raise SnapshotUnavailable()
            if (
                (cancelled and (previous.status != "active" or reason != "cancellation"))
                or (not cancelled and previous.status == "cancelled" and reason != "reinstatement")
                or (not cancelled and previous.status == "active" and reason != "source_correction")
                or (
                    not cancelled
                    and (candidate.kind != previous.kind or currency != previous.currency)
                )
            ):
                raise SnapshotUnavailable()
            if cancelled:
                instrument, currency = previous.instrument_id, previous.currency
        elif cancelled:
            raise SnapshotUnavailable()
        if (position_id is None) != (instrument is None):
            raise SnapshotUnavailable()
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
            raise SnapshotUnavailable()
        native = context["quote_currency"] or context["fund_currency"]
        if native is not None and any(
            value.role == "unit_price" and value.currency != native for value in candidate.values
        ):
            raise SnapshotUnavailable()
        self._budget("snapshot_records")
        self._budget("snapshot_components", len(values))
        record_id, version = (previous.id, previous.revision + 1) if previous else (uuid4(), 1)
        self._execute(
            "INSERT INTO app.snapshot_records (owner_id,id,revision,previous_revision,"
            "source_row_id,source_review_revision,account_id,position_id,instrument_id,"
            "currency,kind,status,correction_reason,as_of_date,as_of_instant,snapshot_scope,"
            "booking_date,value_count) VALUES (:owner,:id,:revision,:previous,:row,:review,"
            ":account,:position,:instrument,:currency,:kind,:status,:reason,:as_of_date,"
            ":instant,:scope,:booking,:count)",
            id=record_id,
            revision=version,
            previous=previous.revision if previous else None,
            row=row_id,
            review=review,
            account=account.id,
            position=position_id,
            instrument=instrument,
            currency=currency,
            kind=previous.kind if cancelled and previous else candidate.kind,
            status="cancelled" if cancelled else "active",
            reason=reason,
            as_of_date=candidate.as_of_date,
            instant=candidate.as_of_instant,
            scope=candidate.snapshot_scope,
            booking=candidate.booking_date,
            count=len(values),
        )
        for value in candidate.values:
            self._execute(
                "INSERT INTO app.snapshot_components (owner_id,snapshot_id,revision,role,"
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

    def _selection(self, row: Any) -> Selection:
        return Selection(**{key: row[key] for key in Selection.__dataclass_fields__})

    def selection(self, selection_id: UUID) -> Selection | None:
        row = (
            self._execute(
                "SELECT * FROM app.snapshot_selections WHERE owner_id=:owner AND id=:id "
                "ORDER BY revision DESC LIMIT 1",
                id=identifier(selection_id),
            )
            .mappings()
            .one_or_none()
        )
        return self._selection(row) if row else None

    def selections(
        self, account_id: UUID, *, limit: int = 25, after: UUID | None = None
    ) -> tuple[Selection, ...]:
        page(limit, after)
        rows = self._execute(
            "SELECT e.* FROM app.snapshot_selections e WHERE e.owner_id=:owner AND "
            "e.account_id=:account AND (CAST(:after AS uuid) IS NULL OR e.id>CAST(:after AS "
            "uuid)) AND NOT EXISTS (SELECT 1 FROM app.snapshot_selections n WHERE "
            "n.owner_id=e.owner_id AND n.id=e.id AND n.revision>e.revision) ORDER BY e.id "
            "LIMIT :limit",
            account=identifier(account_id),
            after=after,
            limit=limit,
        ).mappings()
        return tuple(self._selection(row) for row in rows)

    def selection_history(
        self, selection_id: UUID, *, limit: int = 25, before: int | None = None
    ) -> tuple[Selection, ...]:
        page(limit, None)
        if before is not None:
            revision(before)
        rows = self._execute(
            "SELECT * FROM app.snapshot_selections WHERE owner_id=:owner AND id=:id AND "
            "(CAST(:before AS bigint) IS NULL OR revision<:before) ORDER BY revision DESC "
            "LIMIT :limit",
            id=identifier(selection_id),
            before=before,
            limit=limit,
        ).mappings()
        return tuple(self._selection(row) for row in rows)

    def select(
        self,
        snapshot_id: UUID,
        *,
        expected_snapshot_revision: int,
        expected_revision: int,
        reason: str = "reviewed",
    ) -> Selection:
        identifier(snapshot_id)
        expected = revision(expected_revision, initial=True)
        version = revision(expected_snapshot_revision)
        if type(reason) is not str or reason not in {"reviewed", "newer_evidence", "correction"}:
            raise SnapshotUnavailable()
        try:
            with self._accounts._write():
                snapshot = self.get(snapshot_id)
                if snapshot is None:
                    raise SnapshotUnavailable()
                current_row = (
                    self._execute(
                        "SELECT * FROM app.snapshot_selections WHERE owner_id=:owner AND "
                        "account_id=:account AND position_id IS NOT DISTINCT FROM "
                        "CAST(:position AS uuid) AND currency IS NOT DISTINCT FROM "
                        "CAST(:currency AS text) ORDER BY revision DESC LIMIT 1",
                        account=snapshot.account_id,
                        position=snapshot.position_id,
                        currency=snapshot.currency,
                    )
                    .mappings()
                    .one_or_none()
                )
                current = self._selection(current_row) if current_row else None
                replay = self._selection_replay(current, expected, snapshot_id, version, reason)
                if replay:
                    return replay
                if (
                    (current.revision if current else 0) != expected
                    or snapshot.revision != version
                    or self._state(snapshot) != "selected"
                ):
                    raise SnapshotUnavailable()
                return self._choose(current, snapshot, reason)
        except AccountUnavailable, ImportUnavailable:
            raise SnapshotUnavailable() from None

    def clear(self, selection_id: UUID, *, expected_revision: int) -> Selection:
        identifier(selection_id)
        expected = revision(expected_revision)
        try:
            with self._accounts._write():
                current = self.selection(selection_id)
                replay = self._selection_replay(current, expected, None, None, "clear")
                if replay:
                    return replay
                if current is None or current.revision != expected or current.snapshot_id is None:
                    raise SnapshotUnavailable()
                account = self._accounts.get(current.account_id)
                if account is None or account.archived_at is not None:
                    raise SnapshotUnavailable()
                return self._choose(current, None, "clear")
        except AccountUnavailable:
            raise SnapshotUnavailable() from None

    def _selection_replay(
        self,
        current: Selection | None,
        expected: int,
        snapshot_id: UUID | None,
        snapshot_revision: int | None,
        reason: str,
    ) -> Selection | None:
        if current is None or current.revision <= expected:
            return None
        row = (
            self._execute(
                "SELECT * FROM app.snapshot_selections WHERE owner_id=:owner AND id=:id AND "
                "revision=:revision",
                id=current.id,
                revision=expected + 1,
            )
            .mappings()
            .one_or_none()
        )
        if row is None or (row["snapshot_id"], row["snapshot_revision"], row["reason"]) != (
            snapshot_id,
            snapshot_revision,
            reason,
        ):
            raise SnapshotUnavailable()
        return self._selection(row)

    def _choose(
        self, current: Selection | None, snapshot: Snapshot | None, reason: str
    ) -> Selection:
        target = current or snapshot
        assert target is not None
        self._budget("snapshot_selections")
        selected = Selection(
            current.id if current else uuid4(),
            current.revision + 1 if current else 1,
            target.account_id,
            target.position_id,
            target.currency,
            snapshot.id if snapshot else None,
            snapshot.revision if snapshot else None,
            reason,
        )
        self._execute(
            "INSERT INTO app.snapshot_selections (owner_id,id,revision,previous_revision,"
            "account_id,position_id,currency,snapshot_id,snapshot_revision,reason) VALUES "
            "(:owner,:id,:revision,:previous,:account_id,:position_id,:currency,:snapshot_id,"
            ":snapshot_revision,:reason)",
            previous=current.revision if current else None,
            **{key: getattr(selected, key) for key in Selection.__dataclass_fields__},
        )
        return selected

    def _state(self, snapshot: Snapshot) -> str:
        if snapshot.status != "active":
            return "cancelled"
        account = self._accounts.get(snapshot.account_id)
        if account is None or account.archived_at is not None:
            return "archived"
        row = self._imports.get_row(snapshot.source_row_id)
        if (
            row is None
            or row.status != "included"
            or row.decision is None
            or row.decision.revision != snapshot.source_review_revision
        ):
            return "stale"
        self._imports.get_batch(row.batch_id)
        if self._execute(
            "SELECT app.snapshot_conflict(:owner,:id,:revision)",
            id=snapshot.id,
            revision=snapshot.revision,
        ).scalar_one():
            return "conflicting"
        return "selected"

    def resolve(self, selection_id: UUID) -> SelectedSnapshot | None:
        # Keep selection, current version, review context and competing evidence
        # coherent across these reads while financial writers use the same lock.
        try:
            with self._accounts._write():
                return self._resolved(selection_id)
        except AccountUnavailable, ImportUnavailable:
            raise SnapshotUnavailable() from None

    def _resolved(self, selection_id: UUID) -> SelectedSnapshot | None:
        selection = self.selection(selection_id)
        if selection is None:
            return None
        if selection.snapshot_id is None:
            return SelectedSnapshot(selection, "unselected", None)
        snapshot = self.get(selection.snapshot_id)
        if snapshot is None or snapshot.revision != selection.snapshot_revision:
            return SelectedSnapshot(selection, "stale", None)
        state = self._state(snapshot)
        return SelectedSnapshot(selection, state, snapshot if state == "selected" else None)


class SnapshotDatabase:
    def __init__(self, url: URL, project: str) -> None:
        self._workspace = WorkspaceDatabase(url, project)

    def close(self) -> None:
        self._workspace.close()

    @contextmanager
    def transaction(self, owner_id: UUID) -> Iterator[SnapshotTransaction]:
        try:
            with self._workspace.transaction(owner_id) as unit:
                yield SnapshotTransaction(unit)
        except SQLAlchemyError, AccountUnavailable, ImportUnavailable:
            raise SnapshotUnavailable() from None
