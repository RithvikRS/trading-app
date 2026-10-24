"""Atomic completion of reviewed partial/snapshot evidence; no full-ledger claim."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import URL
from sqlalchemy.exc import SQLAlchemyError

from trading_db.account_keys import ReferenceKeys, ReferenceUnavailable
from trading_db.accounts import AccountTransaction, AccountUnavailable, identifier, page
from trading_db.completion_baseline import CompletionBaseline, CompletionUnavailable
from trading_db.completion_contracts import (
    CompletionManifest,
    CompletionRequest,
    CompletionRow,
    canonical_request,
    parse_manifest,
)
from trading_db.event_evidence import (
    EventEvidenceTransaction,
    EventEvidenceUnavailable,
    same_economics,
)
from trading_db.events import EventTransaction, EventUnavailable, FinancialEvent
from trading_db.import_contracts import EVENT_KINDS, LOT_KINDS
from trading_db.imports import ImportTransaction, ImportUnavailable, StagedRow
from trading_db.lots import LotObservation, LotTransaction, LotUnavailable
from trading_db.snapshots import Snapshot, SnapshotTransaction, SnapshotUnavailable
from trading_db.workspace import WorkspaceDatabase, WorkspaceTransaction

type Family = Literal["event", "lot", "snapshot"]
type Record = FinancialEvent | LotObservation | Snapshot


@dataclass(frozen=True, repr=False)
class CompletedRow:
    source_row_id: UUID
    review_revision: int
    operation: str
    outcome: str
    event_id: UUID | None
    lot_observation_id: UUID | None
    snapshot_id: UUID | None
    record_revision: int | None
    provider_identity_id: UUID | None
    selection_id: UUID | None
    selection_revision: int | None


@dataclass(frozen=True, repr=False)
class CompletionReceipt:
    id: UUID
    manifest: CompletionManifest
    coverage: str
    created_at: datetime
    rows: tuple[CompletedRow, ...]


class CompletionTransaction:
    def __init__(self, unit: WorkspaceTransaction, keys: ReferenceKeys | None) -> None:
        self._accounts = AccountTransaction(unit, None)
        self._imports = ImportTransaction(unit)
        self._events = EventTransaction(unit)
        self._evidence = EventEvidenceTransaction(unit, keys)
        self._lots = LotTransaction(unit)
        self._snapshots = SnapshotTransaction(unit)
        self._baseline = CompletionBaseline(unit)

    def _execute(self, sql: str, **parameters: Any) -> Any:
        return self._accounts._execute(sql, **parameters)

    def baseline(self) -> str:
        return self._baseline.current()

    def _receipt(self, root: Any) -> CompletionReceipt:
        rows = self._execute(
            "SELECT source_row_id,review_revision,operation,outcome,event_id,lot_observation_id,"
            "snapshot_id,record_revision,provider_identity_id,selection_id,selection_revision "
            "FROM app.completion_rows WHERE owner_id=:owner AND receipt_id=:id "
            "ORDER BY source_row_id LIMIT 101",
            id=root["id"],
        ).mappings()
        saved = tuple(CompletedRow(**row) for row in rows)
        if len(saved) != root["row_count"]:
            raise CompletionUnavailable()
        return CompletionReceipt(
            root["id"],
            parse_manifest(root["request_canonical"]),
            root["coverage"],
            root["created_at"],
            saved,
        )

    def get(self, receipt_id: UUID) -> CompletionReceipt | None:
        root = (
            self._execute(
                "SELECT * FROM app.completion_receipts WHERE owner_id=:owner AND id=:id",
                id=identifier(receipt_id),
            )
            .mappings()
            .one_or_none()
        )
        return self._receipt(root) if root else None

    def list(self, *, limit: int = 25, after: UUID | None = None) -> tuple[CompletionReceipt, ...]:
        page(limit, after)
        roots = self._execute(
            "SELECT * FROM app.completion_receipts WHERE owner_id=:owner "
            "AND (CAST(:after AS uuid) IS NULL OR id>CAST(:after AS uuid)) "
            "ORDER BY id LIMIT :limit",
            after=after,
            limit=limit,
        ).mappings()
        return tuple(self._receipt(root) for root in roots)

    def _raw_targets(self, row_id: UUID) -> set[tuple[str, UUID]]:
        records = self._execute(
            "SELECT kind,id FROM app.completion_raw_targets(:owner,:row) LIMIT 1001", row=row_id
        ).all()
        if len(records) > 1000:
            raise CompletionUnavailable()
        return {(row[0], row[1]) for row in records}

    def _service(self, family: Family) -> EventTransaction | LotTransaction | SnapshotTransaction:
        if family == "event":
            return self._events
        if family == "lot":
            return self._lots
        return self._snapshots

    def _private_replay(self, request: CompletionRequest, receipt: CompletionReceipt) -> None:
        provided = [row for row in request.rows if row.provider_reference is not None]
        if not provided:
            return
        _, identities = self._evidence._identities()
        references = {row["id"]: value for row, value in identities}
        saved = {row.source_row_id: row for row in receipt.rows}
        if any(
            references.get(saved[row.row_id].provider_identity_id) != row.provider_reference
            for row in provided
        ):
            raise CompletionUnavailable()

    def _correct(
        self, choice: CompletionRow, raw: set[tuple[str, UUID]]
    ) -> tuple[Family, Record, None]:
        family, target, version, reason = (
            choice.target_kind,
            choice.target_id,
            choice.target_revision,
            choice.correction_reason,
        )
        if family is None or target is None or version is None or reason is None:
            raise CompletionUnavailable()
        if raw and raw != {(family, target)}:
            raise CompletionUnavailable()
        service = self._service(family)
        result = service.correct(
            target,
            choice.row_id,
            expected_revision=version,
            expected_review_revision=choice.review_revision,
            reason=reason,
        )
        if service.get(result.id) != result:
            raise CompletionUnavailable()
        return family, result, None

    def _event(
        self, choice: CompletionRow, source: StagedRow, raw: set[tuple[str, UUID]]
    ) -> tuple[Family, Record, UUID | None]:
        if choice.lot_id is not None or choice.lot_source_row_id is not None:
            raise CompletionUnavailable()
        primary = self._events.by_source(choice.row_id)
        if primary is not None and primary.revision != 1:
            raise CompletionUnavailable()
        linked = self._evidence.get(choice.row_id)
        prior = primary or (linked.event if linked else None)
        if prior and self._events.get(prior.id) != prior:
            raise CompletionUnavailable()
        if raw and (len(raw) != 1 or next(iter(raw))[0] != "event"):
            raise CompletionUnavailable()
        target = prior.id if prior else next(iter(raw))[1] if raw else None
        if target is not None:
            if raw and raw != {("event", target)}:
                raise CompletionUnavailable()
            current = self._events.get(target)
            context = self._imports._context(
                {
                    "batch_id": source.batch_id,
                    "instrument_identifier_id": source.definition.instrument_identifier_id,
                }
            )
            account = context["account"]
            if (
                current is None
                or account is None
                or not same_economics(
                    current,
                    source.definition,
                    account.id,
                    choice.position_id,
                    context["instrument"],
                )
            ):
                raise CompletionUnavailable()
            if choice.provider_reference is None:
                return "event", current, None
            _, identities = self._evidence._identities()
            if not any(
                (identity["event_id"], identity["source_id"], identity["kind"], value)
                == (target, context["source_id"], source.definition.kind, choice.provider_reference)
                for identity, value in identities
            ):
                raise CompletionUnavailable()
        result = self._evidence.record(
            choice.row_id,
            expected_review_revision=choice.review_revision,
            position_id=choice.position_id,
            provider_reference=choice.provider_reference,
        )
        return "event", result.event, result.identity_id

    def _record(
        self,
        choice: CompletionRow,
        source: StagedRow,
        done: dict[UUID, tuple[Family, Record, UUID | None]],
        source_rows: dict[UUID, StagedRow],
    ) -> tuple[Family, Record, UUID | None]:
        raw = self._raw_targets(choice.row_id)
        if choice.operation == "correct":
            return self._correct(choice, raw)
        if source.definition.kind in EVENT_KINDS:
            return self._event(choice, source, raw)
        if raw or choice.provider_reference is not None:
            raise CompletionUnavailable()
        if source.definition.kind in LOT_KINDS:
            if choice.position_id is None:
                raise CompletionUnavailable()
            lot_id = choice.lot_id
            if choice.lot_source_row_id is not None:
                anchor = done.get(choice.lot_source_row_id)
                origin = source_rows.get(choice.lot_source_row_id)
                if (
                    anchor is None
                    or not isinstance(anchor[1], LotObservation)
                    or origin is None
                    or (
                        origin.definition.kind != "lot_acquisition"
                        or origin.definition.occurrence >= source.definition.occurrence
                    )
                ):
                    raise CompletionUnavailable()
                lot_id = anchor[1].lot_id
            result = self._lots.record(
                choice.row_id,
                choice.position_id,
                expected_review_revision=choice.review_revision,
                lot_id=lot_id,
            )
            if self._lots.get(result.id) != result:
                raise CompletionUnavailable()
            return "lot", result, None
        if choice.lot_id is not None or choice.lot_source_row_id is not None:
            raise CompletionUnavailable()
        if source.definition.kind not in ("position_snapshot", "cash_snapshot"):
            raise CompletionUnavailable()
        snapshot = self._snapshots.record(
            choice.row_id,
            expected_review_revision=choice.review_revision,
            position_id=choice.position_id,
        )
        if self._snapshots.get(snapshot.id) != snapshot:
            raise CompletionUnavailable()
        return "snapshot", snapshot, None

    def complete(self, request: CompletionRequest) -> CompletionReceipt:
        try:
            valid = CompletionRequest.model_validate(request)
            canonical = canonical_request(valid)
            with self._accounts._write():
                previous = (
                    self._execute(
                        "SELECT * FROM app.completion_receipts WHERE owner_id=:owner "
                        "AND idempotency_key=:key",
                        key=valid.idempotency_key,
                    )
                    .mappings()
                    .one_or_none()
                )
                if previous:
                    if previous["request_canonical"] != canonical:
                        raise CompletionUnavailable()
                    receipt = self._receipt(previous)
                    self._private_replay(valid, receipt)
                    return receipt
                if self._execute(
                    "SELECT EXISTS(SELECT 1 FROM app.completion_receipts WHERE owner_id=:owner "
                    "AND batch_id=:batch)",
                    batch=valid.batch_id,
                ).scalar_one():
                    raise CompletionUnavailable()
                with self._baseline.guard(valid.baseline):
                    return self._complete(valid, canonical)
        except (
            AccountUnavailable,
            ImportUnavailable,
            EventUnavailable,
            EventEvidenceUnavailable,
            LotUnavailable,
            SnapshotUnavailable,
            ReferenceUnavailable,
            ValidationError,
        ):
            raise CompletionUnavailable() from None

    def _complete(self, request: CompletionRequest, canonical: str) -> CompletionReceipt:
        batch = self._imports.get_batch(request.batch_id)
        if (
            batch is None
            or batch.revision != request.batch_revision
            or (
                self._imports.latest_batch(batch.observation_id) != batch
                or not self._imports._current_observation(batch.observation_id)
            )
        ):
            raise CompletionUnavailable()
        observation = self._imports.get_observation(batch.observation_id)
        if (
            observation is None
            or request.mode != "limited"
            or observation.definition.coverage == "complete_activity"
        ):
            raise CompletionUnavailable()
        rows = self._imports.rows(batch.id, limit=100)
        choices = {row.row_id: row for row in request.rows}
        sources = {row.id: row for row in rows}
        if choices.keys() != sources.keys():
            raise CompletionUnavailable()
        for row in rows:
            choice = choices[row.id]
            if (
                row.decision is None
                or row.decision.revision != choice.review_revision
                or (row.status != ("excluded" if choice.operation == "exclude" else "included"))
            ):
                raise CompletionUnavailable()
        receipt_id = uuid4()
        self._execute(
            "INSERT INTO app.completion_receipts (owner_id,id,idempotency_key,batch_id,"
            "batch_revision,baseline_digest,request_canonical,request_digest,mode,coverage,"
            "row_count,selection_count) VALUES (:owner,:id,:key,:batch,:version,:baseline,"
            ":canonical,:digest,'limited',:coverage,:rows,:selections)",
            id=receipt_id,
            key=request.idempotency_key,
            batch=batch.id,
            version=batch.revision,
            baseline=request.baseline,
            canonical=canonical,
            digest=hashlib.sha256(canonical.encode()).hexdigest(),
            coverage=observation.definition.coverage,
            rows=len(rows),
            selections=len(request.selections),
        )
        done: dict[UUID, tuple[Family, Record, UUID | None]] = {}
        for row in rows:
            if choices[row.id].operation != "exclude":
                done[row.id] = self._record(choices[row.id], row, done, sources)
                if observation.definition.coverage == "snapshot" and done[row.id][0] == "event":
                    raise CompletionUnavailable()
        selections = {}
        for requested_selection in request.selections:
            family, record, _ = done[requested_selection.row_id]
            if family != "snapshot":
                raise CompletionUnavailable()
            selected = self._snapshots.select(
                record.id,
                expected_snapshot_revision=record.revision,
                expected_revision=requested_selection.expected_revision,
                reason=requested_selection.reason,
            )
            if self._snapshots.selection(selected.id) != selected:
                raise CompletionUnavailable()
            selections[requested_selection.row_id] = selected
        for row in rows:
            choice = choices[row.id]
            effect = done.get(row.id)
            effect_family, effect_record, identity = effect if effect else (None, None, None)
            choice_selection = selections.get(row.id)
            outcome = (
                "excluded"
                if effect_record is None
                else "corrected"
                if choice.operation == "correct"
                else ("recorded" if effect_record.source_row_id == row.id else "linked")
            )
            self._execute(
                "INSERT INTO app.completion_rows (owner_id,receipt_id,source_row_id,"
                "review_revision,operation,outcome,event_id,lot_observation_id,snapshot_id,"
                "record_revision,provider_identity_id,selection_id,selection_revision) VALUES "
                "(:owner,:receipt,:row,:review,:operation,:outcome,:event,:lot,:snapshot,"
                ":revision,:identity,:selection,:selection_revision)",
                receipt=receipt_id,
                row=row.id,
                review=choice.review_revision,
                operation=choice.operation,
                outcome=outcome,
                event=effect_record.id if effect_record and effect_family == "event" else None,
                lot=effect_record.id if effect_record and effect_family == "lot" else None,
                snapshot=effect_record.id
                if effect_record and effect_family == "snapshot"
                else None,
                revision=effect_record.revision if effect_record else None,
                identity=identity,
                selection=choice_selection.id if choice_selection else None,
                selection_revision=choice_selection.revision if choice_selection else None,
            )
        result = self.get(receipt_id)
        if result is None:
            raise CompletionUnavailable()
        return result


class CompletionDatabase:
    def __init__(self, url: URL, project: str, keys: ReferenceKeys | None) -> None:
        self._workspace = WorkspaceDatabase(url, project)
        self._keys = keys

    def close(self) -> None:
        self._workspace.close()

    @contextmanager
    def transaction(self, owner_id: UUID) -> Iterator[CompletionTransaction]:
        try:
            with self._workspace.transaction(owner_id) as unit:
                yield CompletionTransaction(unit, self._keys)
        except SQLAlchemyError, AccountUnavailable, ReferenceUnavailable, ValueError:
            raise CompletionUnavailable() from None
