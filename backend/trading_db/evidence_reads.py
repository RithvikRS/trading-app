"""Finite current/history projections; supplied evidence never implies a portfolio total."""

from typing import Any
from uuid import UUID

from trading_api.evidence_read_contracts import (
    EventQuery,
    EventView,
    FinancialComponent,
    HistoryPage,
    HistoryQuery,
    LotObservationQuery,
    LotObservationView,
    LotQuery,
    LotView,
    RevisionView,
)
from trading_api.read_contracts import FinancialPage
from trading_db.financial_reads import (
    FinancialReadTransaction,
    FinancialReadUnavailable,
    page_result,
)

# Only committed table/field pairs participate; request values remain SQL parameters.
PARENTS = {
    "account": "financial_accounts",
    "position": "account_positions",
    "lot": "lots",
    "event": "financial_events",
    "lot_observation": "lot_observations",
}
PROVENANCE = (
    "e.source_row_id::text AS source_row_id,e.source_review_revision,"
    "o.source_id::text AS source_id,o.id::text AS observation_id,b.id::text AS batch_id,"
    "o.coverage,o.period_start::text AS period_start,o.period_end::text AS period_end,"
    "b.cash_date_basis,CASE WHEN a.archived_at IS NULL THEN 'active' "
    "ELSE 'archived' END AS account_state"
)
SOURCE_JOINS = (
    "JOIN app.staged_rows r ON r.owner_id=e.owner_id AND r.id=e.source_row_id "
    "JOIN app.import_batches b ON b.owner_id=r.owner_id AND b.id=r.batch_id "
    "JOIN app.source_observations o ON o.owner_id=b.owner_id AND o.id=b.observation_id "
)
EVENT_FIELDS = (
    "e.id::text AS id,e.revision,e.account_id::text AS account_id,"
    "e.position_id::text AS position_id,e.instrument_id::text AS instrument_id,"
    "e.status,e.correction_reason,e.kind,e.posting_state,e.trade_date::text AS trade_date,"
    "e.settlement_date::text AS settlement_date,e.booking_date::text AS booking_date,"
    "e.value_date::text AS value_date,"
    "NOT EXISTS(SELECT 1 FROM app.financial_events n WHERE n.owner_id=e.owner_id "
    "AND n.id=e.id AND n.revision>e.revision) AS is_current,"
)
LOT_FIELDS = (
    "e.id::text AS id,e.revision,e.lot_id::text AS lot_id,p.id::text AS position_id,"
    "p.account_id::text AS account_id,p.instrument_id::text AS instrument_id,"
    "e.scope,e.status,e.correction_reason,e.as_of_date::text AS as_of_date,"
    "e.acquisition_date::text AS acquisition_date,e.booking_date::text AS booking_date,"
    "NOT EXISTS(SELECT 1 FROM app.lot_observations n WHERE n.owner_id=e.owner_id "
    "AND n.id=e.id AND n.revision>e.revision) AS is_current,"
)


def components(table: str, reference: str) -> str:
    if (table, reference) not in {
        ("event_components", "event_id"),
        ("lot_components", "observation_id"),
    }:
        raise ValueError("Unsupported financial projection.")
    return (
        ",COALESCE((SELECT jsonb_agg(jsonb_build_object('role',c.role,'source',c.source,"
        "'currency',c.currency,'missing_reason',c.missing_reason) ORDER BY c.role) FROM "
        f"(SELECT role,source,currency,missing_reason FROM app.{table} "
        f"WHERE owner_id=e.owner_id AND {reference}=e.id AND revision=e.revision "
        "ORDER BY role LIMIT 9) c),'[]'::jsonb) AS components "
    )


EVENT_SELECT = (
    "SELECT "
    + EVENT_FIELDS
    + PROVENANCE
    + components("event_components", "event_id")
    + (
        "FROM app.financial_events e JOIN app.financial_accounts a "
        "ON a.owner_id=e.owner_id AND a.id=e.account_id "
    )
    + SOURCE_JOINS
)
LOT_SELECT = (
    "SELECT "
    + LOT_FIELDS
    + PROVENANCE
    + components("lot_components", "observation_id")
    + (
        "FROM app.lot_observations e JOIN app.lots l ON l.owner_id=e.owner_id AND l.id=e.lot_id "
        "JOIN app.account_positions p ON p.owner_id=l.owner_id AND p.id=l.position_id "
        "JOIN app.financial_accounts a ON a.owner_id=p.owner_id AND a.id=p.account_id "
    )
    + SOURCE_JOINS
)


def evidence_rows(rows: list[Any]) -> list[Any]:
    return [
        dict(row)
        | {
            "components": tuple(
                FinancialComponent.model_validate(item) for item in row["components"]
            )
        }
        for row in rows
    ]


