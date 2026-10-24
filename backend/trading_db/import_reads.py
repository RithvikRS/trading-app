"""Bounded source/review projections reuse the domain's effective review rules."""

from typing import Any
from uuid import UUID

from trading_api.evidence_read_contracts import HistoryPage, HistoryQuery
from trading_api.import_read_contracts import (
    BatchQuery,
    BatchView,
    ImportRowView,
    ObservationQuery,
    ReviewView,
    RowPage,
    RowQuery,
    SourceObservationView,
)
from trading_api.read_contracts import FinancialPage
from trading_api.valuation_read_contracts import InspectQuery
from trading_db.financial_reads import FinancialReadUnavailable, page_result
from trading_db.imports import ImportTransaction, ReviewDecision
from trading_db.valuation_reads import ValuationReadTransaction, revision_page

OBSERVATION_SELECT = (
    "SELECT o.id::text AS id,o.source_id::text AS source_id,o.previous_id::text AS previous_id,"
    "o.coverage,o.period_start::text AS period_start,o.period_end::text AS period_end,"
    "NOT EXISTS(SELECT 1 FROM app.source_observations n WHERE n.owner_id=o.owner_id "
    "AND n.previous_id=o.id) AS is_current FROM app.source_observations o "
)
BATCH_SELECT = (
    "SELECT b.id::text AS id,b.observation_id::text AS observation_id,b.revision,"
    "o.source_id::text AS source_id,b.normalizer,b.normalizer_version,b.contract_version,"
    "b.row_count,b.cash_date_basis,NOT EXISTS(SELECT 1 FROM app.import_batches n "
    "WHERE n.owner_id=b.owner_id AND n.observation_id=b.observation_id "
    "AND n.revision>b.revision) AS is_current,NOT EXISTS(SELECT 1 FROM app.source_observations n "
    "WHERE n.owner_id=o.owner_id AND n.previous_id=o.id) AS source_current "
    "FROM app.import_batches b JOIN app.source_observations o "
    "ON o.owner_id=b.owner_id AND o.id=b.observation_id "
)
REVIEW_SELECT = (
    "SELECT d.row_id::text AS id,d.revision,d.action,d.reason,d.source_id::text AS source_id,"
    "d.account_mapping_revision,d.instrument_identifier_id::text AS instrument_identifier_id,"
    "d.instrument_mapping_revision,NOT EXISTS(SELECT 1 FROM app.review_decisions n "
    "WHERE n.owner_id=d.owner_id AND n.row_id=d.row_id AND n.revision>d.revision) AS is_current "
    "FROM app.review_decisions d "
)
ROW_SELECT = (
    "SELECT r.id,r.batch_id,r.occurrence,d.revision AS decision_revision,d.action,d.reason,"
    "d.source_id,d.account_mapping_revision,d.instrument_identifier_id,"
    "d.instrument_mapping_revision,m.revision AS current_instrument_revision,"
    "m.instrument_id,i.asset_class,i.fund_currency,l.quote_currency "
    "FROM app.staged_rows r LEFT JOIN LATERAL (SELECT revision,action,reason,source_id,"
    "account_mapping_revision,instrument_identifier_id,instrument_mapping_revision "
    "FROM app.review_decisions WHERE owner_id=r.owner_id AND row_id=r.id "
    "ORDER BY revision DESC LIMIT 1) d ON true LEFT JOIN LATERAL ("
    "SELECT revision,instrument_id,listing_id FROM app.instrument_mappings "
    "WHERE owner_id=r.owner_id AND identifier_id=r.instrument_identifier_id "
    "ORDER BY revision DESC LIMIT 1) m ON true LEFT JOIN app.instruments i "
    "ON i.owner_id=r.owner_id AND i.id=m.instrument_id LEFT JOIN app.instrument_listings l "
    "ON l.owner_id=r.owner_id AND l.id=m.listing_id "
)
CANDIDATE_FIELDS = {
    "occurrence",
    "kind",
    "posting_state",
    "instrument_identifier_id",
    "trade_date",
    "settlement_date",
    "booking_date",
    "value_date",
    "as_of_date",
    "acquisition_date",
    "as_of_instant",
    "snapshot_scope",
    "reconciliation_boundary",
    "blocked_reason",
}


def review_view(decision: ReviewDecision) -> ReviewView:
    return ReviewView.model_validate(
        dict(
            id=str(decision.row_id),
            revision=decision.revision,
            is_current=True,
            action=decision.action,
            reason=decision.reason,
            source_id=str(decision.source_id),
            account_mapping_revision=decision.account_mapping_revision,
            instrument_identifier_id=str(decision.instrument_identifier_id)
            if decision.instrument_identifier_id
            else None,
            instrument_mapping_revision=decision.instrument_mapping_revision,
        )
    )


