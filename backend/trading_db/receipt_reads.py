"""Bounded receipt projections and frozen reconciliation inspection."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from trading_api.read_contracts import FinancialPage
from trading_api.receipt_read_contracts import (
    ComparisonInputView,
    ComparisonSide,
    CompletedRowView,
    InputQuery,
    ReceiptChildrenQuery,
    ReceiptQuery,
    ReceiptView,
    ScopeInspection,
    ScopeView,
)
from trading_api.reconciliation import RULE_VERSION, ReconciliationResult
from trading_api.valuation_read_contracts import InspectQuery
from trading_db.completion_reconciliation import CompletionReconciliation
from trading_db.financial_reads import FinancialReadUnavailable, page_result
from trading_db.import_reads import ImportReadTransaction

RECEIPT_SELECT = (
    "SELECT c.id::text AS id,c.batch_id::text AS batch_id,c.batch_revision,c.mode,c.coverage,"
    "c.created_at,c.row_count,c.selection_count,(SELECT count(*) FROM (SELECT id FROM "
    "app.completion_scopes s WHERE s.owner_id=c.owner_id AND s.receipt_id=c.id LIMIT 101) x) "
    "AS scope_count FROM app.completion_receipts c "
)
SCOPE_FIELDS = (
    "s.id::text AS id,s.receipt_id::text AS receipt_id,s.kind,s.account_id::text AS account_id,"
    "s.position_id::text AS position_id,s.currency,s.period_start::text AS period_start,"
    "s.period_end::text AS period_end,s.date_basis,s.rule_version,s.input_count "
)
SCOPE_SELECT = "SELECT " + SCOPE_FIELDS + "FROM app.completion_scopes s "
INPUT_FIELDS = (
    "i.reference_id::text AS id,i.scope_id::text AS scope_id,i.side,i.part,i.reference_revision,"
    "i.source_row_id::text AS source_row_id,i.event_id::text AS event_id,"
    "i.snapshot_id::text AS snapshot_id,i.source,i.evidence_date::text AS evidence_date,"
    "i.posting_state,s.kind,s.currency "
)


def receipt_rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(row) | {"created_at": row["created_at"].isoformat()} for row in rows]


def comparison_side(result: ReconciliationResult) -> ComparisonSide:
    opening, closing = result.evidence.opening, result.evidence.closing
    if opening is None or closing is None:
        raise FinancialReadUnavailable()
    return ComparisonSide.model_validate(
        dict(
            outcome=result.outcome,
            opening=opening.source,
            closing=closing.source,
            posted_total=result.posted_total,
            calculated_closing=result.calculated_closing,
            difference=result.difference,
            posted_count=result.posted_count,
            pending_count=result.pending_count,
        )
    )


class ReceiptReadTransaction(ImportReadTransaction):
    def _receipt_parent(self, kind: str, identity: str) -> bool:
        table = {
            "receipt": "completion_receipts",
            "scope": "completion_scopes",
            "batch": "import_batches",
        }[kind]
        return bool(
            self._execute(
                f"SELECT EXISTS(SELECT 1 FROM app.{table} WHERE owner_id=:owner AND id=:id)",
                id=UUID(identity),
            ).scalar_one()
        )

    def receipts(self, query: ReceiptQuery) -> FinancialPage[ReceiptView] | None:
        valid = ReceiptQuery.model_validate(query)
        if valid.batch_id is not None and not self._receipt_parent("batch", valid.batch_id):
            return None
        rows = (
            self._execute(
                RECEIPT_SELECT + "WHERE c.owner_id=:owner AND "
                "(CAST(:batch AS uuid) IS NULL OR c.batch_id=CAST(:batch AS uuid)) AND "
                "(CAST(:after AS uuid) IS NULL OR c.id>CAST(:after AS uuid)) "
                "ORDER BY c.id LIMIT :limit",
                batch=UUID(valid.batch_id) if valid.batch_id else None,
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return page_result(
            ReceiptView, FinancialPage[ReceiptView], receipt_rows(list(rows)), valid.limit
        )

    def receipt(self, query: InspectQuery) -> ReceiptView | None:
        valid = InspectQuery.model_validate(query)
        row = (
            self._execute(
                RECEIPT_SELECT + "WHERE c.owner_id=:owner AND c.id=:id", id=UUID(valid.id)
            )
            .mappings()
            .one_or_none()
        )
        return ReceiptView.model_validate(receipt_rows([row])[0]) if row else None

    def receipt_effects(
        self, query: ReceiptChildrenQuery
    ) -> FinancialPage[CompletedRowView] | None:
        valid = ReceiptChildrenQuery.model_validate(query)
        if not self._receipt_parent("receipt", valid.receipt_id):
            return None
        rows = (
            self._execute(
                "SELECT source_row_id::text AS id,receipt_id::text AS receipt_id,review_revision,"
                "operation,outcome,event_id::text AS event_id,"
                "lot_observation_id::text AS lot_observation_id,"
                "snapshot_id::text AS snapshot_id,record_revision,provider_identity_id::text AS "
                "provider_identity_id,selection_id::text AS selection_id,selection_revision "
                "FROM app.completion_rows WHERE owner_id=:owner AND receipt_id=:receipt AND "
                "(CAST(:after AS uuid) IS NULL OR source_row_id>CAST(:after AS uuid)) "
                "ORDER BY source_row_id LIMIT :limit",
                receipt=UUID(valid.receipt_id),
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return page_result(
            CompletedRowView, FinancialPage[CompletedRowView], list(rows), valid.limit
        )

    def receipt_scopes(self, query: ReceiptChildrenQuery) -> FinancialPage[ScopeView] | None:
        valid = ReceiptChildrenQuery.model_validate(query)
        if not self._receipt_parent("receipt", valid.receipt_id):
            return None
        rows = (
            self._execute(
                SCOPE_SELECT + "WHERE s.owner_id=:owner AND s.receipt_id=:receipt AND "
                "(CAST(:after AS uuid) IS NULL OR s.id>CAST(:after AS uuid)) "
                "ORDER BY s.id LIMIT :limit",
                receipt=UUID(valid.receipt_id),
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return page_result(ScopeView, FinancialPage[ScopeView], list(rows), valid.limit)

    def scope_inspection(self, query: InspectQuery) -> ScopeInspection | None:
        valid = InspectQuery.model_validate(query)
        raw = (
            self._execute(
                "SELECT " + SCOPE_FIELDS.rstrip() + ",s.opening_amount,s.closing_amount,"
                "s.source_total,s.combined_total,s.source_posted_count,s.source_pending_count,"
                "s.combined_posted_count,s.combined_pending_count FROM app.completion_scopes s "
                "WHERE s.owner_id=:owner AND s.id=:id",
                id=UUID(valid.id),
            )
            .mappings()
            .one_or_none()
        )
        if raw is None:
            return None
        scope = ScopeView.model_validate({field: raw[field] for field in ScopeView.model_fields})
        if scope.rule_version != RULE_VERSION:
            raise FinancialReadUnavailable()
        inputs = (
            self._execute(
                "SELECT side,part,reference_id,reference_revision,source,"
                "evidence_date,posting_state "
                "FROM app.completion_inputs WHERE owner_id=:owner AND scope_id=:id "
                "ORDER BY side,part,reference_id LIMIT 1001",
                id=UUID(valid.id),
            )
            .mappings()
            .all()
        )
        if len(inputs) != scope.input_count or len(inputs) > 1000:
            raise FinancialReadUnavailable()
        native = dict(raw) | dict(
            account_id=UUID(scope.account_id),
            position_id=UUID(scope.position_id) if scope.position_id else None,
        )
        # The domain reconstruction uses database dates and native UUIDs.
        native["period_start"] = date.fromisoformat(scope.period_start)
        native["period_end"] = date.fromisoformat(scope.period_end)
        pair = CompletionReconciliation._pair(native, list(inputs))
        left, right = comparison_side(pair.source), comparison_side(pair.combined)
        if any(
            Decimal(value) != raw[column]
            for column, value in (
                ("opening_amount", left.opening),
                ("closing_amount", left.closing),
                ("source_total", left.posted_total),
                ("combined_total", right.posted_total),
            )
        ) or any(
            raw[column] != value
            for column, value in (
                ("source_posted_count", left.posted_count),
                ("source_pending_count", left.pending_count),
                ("combined_posted_count", right.posted_count),
                ("combined_pending_count", right.pending_count),
            )
        ):
            raise FinancialReadUnavailable()
        return ScopeInspection(scope=scope, source=left, combined=right)

    def comparison_inputs(self, query: InputQuery) -> FinancialPage[ComparisonInputView] | None:
        valid = InputQuery.model_validate(query)
        if not self._receipt_parent("scope", valid.scope_id):
            return None
        rows = (
            self._execute(
                "SELECT "
                + INPUT_FIELDS
                + "FROM app.completion_inputs i JOIN app.completion_scopes s "
                "ON s.owner_id=i.owner_id AND s.id=i.scope_id WHERE i.owner_id=:owner AND "
                "i.scope_id=:scope AND i.side=:side AND i.part=:part AND "
                "(CAST(:after AS uuid) IS NULL OR i.reference_id>CAST(:after AS uuid)) "
                "ORDER BY i.reference_id LIMIT :limit",
                scope=UUID(valid.scope_id),
                side=valid.side,
                part=valid.part,
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return page_result(
            ComparisonInputView, FinancialPage[ComparisonInputView], list(rows), valid.limit
        )
