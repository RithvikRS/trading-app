"""Atomic staging and reversible review; never writes financial events or balances."""

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import URL
from sqlalchemy.exc import SQLAlchemyError

from trading_db.accounts import AccountTransaction, AccountUnavailable, identifier, page, revision
from trading_db.connections import DatabaseFailure
from trading_db.import_contracts import (
    BatchDefinition,
    CandidateDefinition,
    ObservationDefinition,
    StagedValue,
)
from trading_db.workspace import WorkspaceDatabase, WorkspaceTransaction

MAX_RECORDS = 1000


class ImportUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__("Import operation is unavailable or conflicts with the current revision.")


@dataclass(frozen=True, repr=False)
class Observation:
    id: UUID
    source_id: UUID
    previous_id: UUID | None
    definition: ObservationDefinition


@dataclass(frozen=True, repr=False)
class Batch:
    id: UUID
    observation_id: UUID
    revision: int
    definition: BatchDefinition


@dataclass(frozen=True, repr=False)
class ReviewDecision:
    row_id: UUID
    revision: int
    action: str
    reason: str
    source_id: UUID
    account_mapping_revision: int | None
    instrument_identifier_id: UUID | None
    instrument_mapping_revision: int | None


@dataclass(frozen=True, repr=False)
class StagedRow:
    id: UUID
    batch_id: UUID
    definition: CandidateDefinition
    status: str
    issue: str | None
    decision: ReviewDecision | None


