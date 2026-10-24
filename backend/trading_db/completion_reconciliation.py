"""Exact scoped comparisons bound to immutable receipt inputs."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from trading_api.reconciliation import (
    RULE_VERSION,
    LedgerEvidence,
    ReconciliationActivity,
    ReconciliationCheckpoint,
    ReconciliationPair,
    ReconciliationPeriod,
    ReconciliationScope,
    reconcile_pair,
)
from trading_db.accounts import AccountTransaction
from trading_db.completion_baseline import CompletionUnavailable
from trading_db.snapshots import SnapshotTransaction
from trading_db.workspace import WorkspaceTransaction


@dataclass(frozen=True, repr=False)
class CompletedScope:
    id: UUID
    comparison: ReconciliationPair


class CompletionReconciliation:
    def __init__(self, unit: WorkspaceTransaction) -> None:
        self._accounts = AccountTransaction(unit, None)
        self._snapshots = SnapshotTransaction(unit)

    def _execute(self, sql: str, **parameters: Any) -> Any:
        return self._accounts._execute(sql, **parameters)

    @staticmethod
    def _pair(scope: Any, inputs: list[Any]) -> ReconciliationPair:
        native = ReconciliationScope.model_validate(
            {key: scope[key] for key in ("kind", "account_id", "position_id", "currency")}
        )
        period = ReconciliationPeriod.model_validate(
            {
                "start": scope["period_start"].isoformat(),
                "end": scope["period_end"].isoformat(),
                "date_basis": scope["date_basis"],
            }
        )
        sides = []
        for side in ("source", "combined"):
            checkpoints = {}
            activities = []
            for item in inputs:
                if item["side"] != side:
                    continue
                common = {
                    "scope": native,
                    "reference": item["reference_id"],
                    "revision": item["reference_revision"],
                    "source": item["source"],
                    "date": item["evidence_date"].isoformat() if item["evidence_date"] else None,
                }
                if item["part"] == "activity":
                    activities.append(
                        ReconciliationActivity.model_validate(
                            common | {"posting_state": item["posting_state"]}
                        )
                    )
                else:
                    if item["part"] not in ("opening", "closing") or item["part"] in checkpoints:
                        raise CompletionUnavailable()
                    checkpoints[item["part"]] = ReconciliationCheckpoint.model_validate(
                        common
                        | {
                            "boundary": "before_period"
                            if item["part"] == "opening"
                            else "after_period"
                        }
                    )
            sides.append(
                LedgerEvidence.model_validate(
                    {
                        "side": side,
                        "scope": native,
                        "period": period,
                        "coverage": "complete_activity",
                        "opening": checkpoints.get("opening"),
                        "closing": checkpoints.get("closing"),
                        "activities": tuple(sorted(activities, key=lambda item: item.reference)),
                        # Only the explicit source period is anchored by its checkpoints.
                        "baseline_verified": side == "combined",
                    }
                )
            )
        result = reconcile_pair(*sides)
        if not result.balanced:
            raise CompletionUnavailable()
        return result

    def list(self, receipt_id: UUID) -> tuple[CompletedScope, ...]:
        roots = (
            self._execute(
                "SELECT * FROM app.completion_scopes WHERE owner_id=:owner AND receipt_id=:id "
                "ORDER BY id LIMIT 101",
                id=receipt_id,
            )
            .mappings()
            .all()
        )
        if len(roots) > 100:
            raise CompletionUnavailable()
        result = []
        for root in roots:
            if root["rule_version"] != RULE_VERSION:
                raise CompletionUnavailable()
            inputs = (
                self._execute(
                    "SELECT * FROM app.completion_inputs WHERE owner_id=:owner AND scope_id=:id "
                    "ORDER BY side,part,reference_id LIMIT 1001",
                    id=root["id"],
                )
                .mappings()
                .all()
            )
            if len(inputs) != root["input_count"] or len(inputs) > 1000:
                raise CompletionUnavailable()
            result.append(CompletedScope(root["id"], self._pair(root, list(inputs))))
        return tuple(result)

    def persist(self, receipt_id: UUID) -> None:
        header = (
            self._execute(
                "SELECT b.cash_date_basis,o.period_start,o.period_end "
                "FROM app.completion_receipts c "
                "JOIN app.import_batches b ON b.owner_id=c.owner_id AND b.id=c.batch_id JOIN "
                "app.source_observations o ON o.owner_id=b.owner_id AND o.id=b.observation_id "
                "WHERE c.owner_id=:owner AND c.id=:id AND c.mode='reconciled'",
                id=receipt_id,
            )
            .mappings()
            .one()
        )
        source = (
            self._execute(
                "SELECT * FROM app.reconciliation_source_inputs(:owner,:id) "
                "ORDER BY kind,account_id,position_id,currency,side,part,reference_id LIMIT 401",
                id=receipt_id,
            )
            .mappings()
            .all()
        )
        if not source or len(source) > 400:
            raise CompletionUnavailable()
        grouped: dict[tuple[Any, ...], list[Any]] = {}
        fields = ("kind", "account_id", "position_id", "currency")
        for item in source:
            grouped.setdefault(tuple(item[key] for key in fields), []).append(dict(item))
        if len(grouped) > 100:
            raise CompletionUnavailable()
        for key, inputs in grouped.items():
            scope = dict(zip(fields, key, strict=True)) | {
                "period_start": header["period_start"],
                "period_end": header["period_end"],
                "date_basis": header["cash_date_basis"] if key[0] == "cash" else "trade",
            }
            current = (
                self._execute(
                    "SELECT * FROM app.reconciliation_current_activity(:owner,:account_id,"
                    ":position_id,:currency,:period_start,:period_end,:date_basis) "
                    "ORDER BY reference_id LIMIT 1001",
                    **scope,
                )
                .mappings()
                .all()
            )
            if len(current) > 1000 or len(current) + len(inputs) > 1000:
                raise CompletionUnavailable()
            inputs.extend(
                dict(item)
                | {
                    "side": "combined",
                    "part": "activity",
                    "source_row_id": None,
                    "event_id": item["reference_id"],
                    "snapshot_id": None,
                }
                for item in current
            )
            # Current checkpoint usability is independently checked again by SQL at commit.
            for item in inputs:
                if item["side"] == "combined" and item["snapshot_id"] is not None:
                    snapshot = self._snapshots.get(item["snapshot_id"])
                    if (
                        snapshot is None
                        or snapshot.revision != item["reference_revision"]
                        or (self._snapshots._state(snapshot) != "selected")
                    ):
                        raise CompletionUnavailable()
            pair = self._pair(scope, inputs)
            scope_id = uuid4()
            opening, closing = (
                pair.source.evidence.opening,
                pair.source.evidence.closing,
            )
            assert opening is not None and closing is not None
            assert pair.source.posted_total is not None and pair.combined.posted_total is not None
            self._execute(
                "INSERT INTO app.completion_scopes (owner_id,id,receipt_id,kind,account_id,"
                "position_id,currency,period_start,period_end,date_basis,rule_version,"
                "opening_amount,closing_amount,source_total,combined_total,source_posted_count,"
                "source_pending_count,combined_posted_count,combined_pending_count,input_count) "
                "VALUES (:owner,:id,:receipt,:kind,:account_id,:position_id,:currency,"
                ":period_start,:period_end,:date_basis,:rule_version,:opening,:closing,:source_total,"
                ":combined_total,:source_posted,:source_pending,:combined_posted,"
                ":combined_pending,:input_count)",
                **scope,
                id=scope_id,
                receipt=receipt_id,
                rule_version=RULE_VERSION,
                opening=opening.financial().value,
                closing=closing.financial().value,
                source_total=Decimal(pair.source.posted_total),
                combined_total=Decimal(pair.combined.posted_total),
                source_posted=pair.source.posted_count,
                source_pending=pair.source.pending_count,
                combined_posted=pair.combined.posted_count,
                combined_pending=pair.combined.pending_count,
                input_count=len(inputs),
            )
            for item in inputs:
                self._execute(
                    "INSERT INTO app.completion_inputs (owner_id,scope_id,side,part,reference_id,"
                    "reference_revision,source_row_id,event_id,snapshot_id,source,amount,"
                    "evidence_date,posting_state) VALUES (:owner,:scope,:side,:part,:reference_id,"
                    ":reference_revision,:source_row_id,:event_id,:snapshot_id,:source,:amount,"
                    ":evidence_date,:posting_state)",
                    scope=scope_id,
                    **{
                        field: item[field]
                        for field in (
                            "side",
                            "part",
                            "reference_id",
                            "reference_revision",
                            "source_row_id",
                            "event_id",
                            "snapshot_id",
                            "source",
                            "amount",
                            "evidence_date",
                            "posting_state",
                        )
                    },
                )
            self._execute("SELECT app.validate_completion_scope(:owner,:id)", id=scope_id)
