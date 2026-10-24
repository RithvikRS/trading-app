"""Owned immutable market evidence and explicit, revisioned source selections."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import URL
from sqlalchemy.exc import SQLAlchemyError

from trading_db.accounts import AccountTransaction, AccountUnavailable, identifier, page, revision
from trading_db.connections import DatabaseFailure
from trading_db.market_contracts import MarketDefinition, MarketTarget
from trading_db.workspace import WorkspaceDatabase, WorkspaceTransaction

MAX_RECORDS = 1000
# All fragments derive from committed field names, never request input.
TARGET_MATCH = " AND ".join(
    f"{key} IS NOT DISTINCT FROM CAST(:{key} AS {'uuid' if key.endswith('_id') else 'text'})"
    for key in MarketTarget.model_fields
)


class MarketUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__("Market evidence is unavailable or conflicts with the current revision.")


@dataclass(frozen=True, repr=False)
class MarketObservation:
    id: UUID
    definition: MarketDefinition


@dataclass(frozen=True, repr=False)
class MarketSelection:
    id: UUID
    revision: int
    target: MarketTarget
    observation_id: UUID | None
    reason: str


@dataclass(frozen=True, repr=False)
class SelectedMarket:
    selection: MarketSelection
    state: str
    observation: MarketObservation | None


class MarketTransaction:
    def __init__(self, unit: WorkspaceTransaction) -> None:
        self._accounts = AccountTransaction(unit, None)

    def _execute(self, sql: str, **parameters: Any) -> Any:
        return self._accounts._execute(sql, **parameters)

    @contextmanager
    def _write(self) -> Iterator[None]:
        try:
            with self._accounts._write():
                yield
        except AccountUnavailable:
            raise MarketUnavailable() from None

    def _budget(self, table: str) -> None:
        if (
            self._execute(f"SELECT count(*) FROM app.{table} WHERE owner_id=:owner").scalar_one()
            >= MAX_RECORDS
        ):
            raise MarketUnavailable()

    @staticmethod
    def _observation(row: Any) -> MarketObservation:
        fields = {key: row[key] for key in MarketDefinition.model_fields}
        fields["observed_on"] = row["observed_on"].isoformat()
        return MarketObservation(row["id"], MarketDefinition.model_validate(fields))

    @staticmethod
    def _selection(row: Any) -> MarketSelection:
        target = MarketTarget.model_validate({key: row[key] for key in MarketTarget.model_fields})
        return MarketSelection(
            row["id"], row["revision"], target, row["observation_id"], row["reason"]
        )

    def get(self, observation_id: UUID) -> MarketObservation | None:
        row = (
            self._execute(
                "SELECT * FROM app.market_observations WHERE owner_id=:owner AND id=:id",
                id=identifier(observation_id),
            )
            .mappings()
            .one_or_none()
        )
        return self._observation(row) if row else None

    def list(
        self, target: MarketTarget, *, limit: int = 25, after: UUID | None = None
    ) -> tuple[MarketObservation, ...]:
        valid = MarketTarget.model_validate(target.model_dump())
        page(limit, after)
        rows = self._execute(
            "SELECT * FROM app.market_observations WHERE owner_id=:owner AND "
            + TARGET_MATCH
            + " AND (CAST(:after AS uuid) IS NULL OR id>CAST(:after AS uuid)) "
            "ORDER BY id LIMIT :limit",
            **valid.model_dump(),
            limit=limit,
            after=after,
        ).mappings()
        return tuple(self._observation(row) for row in rows)

    def record(self, definition: MarketDefinition) -> MarketObservation:
        valid = MarketDefinition.model_validate(definition.model_dump())
        with self._write():
            row = (
                self._execute(
                    "SELECT * FROM app.market_observations WHERE owner_id=:owner AND "
                    "namespace=:namespace AND digest_algorithm=:digest_algorithm "
                    "AND digest=:digest "
                    "AND occurrence=:occurrence AND normalizer=:normalizer AND "
                    "normalizer_version=:normalizer_version",
                    **valid.model_dump(),
                )
                .mappings()
                .one_or_none()
            )
            if row:
                existing = self._observation(row)
                if existing.definition != valid:
                    raise MarketUnavailable()
                return existing
            if valid.previous_id is not None:
                previous = self.get(valid.previous_id)
                if (
                    previous is None
                    or previous.definition.target() != valid.target()
                    or self._superseded(previous.id)
                ):
                    raise MarketUnavailable()
            self._budget("market_observations")
            observation_id = uuid4()
            columns = ",".join(MarketDefinition.model_fields)
            values = ",".join(":" + key for key in MarketDefinition.model_fields)
            self._execute(
                f"INSERT INTO app.market_observations (owner_id,id,{columns},amount) "
                f"VALUES (:owner,:id,{values},:amount)",
                id=observation_id,
                amount=valid.reported().value,
                **valid.model_dump(),
            )
            return MarketObservation(observation_id, valid)

    def _superseded(self, observation_id: UUID) -> bool:
        return bool(
            self._execute(
                "SELECT EXISTS (SELECT 1 FROM app.market_observations WHERE "
                "owner_id=:owner AND previous_id=:id)",
                id=observation_id,
            ).scalar_one()
        )

    def selection(self, selection_id: UUID) -> MarketSelection | None:
        row = (
            self._execute(
                "SELECT * FROM app.market_selections WHERE owner_id=:owner AND id=:id "
                "ORDER BY revision DESC LIMIT 1",
                id=identifier(selection_id),
            )
            .mappings()
            .one_or_none()
        )
        return self._selection(row) if row else None

    def selections(
        self, *, limit: int = 25, after: UUID | None = None
    ) -> tuple[MarketSelection, ...]:
        page(limit, after)
        rows = self._execute(
            "SELECT s.* FROM app.market_selections s WHERE owner_id=:owner AND "
            "(CAST(:after AS uuid) IS NULL OR id>CAST(:after AS uuid)) AND NOT EXISTS "
            "(SELECT 1 FROM app.market_selections n WHERE n.owner_id=s.owner_id AND n.id=s.id "
            "AND n.revision>s.revision) ORDER BY id LIMIT :limit",
            limit=limit,
            after=after,
        ).mappings()
        return tuple(self._selection(row) for row in rows)

    def selection_history(
        self, selection_id: UUID, *, limit: int = 25, before: int | None = None
    ) -> tuple[MarketSelection, ...]:
        page(limit, None)
        if before is not None:
            revision(before)
        rows = self._execute(
            "SELECT * FROM app.market_selections WHERE owner_id=:owner AND id=:id "
            "AND (CAST(:before AS bigint) IS NULL OR revision<:before) ORDER BY revision DESC "
            "LIMIT :limit",
            id=identifier(selection_id),
            limit=limit,
            before=before,
        ).mappings()
        return tuple(self._selection(row) for row in rows)

    def _replay(
        self,
        current: MarketSelection | None,
        expected: int,
        observation_id: UUID | None,
        reason: str,
    ) -> MarketSelection | None:
        if current is None or current.revision <= expected:
            return None
        row = (
            self._execute(
                "SELECT * FROM app.market_selections WHERE owner_id=:owner AND id=:id "
                "AND revision=:revision",
                id=current.id,
                revision=expected + 1,
            )
            .mappings()
            .one_or_none()
        )
        if row is None or (row["observation_id"], row["reason"]) != (observation_id, reason):
            raise MarketUnavailable()
        return self._selection(row)

    def select(
        self, observation_id: UUID, *, expected_revision: int, reason: str = "reviewed"
    ) -> MarketSelection:
        identifier(observation_id)
        expected = revision(expected_revision, initial=True)
        if type(reason) is not str or reason not in {"reviewed", "replacement", "correction"}:
            raise MarketUnavailable()
        with self._write():
            observation = self.get(observation_id)
            if observation is None:
                raise MarketUnavailable()
            target = observation.definition.target()
            row = (
                self._execute(
                    "SELECT * FROM app.market_selections WHERE owner_id=:owner AND "
                    + TARGET_MATCH
                    + " ORDER BY revision DESC LIMIT 1",
                    **target.model_dump(),
                )
                .mappings()
                .one_or_none()
            )
            current = self._selection(row) if row else None
            replay = self._replay(current, expected, observation_id, reason)
            if replay:
                return replay
            if (
                (current.revision if current else 0) != expected
                or not observation.definition.usable
                or self._superseded(observation_id)
                or (current is None and reason != "reviewed")
                or (current is not None and reason == "reviewed")
                or (
                    reason == "correction"
                    and (
                        current is None
                        or observation.definition.previous_id != current.observation_id
                    )
                )
            ):
                raise MarketUnavailable()
            return self._choose(current, target, observation_id, reason)

    def clear(self, selection_id: UUID, *, expected_revision: int) -> MarketSelection:
        expected = revision(expected_revision)
        with self._write():
            current = self.selection(selection_id)
            replay = self._replay(current, expected, None, "clear")
            if replay:
                return replay
            if current is None or current.revision != expected or current.observation_id is None:
                raise MarketUnavailable()
            return self._choose(current, current.target, None, "clear")

    def _choose(
        self,
        current: MarketSelection | None,
        target: MarketTarget,
        observation_id: UUID | None,
        reason: str,
    ) -> MarketSelection:
        self._budget("market_selections")
        selected = MarketSelection(
            current.id if current else uuid4(),
            current.revision + 1 if current else 1,
            target,
            observation_id,
            reason,
        )
        columns = ",".join(MarketTarget.model_fields)
        values = ",".join(":" + key for key in MarketTarget.model_fields)
        self._execute(
            f"INSERT INTO app.market_selections (owner_id,id,revision,previous_revision,"
            f"{columns},observation_id,reason) VALUES (:owner,:id,:revision,:previous,"
            f"{values},:observation,:reason)",
            id=selected.id,
            revision=selected.revision,
            previous=current.revision if current else None,
            observation=observation_id,
            reason=reason,
            **target.model_dump(),
        )
        return selected

    def resolve(self, selection_id: UUID) -> SelectedMarket | None:
        # Serialize with observations/corrections so multi-read resolution is coherent.
        with self._write():
            selection = self.selection(selection_id)
            if selection is None:
                return None
            if selection.observation_id is None:
                return SelectedMarket(selection, "unselected", None)
            observation = self.get(selection.observation_id)
            if observation is None or self._superseded(observation.id):
                return SelectedMarket(selection, "stale", None)
            if not observation.definition.usable:
                return SelectedMarket(selection, "unusable", None)
            return SelectedMarket(selection, "selected", observation)


class MarketDatabase:
    def __init__(self, url: URL, project: str) -> None:
        self._workspace = WorkspaceDatabase(url, project)

    def close(self) -> None:
        self._workspace.close()

    @contextmanager
    def transaction(self, owner_id: UUID) -> Iterator[MarketTransaction]:
        try:
            with self._workspace.transaction(owner_id) as unit:
                yield MarketTransaction(unit)
        except SQLAlchemyError, AccountUnavailable:
            raise MarketUnavailable() from None