class ImportReadTransaction(ValuationReadTransaction):
    def _import_parent(self, kind: str, identity: str) -> bool:
        table = {
            "source": "source_accounts",
            "observation": "source_observations",
            "row": "staged_rows",
        }[kind]
        return bool(
            self._execute(
                f"SELECT EXISTS(SELECT 1 FROM app.{table} WHERE owner_id=:owner AND id=:id)",
                id=UUID(identity),
            ).scalar_one()
        )

    def source_observations(
        self, query: ObservationQuery
    ) -> FinancialPage[SourceObservationView] | None:
        valid = ObservationQuery.model_validate(query)
        if not self._import_parent("source", valid.source_id):
            return None
        rows = (
            self._execute(
                OBSERVATION_SELECT + "WHERE o.owner_id=:owner AND o.source_id=:source AND "
                "(CAST(:after AS uuid) IS NULL OR o.id>CAST(:after AS uuid)) "
                "ORDER BY o.id LIMIT :limit",
                source=UUID(valid.source_id),
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return page_result(
            SourceObservationView, FinancialPage[SourceObservationView], list(rows), valid.limit
        )

    def import_batches(self, query: BatchQuery) -> HistoryPage[BatchView] | None:
        valid = BatchQuery.model_validate(query)
        if not self._import_parent("observation", valid.observation_id):
            return None
        rows = (
            self._execute(
                BATCH_SELECT + "WHERE b.owner_id=:owner AND b.observation_id=:observation AND "
                "(CAST(:before AS bigint) IS NULL OR b.revision<:before) "
                "ORDER BY b.revision DESC LIMIT :limit",
                observation=UUID(valid.observation_id),
                before=valid.before,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return revision_page(BatchView, HistoryPage[BatchView], list(rows), valid.limit)

    def review_history(self, query: HistoryQuery) -> HistoryPage[ReviewView] | None:
        valid = HistoryQuery.model_validate(query)
        if not self._import_parent("row", valid.id):
            return None
        rows = (
            self._execute(
                REVIEW_SELECT + "WHERE d.owner_id=:owner AND d.row_id=:id AND "
                "(CAST(:before AS bigint) IS NULL OR d.revision<:before) "
                "ORDER BY d.revision DESC LIMIT :limit",
                id=UUID(valid.id),
                before=valid.before,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return revision_page(ReviewView, HistoryPage[ReviewView], list(rows), valid.limit)

    def _materialize(
        self,
        batch_id: str,
        *,
        limit: int,
        after: int | None = None,
        exact: UUID | None = None,
    ) -> list[ImportRowView] | None:
        metadata = (
            self._execute(
                BATCH_SELECT + "WHERE b.owner_id=:owner AND b.id=:id",
                id=UUID(batch_id),
            )
            .mappings()
            .one_or_none()
        )
        if metadata is None:
            return None
        meta = BatchView.model_validate(dict(metadata))
        imports = ImportTransaction(self._accounts._unit)
        batch = imports.get_batch(UUID(batch_id))
        if batch is None:
            raise FinancialReadUnavailable()
        definitions = {row.occurrence: row for row in batch.definition.rows}
        mapping = self._accounts.mapping(UUID(meta.source_id))
        account = self._accounts.get(mapping.account_id) if mapping and mapping.account_id else None
        rows = (
            self._execute(
                ROW_SELECT + "WHERE r.owner_id=:owner AND r.batch_id=:batch "
                "AND (CAST(:exact AS uuid) IS NULL OR r.id=CAST(:exact AS uuid)) "
                "AND r.occurrence>:after ORDER BY r.occurrence LIMIT :limit",
                batch=UUID(batch_id),
                exact=exact,
                after=after or 0,
                limit=limit,
            )
            .mappings()
            .all()
        )
        if len(rows) > limit:
            raise FinancialReadUnavailable()
        result = []
        for row in rows:
            candidate = definitions.get(row["occurrence"])
            if candidate is None:
                raise FinancialReadUnavailable()
            decision = (
                None
                if row["decision_revision"] is None
                else ReviewDecision(
                    row["id"],
                    row["decision_revision"],
                    row["action"],
                    row["reason"],
                    row["source_id"],
                    row["account_mapping_revision"],
                    row["instrument_identifier_id"],
                    row["instrument_mapping_revision"],
                )
            )
            context: dict[str, Any] = dict(
                superseded=not (meta.is_current and meta.source_current),
                account_revision=mapping.revision if mapping else None,
                account=account,
                instrument_revision=row["current_instrument_revision"],
                instrument=row["instrument_id"],
                asset_class=row["asset_class"],
                fund_currency=row["fund_currency"],
                quote_currency=row["quote_currency"],
            )
            effective = imports._row_from_parts(row, candidate, decision, context)
            fields = candidate.model_dump(include=CANDIDATE_FIELDS)
            fields["instrument_identifier_id"] = (
                str(candidate.instrument_identifier_id)
                if candidate.instrument_identifier_id
                else None
            )
            fields.update(
                id=str(row["id"]),
                batch_id=batch_id,
                components=tuple(value.model_dump() for value in candidate.values),
                status=effective.status,
                issue=effective.issue,
                decision=review_view(decision) if decision is not None else None,
            )
            result.append(ImportRowView.model_validate(fields))
        return result

    def import_rows(self, query: RowQuery) -> RowPage | None:
        valid = RowQuery.model_validate(query)
        rows = self._materialize(
            valid.batch_id, after=valid.after_occurrence, limit=valid.limit + 1
        )
        if rows is None:
            return None
        items = tuple(rows[: valid.limit])
        return RowPage(
            items=items,
            next_after_occurrence=items[-1].occurrence if len(rows) > valid.limit else None,
        )

    def import_row(self, query: InspectQuery) -> ImportRowView | None:
        valid = InspectQuery.model_validate(query)
        parent = self._execute(
            "SELECT batch_id::text FROM app.staged_rows WHERE owner_id=:owner AND id=:id",
            id=UUID(valid.id),
        ).scalar_one_or_none()
        if parent is None:
            return None
        rows = self._materialize(parent, exact=UUID(valid.id), limit=1)
        if not rows or len(rows) != 1:
            raise FinancialReadUnavailable()
        return rows[0]