def history_result[T: RevisionView](
    model: type[T], response: type[HistoryPage[T]], rows: list[Any], limit: int
) -> HistoryPage[T]:
    if len(rows) > limit + 1:
        raise FinancialReadUnavailable()
    items = tuple(model.model_validate(row) for row in evidence_rows(rows[:limit]))
    return response(items=items, next_before=items[-1].revision if len(rows) > limit else None)


class EvidenceReadTransaction(FinancialReadTransaction):
    def _owned(self, kind: str, identity: str) -> bool:
        table = PARENTS[kind]
        return bool(
            self._execute(
                f"SELECT EXISTS(SELECT 1 FROM app.{table} WHERE owner_id=:owner AND id=:id)",
                id=UUID(identity),
            ).scalar_one()
        )

    def events(self, query: EventQuery) -> FinancialPage[EventView] | None:
        valid = EventQuery.model_validate(query)
        if not self._owned("account", valid.account_id):
            return None
        rows = (
            self._execute(
                EVENT_SELECT + "WHERE e.owner_id=:owner AND e.account_id=:account AND "
                "(CAST(:after AS uuid) IS NULL OR e.id>CAST(:after AS uuid)) AND NOT EXISTS "
                "(SELECT 1 FROM app.financial_events n WHERE n.owner_id=e.owner_id AND n.id=e.id "
                "AND n.revision>e.revision) ORDER BY e.id LIMIT :limit",
                account=UUID(valid.account_id),
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return page_result(
            EventView, FinancialPage[EventView], evidence_rows(list(rows)), valid.limit
        )

    def event_history(self, query: HistoryQuery) -> HistoryPage[EventView] | None:
        valid = HistoryQuery.model_validate(query)
        if not self._owned("event", valid.id):
            return None
        rows = (
            self._execute(
                EVENT_SELECT + "WHERE e.owner_id=:owner AND e.id=:id AND "
                "(CAST(:before AS bigint) IS NULL OR e.revision<:before) "
                "ORDER BY e.revision DESC LIMIT :limit",
                id=UUID(valid.id),
                before=valid.before,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return history_result(EventView, HistoryPage[EventView], list(rows), valid.limit)

    def lots(self, query: LotQuery) -> FinancialPage[LotView] | None:
        valid = LotQuery.model_validate(query)
        if not self._owned("position", valid.position_id):
            return None
        rows = (
            self._execute(
                "SELECT l.id::text AS id,l.position_id::text AS position_id,"
                "p.account_id::text AS account_id,p.instrument_id::text AS instrument_id,"
                "CASE WHEN a.archived_at IS NULL THEN 'active' "
                "ELSE 'archived' END AS account_state "
                "FROM app.lots l JOIN app.account_positions p ON p.owner_id=l.owner_id "
                "AND p.id=l.position_id JOIN app.financial_accounts a ON a.owner_id=p.owner_id "
                "AND a.id=p.account_id WHERE l.owner_id=:owner AND l.position_id=:position AND "
                "(CAST(:after AS uuid) IS NULL OR l.id>CAST(:after AS uuid)) "
                "ORDER BY l.id LIMIT :limit",
                position=UUID(valid.position_id),
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return page_result(LotView, FinancialPage[LotView], list(rows), valid.limit)

    def lot_observations(
        self, query: LotObservationQuery
    ) -> FinancialPage[LotObservationView] | None:
        valid = LotObservationQuery.model_validate(query)
        if not self._owned("lot", valid.lot_id):
            return None
        rows = (
            self._execute(
                LOT_SELECT + "WHERE e.owner_id=:owner AND e.lot_id=:lot AND "
                "(CAST(:after AS uuid) IS NULL OR e.id>CAST(:after AS uuid)) AND NOT EXISTS "
                "(SELECT 1 FROM app.lot_observations n WHERE n.owner_id=e.owner_id AND n.id=e.id "
                "AND n.revision>e.revision) ORDER BY e.id LIMIT :limit",
                lot=UUID(valid.lot_id),
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return page_result(
            LotObservationView,
            FinancialPage[LotObservationView],
            evidence_rows(list(rows)),
            valid.limit,
        )

    def lot_history(self, query: HistoryQuery) -> HistoryPage[LotObservationView] | None:
        valid = HistoryQuery.model_validate(query)
        if not self._owned("lot_observation", valid.id):
            return None
        rows = (
            self._execute(
                LOT_SELECT + "WHERE e.owner_id=:owner AND e.id=:id AND "
                "(CAST(:before AS bigint) IS NULL OR e.revision<:before) "
                "ORDER BY e.revision DESC LIMIT :limit",
                id=UUID(valid.id),
                before=valid.before,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return history_result(
            LotObservationView, HistoryPage[LotObservationView], list(rows), valid.limit
        )
