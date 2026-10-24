"""Exact provider-scoped event reuse; equal-looking transactions stay distinct."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import URL
from sqlalchemy.exc import SQLAlchemyError

from trading_db.account_keys import ReferenceKeys, ReferenceUnavailable, reference
from trading_db.accounts import AccountTransaction, AccountUnavailable, identifier, page, revision
from trading_db.connections import DatabaseFailure
from trading_db.events import EventTransaction, EventUnavailable, FinancialEvent
from trading_db.import_contracts import EVENT_KINDS, CandidateDefinition, StagedValue
from trading_db.imports import ImportTransaction, ImportUnavailable
from trading_db.provider_keys import ProviderKeys
from trading_db.workspace import WorkspaceDatabase, WorkspaceTransaction

MAX_RECORDS = 1000


class EventEvidenceUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__("Event identity or evidence is unavailable or conflicts.")


@dataclass(frozen=True, repr=False)
class EventEvidence:
    source_row_id: UUID
    review_revision: int
    identity_id: UUID | None
    event: FinancialEvent

    @property
    def reused(self) -> bool:
        return self.event.source_row_id != self.source_row_id


def same_economics(
    event: FinancialEvent,
    candidate: CandidateDefinition,
    account_id: UUID,
    position_id: UUID | None,
    instrument_id: UUID | None,
) -> bool:
    dates = ("trade_date", "settlement_date", "booking_date", "value_date")

    def values(
        components: tuple[StagedValue, ...],
    ) -> dict[str, tuple[Decimal | None, str | None, str | None]]:
        return {
            item.role: (item.financial().value, item.currency, item.missing_reason)
            for item in components
        }

    return (
        event.status == "active"
        and (event.account_id, event.position_id, event.instrument_id)
        == (account_id, position_id, instrument_id)
        and (event.kind, event.posting_state) == (candidate.kind, candidate.posting_state)
        and all(
            (getattr(event, key).isoformat() if getattr(event, key) else None)
            == getattr(candidate, key)
            for key in dates
        )
        and values(event.components) == values(candidate.values)
    )


class EventEvidenceTransaction:
    def __init__(self, unit: WorkspaceTransaction, keys: ReferenceKeys | None) -> None:
        self._accounts = AccountTransaction(unit, None)
        self._imports = ImportTransaction(unit)
        self._events = EventTransaction(unit)
        self._keys = ProviderKeys(keys) if keys is not None else None

    def _execute(self, sql: str, **parameters: Any) -> Any:
        return self._accounts._execute(sql, **parameters)

    @contextmanager
    def _write(self) -> Iterator[None]:
        try:
            with self._accounts._write():
                yield
        except AccountUnavailable, ImportUnavailable, EventUnavailable, ReferenceUnavailable:
            raise EventEvidenceUnavailable() from None

    def _identities(self) -> tuple[ProviderKeys, list[tuple[Any, str]]]:
        if self._keys is None:
            raise EventEvidenceUnavailable()
        rows = list(
            self._execute(
                "SELECT * FROM app.event_provider_identities WHERE owner_id=:owner ORDER BY id "
                "LIMIT :limit",
                limit=MAX_RECORDS + 1,
            ).mappings()
        )
        if len(rows) > MAX_RECORDS:
            raise EventEvidenceUnavailable()
        values = [(row, self._keys.open(row)) for row in rows]
        names = [(row["source_id"], row["kind"], value) for row, value in values]
        if len(set(names)) != len(names):
            raise EventEvidenceUnavailable()
        return self._keys, values

    def _link(self, row: Any) -> EventEvidence:
        event = (
            self._execute(
                "SELECT * FROM app.financial_events WHERE owner_id=:owner AND id=:id "
                "AND revision=:revision",
                id=row["event_id"],
                revision=row["event_revision"],
            )
            .mappings()
            .one()
        )
        return EventEvidence(
            row["source_row_id"],
            row["review_revision"],
            row["identity_id"],
            self._events._event(event),
        )

    def get(self, row_id: UUID) -> EventEvidence | None:
        row = (
            self._execute(
                "SELECT * FROM app.event_evidence_links WHERE owner_id=:owner "
                "AND source_row_id=:id",
                id=identifier(row_id),
            )
            .mappings()
            .one_or_none()
        )
        return self._link(row) if row else None

    def list(
        self, event_id: UUID, *, limit: int = 25, after: UUID | None = None
    ) -> tuple[EventEvidence, ...]:
        page(limit, after)
        rows = self._execute(
            "SELECT * FROM app.event_evidence_links WHERE owner_id=:owner AND event_id=:id "
            "AND (CAST(:after AS uuid) IS NULL OR source_row_id>CAST(:after AS uuid)) "
            "ORDER BY source_row_id LIMIT :limit",
            id=identifier(event_id),
            limit=limit,
            after=after,
        ).mappings()
        return tuple(self._link(row) for row in rows)

    def _budget(self, table: str) -> None:
        if (
            self._execute(f"SELECT count(*) FROM app.{table} WHERE owner_id=:owner").scalar_one()
            >= MAX_RECORDS
        ):
            raise EventEvidenceUnavailable()

    def record(
        self,
        row_id: UUID,
        *,
        expected_review_revision: int,
        position_id: UUID | None = None,
        provider_reference: str | None = None,
    ) -> EventEvidence:
        identifier(row_id)
        expected = revision(expected_review_revision)
        if position_id is not None:
            identifier(position_id)
        if provider_reference is not None:
            reference(provider_reference)
        with self._write():
            replay = self.get(row_id)
            if provider_reference is None:
                if replay is not None:
                    raise EventEvidenceUnavailable()
                event = self._events.record(
                    row_id, expected_review_revision=expected, position_id=position_id
                )
                return EventEvidence(row_id, expected, None, event)
            keys, identities = self._identities()
            if replay:
                known = next(
                    (value for row, value in identities if row["id"] == replay.identity_id), None
                )
                if (
                    known != provider_reference
                    or replay.review_revision != expected
                    or replay.event.position_id != position_id
                ):
                    raise EventEvidenceUnavailable()
                return replay
            source, context = self._imports.reviewed(row_id, expected)
            candidate, account = source.definition, context["account"]
            if candidate.kind not in EVENT_KINDS or account is None:
                raise EventEvidenceUnavailable()
            matched = next(
                (
                    row
                    for row, value in identities
                    if (row["source_id"], row["kind"], value)
                    == (context["source_id"], candidate.kind, provider_reference)
                ),
                None,
            )
            if matched:
                current = self._events.get(matched["event_id"])
                if current is None or not same_economics(
                    current, candidate, account.id, position_id, context["instrument"]
                ):
                    raise EventEvidenceUnavailable()
                event = current
                identity_id = matched["id"]
            else:
                self._budget("event_provider_identities")
                event = self._events.record(
                    row_id, expected_review_revision=expected, position_id=position_id
                )
                identity_id = uuid4()
                self._execute(
                    "INSERT INTO app.event_provider_identities (owner_id,id,source_id,kind,"
                    "event_id,event_revision,key_version,key_check,fingerprint,"
                    "encrypted_reference) "
                    "VALUES (:owner,:id,:source,:kind,:event,1,:key_version,:key_check,"
                    ":fingerprint,:encrypted_reference)",
                    id=identity_id,
                    source=context["source_id"],
                    kind=candidate.kind,
                    event=event.id,
                    **keys.seal(
                        self._accounts._unit._owner_id,
                        identity_id,
                        context["source_id"],
                        candidate.kind,
                        provider_reference,
                    ),
                )
            self._budget("event_evidence_links")
            self._execute(
                "INSERT INTO app.event_evidence_links (owner_id,source_row_id,review_revision,"
                "identity_id,event_id,event_revision) VALUES (:owner,:row,:review,:identity,"
                ":event,:revision)",
                row=row_id,
                review=expected,
                identity=identity_id,
                event=event.id,
                revision=event.revision,
            )
            return EventEvidence(row_id, expected, identity_id, event)

    def rotate_references(self) -> int:
        with self._write():
            keys, identities = self._identities()
            changed = 0
            for row, value in identities:
                if row["key_version"] == keys.active:
                    continue
                self._execute(
                    "UPDATE app.event_provider_identities SET key_version=:key_version,"
                    "key_check=:key_check,fingerprint=:fingerprint,"
                    "encrypted_reference=:encrypted_reference WHERE owner_id=:owner AND id=:id",
                    id=row["id"],
                    **keys.seal(row["owner_id"], row["id"], row["source_id"], row["kind"], value),
                )
                changed += 1
            return changed


class EventEvidenceDatabase:
    def __init__(self, url: URL, project: str, keys: ReferenceKeys | None) -> None:
        self._workspace = WorkspaceDatabase(url, project)
        self._keys = keys

    def close(self) -> None:
        self._workspace.close()

    @contextmanager
    def transaction(self, owner_id: UUID) -> Iterator[EventEvidenceTransaction]:
        try:
            with self._workspace.transaction(owner_id) as unit:
                yield EventEvidenceTransaction(unit, self._keys)
        except SQLAlchemyError, AccountUnavailable, ReferenceUnavailable:
            raise EventEvidenceUnavailable() from None