def canonical(definition: BatchDefinition, contract_version: int = 4) -> str:
    if type(contract_version) is not int or contract_version not in (1, 2, 3, 4):
        raise ImportUnavailable()
    value = definition.model_dump(mode="json")
    for row in value["rows"]:
        if contract_version == 1:
            row.pop("posting_state")
        if contract_version < 3:
            row.pop("acquisition_date")
        if contract_version < 4:
            row.pop("as_of_instant")
            row.pop("snapshot_scope")
        row["values"].sort(key=lambda item: item["role"])
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class ImportTransaction:
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
            raise ImportUnavailable() from None

    def _budget(self, table: str, additional: int = 1) -> None:
        if (
            self._execute(f"SELECT count(*) FROM app.{table} WHERE owner_id=:owner").scalar_one()
            + additional
            > MAX_RECORDS
        ):
            raise ImportUnavailable()

    @staticmethod
    def _observation(row: Any) -> Observation:
        return Observation(
            row["id"],
            row["source_id"],
            row["previous_id"],
            ObservationDefinition(
                digest=row["digest"],
                digest_algorithm=row["digest_algorithm"],
                coverage=row["coverage"],
                period_start=row["period_start"].isoformat() if row["period_start"] else None,
                period_end=row["period_end"].isoformat() if row["period_end"] else None,
            ),
        )

    def observation(
        self, source_id: UUID, definition: ObservationDefinition, *, previous_id: UUID | None = None
    ) -> Observation:
        identifier(source_id)
        if previous_id is not None:
            identifier(previous_id)
        valid = ObservationDefinition.model_validate(definition.model_dump(warnings=False))
        with self._write():
            row = (
                self._execute(
                    "SELECT * FROM app.source_observations WHERE owner_id=:owner AND "
                    "source_id=:source AND digest=:digest AND digest_algorithm=:algorithm",
                    source=source_id,
                    digest=valid.digest,
                    algorithm=valid.digest_algorithm,
                )
                .mappings()
                .one_or_none()
            )
            if row:
                result = self._observation(row)
                if result.definition != valid or result.previous_id != previous_id:
                    raise ImportUnavailable()
                return result
            if previous_id is not None:
                previous = self.get_observation(previous_id)
                if (
                    previous is None
                    or previous.source_id != source_id
                    or not self._current_observation(previous_id)
                ):
                    raise ImportUnavailable()
            self._budget("source_observations")
            observation_id = uuid4()
            self._execute(
                "INSERT INTO app.source_observations (owner_id,id,source_id,previous_id,"
                "digest,digest_algorithm,period_start,period_end,coverage) VALUES (:owner,"
                ":id,:source,:previous,:digest,:digest_algorithm,:period_start,:period_end,"
                ":coverage)",
                id=observation_id,
                source=source_id,
                previous=previous_id,
                **valid.model_dump(),
            )
            return Observation(observation_id, source_id, previous_id, valid)

    def get_observation(self, observation_id: UUID) -> Observation | None:
        row = (
            self._execute(
                "SELECT * FROM app.source_observations WHERE owner_id=:owner AND id=:id",
                id=identifier(observation_id),
            )
            .mappings()
            .one_or_none()
        )
        return self._observation(row) if row else None

    def observations(
        self, source_id: UUID, *, limit: int = 25, after: UUID | None = None
    ) -> tuple[Observation, ...]:
        page(limit, after)
        rows = self._execute(
            "SELECT * FROM app.source_observations WHERE owner_id=:owner AND "
            "source_id=:source AND (CAST(:after AS uuid) IS NULL OR id>CAST(:after AS uuid)) "
            "ORDER BY id LIMIT :limit",
            source=identifier(source_id),
            after=after,
            limit=limit,
        ).mappings()
        return tuple(self._observation(row) for row in rows)

    def _current_observation(self, observation_id: UUID) -> bool:
        return not self._execute(
            "SELECT EXISTS(SELECT 1 FROM app.source_observations WHERE owner_id=:owner AND "
            "previous_id=:id)",
            id=observation_id,
        ).scalar_one()

    def _candidate(self, row: Any) -> CandidateDefinition:
        fields = {key: row[key] for key in CandidateDefinition.model_fields if key != "values"}
        for key in (
            "trade_date",
            "settlement_date",
            "booking_date",
            "value_date",
            "as_of_date",
            "acquisition_date",
        ):
            fields[key] = fields[key].isoformat() if fields[key] else None
        values = self._execute(
            "SELECT role,source,currency,missing_reason FROM app.staged_values WHERE "
            "owner_id=:owner AND row_id=:id ORDER BY role",
            id=row["id"],
        ).mappings()
        fields["values"] = tuple(StagedValue.model_validate(dict(value)) for value in values)
        return CandidateDefinition.model_validate(fields)

    def get_batch(self, batch_id: UUID) -> Batch | None:
        row = (
            self._execute(
                "SELECT * FROM app.import_batches WHERE owner_id=:owner AND id=:id",
                id=identifier(batch_id),
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        candidates = self._execute(
            "SELECT * FROM app.staged_rows WHERE owner_id=:owner AND batch_id=:id ORDER BY "
            "occurrence LIMIT 101",
            id=batch_id,
        ).mappings()
        definition = BatchDefinition(
            normalizer=row["normalizer"],
            normalizer_version=row["normalizer_version"],
            rows=tuple(self._candidate(candidate) for candidate in candidates),
        )
        if (
            len(definition.rows) != row["row_count"]
            or hashlib.sha256(canonical(definition, row["contract_version"]).encode()).hexdigest()
            != row["normalized_digest"]
        ):
            raise ImportUnavailable()
        return Batch(row["id"], row["observation_id"], row["revision"], definition)

    def latest_batch(self, observation_id: UUID) -> Batch | None:
        row = self._execute(
            "SELECT id FROM app.import_batches WHERE owner_id=:owner AND observation_id=:id "
            "ORDER BY revision DESC LIMIT 1",
            id=identifier(observation_id),
        ).one_or_none()
        return self.get_batch(row[0]) if row else None

    def stage(
        self, observation_id: UUID, definition: BatchDefinition, *, expected_revision: int
    ) -> Batch:
        identifier(observation_id)
        expected = revision(expected_revision, initial=True)
        valid = BatchDefinition.model_validate(definition.model_dump(warnings=False))
        content = canonical(valid)
        with self._write():
            if self.get_observation(observation_id) is None or not self._current_observation(
                observation_id
            ):
                raise ImportUnavailable()
            current = self.latest_batch(observation_id)
            if (
                current
                and expected in (current.revision, current.revision - 1)
                and canonical(current.definition) == content
            ):
                return current
            if (current.revision if current else 0) != expected:
                raise ImportUnavailable()
            prior = self._execute(
                "SELECT id FROM app.import_batches WHERE owner_id=:owner AND "
                "observation_id=:id AND normalizer=:normalizer AND "
                "normalizer_version=:version ORDER BY revision LIMIT 1",
                id=observation_id,
                normalizer=valid.normalizer,
                version=valid.normalizer_version,
            ).one_or_none()
            if prior:
                prior_batch = self.get_batch(prior[0])
                assert prior_batch is not None
                if canonical(prior_batch.definition) != content:
                    raise ImportUnavailable()
            self._budget("import_batches")
            self._budget("staged_rows", len(valid.rows))
            self._budget("staged_values", sum(len(row.values) for row in valid.rows))
            batch_id = uuid4()
            self._execute(
                "INSERT INTO app.import_batches (owner_id,id,observation_id,revision,"
                "previous_revision,normalizer,normalizer_version,normalized_digest,row_count,"
                "contract_version) VALUES (:owner,:id,:observation,:revision,:previous,"
                ":normalizer,:version,:digest,:count,4)",
                id=batch_id,
                observation=observation_id,
                revision=expected + 1,
                previous=expected or None,
                normalizer=valid.normalizer,
                version=valid.normalizer_version,
                digest=hashlib.sha256(content.encode()).hexdigest(),
                count=len(valid.rows),
            )
            for candidate in valid.rows:
                row_id = uuid4()
                self._execute(
                    "INSERT INTO app.staged_rows (owner_id,id,batch_id,occurrence,kind,"
                    "instrument_identifier_id,trade_date,settlement_date,booking_date,"
                    "value_date,as_of_date,blocked_reason,value_count,posting_state,"
                    "acquisition_date,as_of_instant,snapshot_scope) VALUES "
                    "(:owner,:id,:batch,:occurrence,:kind,"
                    ":instrument_identifier_id,:trade_date,:settlement_date,:booking_date,"
                    ":value_date,:as_of_date,:blocked_reason,:count,:posting_state,"
                    ":acquisition_date,:as_of_instant,:snapshot_scope)",
                    id=row_id,
                    batch=batch_id,
                    count=len(candidate.values),
                    **candidate.model_dump(exclude={"values"}),
                )
                for value in candidate.values:
                    self._execute(
                        "INSERT INTO app.staged_values (owner_id,row_id,role,source,amount,"
                        "currency,missing_reason) VALUES (:owner,:row,:role,:source,:amount,"
                        ":currency,:missing_reason)",
                        row=row_id,
                        amount=value.financial().value,
                        **value.model_dump(),
                    )
            result = self.get_batch(batch_id)
            assert result is not None
            return result

    def history(
        self, row_id: UUID, *, limit: int = 25, before: int | None = None
    ) -> tuple[ReviewDecision, ...]:
        page(limit, None)
        if before is not None:
            revision(before)
        rows = self._execute(
            "SELECT row_id,revision,action,reason,source_id,account_mapping_revision,"
            "instrument_identifier_id,instrument_mapping_revision FROM app.review_decisions "
            "WHERE owner_id=:owner AND row_id=:id AND (CAST(:before AS bigint) IS NULL OR "
            "revision<:before) ORDER BY revision DESC LIMIT :limit",
            id=identifier(row_id),
            before=before,
            limit=limit,
        ).mappings()
        return tuple(ReviewDecision(**row) for row in rows)

    def _context(self, row: Any) -> dict[str, Any]:
        context = dict(
            self._execute(
                "SELECT b.observation_id,b.revision,o.source_id FROM app.import_batches b "
                "JOIN app.source_observations o ON o.owner_id=b.owner_id AND "
                "o.id=b.observation_id WHERE b.owner_id=:owner AND b.id=:batch",
                batch=row["batch_id"],
            )
            .mappings()
            .one()
        )
        current = self._execute(
            "SELECT max(revision) FROM app.import_batches WHERE owner_id=:owner AND "
            "observation_id=:id",
            id=context["observation_id"],
        ).scalar_one()
        context["superseded"] = current != context["revision"] or not self._current_observation(
            context["observation_id"]
        )
        account = self._accounts.mapping(context["source_id"])
        context["account_revision"] = account.revision if account else None
        context["account"] = (
            self._accounts.get(account.account_id) if account and account.account_id else None
        )
        mapping = (
            self._execute(
                "SELECT m.revision,m.instrument_id,i.asset_class,i.fund_currency,"
                "l.quote_currency FROM app.instrument_mappings m LEFT JOIN app.instruments i "
                "ON i.owner_id=m.owner_id AND i.id=m.instrument_id LEFT JOIN "
                "app.instrument_listings l ON l.owner_id=m.owner_id AND l.id=m.listing_id "
                "WHERE m.owner_id=:owner AND m.identifier_id=:id ORDER BY m.revision DESC "
                "LIMIT 1",
                id=row["instrument_identifier_id"],
            )
            .mappings()
            .one_or_none()
        )
        context["instrument_revision"] = mapping["revision"] if mapping else None
        context["instrument"] = mapping["instrument_id"] if mapping else None
        context["asset_class"] = mapping["asset_class"] if mapping else None
        context["fund_currency"] = mapping["fund_currency"] if mapping else None
        context["quote_currency"] = mapping["quote_currency"] if mapping else None
        return context

    def _row(self, raw: Any) -> StagedRow:
        candidate = self._candidate(raw)
        decisions = self.history(raw["id"], limit=1)
        decision = decisions[0] if decisions else None
        context = self._context(raw)
        issue = candidate.issue()
        if context["superseded"]:
            status, issue = "superseded", "revised_evidence"
        elif decision and decision.action == "exclude":
            status, issue = "excluded", None
        else:
            account = context["account"]
            if account is None or account.archived_at is not None:
                issue = issue or "unresolved_account"
            if candidate.instrument_identifier_id and context["instrument"] is None:
                issue = issue or "unresolved_instrument"
            if account is not None:
                if any(
                    value.currency is not None
                    and value.currency not in account.definition.currencies
                    for value in candidate.values
                ):
                    issue = issue or "unsupported_currency"
                if context["instrument"] is not None:
                    asset = context["asset_class"]
                    kind = account.definition.kind
                    if (
                        kind == "bank"
                        or (kind == "mutual_fund" and asset != "mutual_fund")
                        or (kind == "employee_stock" and asset != "equity")
                        or (
                            kind == "brokerage"
                            and account.definition.market == "US"
                            and asset == "mutual_fund"
                        )
                        or candidate.kind == "cash_snapshot"
                        or (
                            context["fund_currency"] is not None
                            and context["fund_currency"] not in account.definition.currencies
                        )
                        or (
                            context["quote_currency"] is not None
                            and context["quote_currency"]
                            != ("INR" if account.definition.market == "IN" else "USD")
                        )
                        or (
                            candidate.kind in ("subscription", "redemption")
                            and asset != "mutual_fund"
                        )
                        or (candidate.kind in ("buy", "sell") and asset not in ("equity", "etf"))
                    ):
                        issue = issue or "incompatible_instrument"
            if (
                decision
                and decision.action == "include"
                and (
                    decision.account_mapping_revision != context["account_revision"]
                    or decision.instrument_mapping_revision != context["instrument_revision"]
                )
            ):
                issue = "stale_mapping"
            status = (
                "blocked"
                if issue
                else "included"
                if decision and decision.action == "include"
                else "reviewable"
            )
        return StagedRow(raw["id"], raw["batch_id"], candidate, status, issue, decision)

    def get_row(self, row_id: UUID) -> StagedRow | None:
        raw = (
            self._execute(
                "SELECT * FROM app.staged_rows WHERE owner_id=:owner AND id=:id",
                id=identifier(row_id),
            )
            .mappings()
            .one_or_none()
        )
        return self._row(raw) if raw else None

    def rows(self, batch_id: UUID, *, limit: int = 25, after: int = 0) -> tuple[StagedRow, ...]:
        page(limit, None)
        if type(after) is not int or not 0 <= after <= 1_000_000:
            raise ImportUnavailable()
        rows = self._execute(
            "SELECT * FROM app.staged_rows WHERE owner_id=:owner AND batch_id=:id AND "
            "occurrence>:after ORDER BY occurrence LIMIT :limit",
            id=identifier(batch_id),
            after=after,
            limit=limit,
        ).mappings()
        return tuple(self._row(row) for row in rows)

    def reviewed(self, row_id: UUID, expected_revision: int) -> tuple[StagedRow, dict[str, Any]]:
        """Read current included evidence while the caller holds the shared write lock."""
        expected = revision(expected_revision)
        raw = (
            self._execute(
                "SELECT * FROM app.staged_rows WHERE owner_id=:owner AND id=:id",
                id=identifier(row_id),
            )
            .mappings()
            .one_or_none()
        )
        if raw is None:
            raise ImportUnavailable()
        source = self._row(raw)
        if self._execute(
            "SELECT EXISTS(SELECT 1 FROM app.financial_events WHERE owner_id=:owner AND "
            "source_row_id=:id) OR EXISTS(SELECT 1 FROM app.lot_observations WHERE "
            "owner_id=:owner AND source_row_id=:id) OR EXISTS(SELECT 1 FROM "
            "app.snapshot_records WHERE owner_id=:owner AND source_row_id=:id)",
            id=row_id,
        ).scalar_one():
            raise ImportUnavailable()
        if (
            source.status != "included"
            or source.decision is None
            or source.decision.revision != expected
        ):
            raise ImportUnavailable()
        self.get_batch(source.batch_id)
        return source, self._context(raw)

    def decide(
        self,
        row_id: UUID,
        action: Literal["include", "exclude", "reopen"],
        *,
        expected_revision: int,
        reason: str | None = None,
    ) -> ReviewDecision:
        identifier(row_id)
        expected = revision(expected_revision, initial=True)
        defaults = {"include": "reviewed", "exclude": "user_excluded", "reopen": "reopened"}
        if type(action) is not str or action not in defaults:
            raise ImportUnavailable()
        reason = defaults[action] if reason is None else reason
        allowed = {
            "include": {"reviewed"},
            "exclude": {"user_excluded", "duplicate_suspected"},
            "reopen": {"reopened"},
        }
        if type(reason) is not str or reason not in allowed[action]:
            raise ImportUnavailable()
        with self._write():
            raw = (
                self._execute(
                    "SELECT * FROM app.staged_rows WHERE owner_id=:owner AND id=:id", id=row_id
                )
                .mappings()
                .one_or_none()
            )
            if raw is None:
                raise ImportUnavailable()
            current = self._row(raw)
            if (
                current.decision.revision if current.decision else 0
            ) != expected or current.status == "superseded":
                raise ImportUnavailable()
            if action == "include" and current.issue not in (None, "stale_mapping"):
                raise ImportUnavailable()
            context = self._context(raw)
            result = ReviewDecision(
                row_id,
                expected + 1,
                action,
                reason,
                context["source_id"],
                context["account_revision"] if action == "include" else None,
                raw["instrument_identifier_id"],
                context["instrument_revision"] if action == "include" else None,
            )
            self._budget("review_decisions")
            self._execute(
                "INSERT INTO app.review_decisions (owner_id,row_id,revision,"
                "previous_revision,action,reason,source_id,account_mapping_revision,"
                "instrument_identifier_id,instrument_mapping_revision) VALUES (:owner,:row,"
                ":revision,:previous,:action,:reason,:source,:account_revision,:reference,"
                ":instrument_revision)",
                row=row_id,
                revision=result.revision,
                previous=expected or None,
                action=action,
                reason=reason,
                source=result.source_id,
                account_revision=result.account_mapping_revision,
                reference=result.instrument_identifier_id,
                instrument_revision=result.instrument_mapping_revision,
            )
            return result


class ImportDatabase:
    def __init__(self, url: URL, project: str) -> None:
        self._workspace = WorkspaceDatabase(url, project)

    def close(self) -> None:
        self._workspace.close()

    @contextmanager
    def transaction(self, owner_id: UUID) -> Iterator[ImportTransaction]:
        try:
            with self._workspace.transaction(owner_id) as unit:
                yield ImportTransaction(unit)
        except SQLAlchemyError, AccountUnavailable:
            raise ImportUnavailable() from None
