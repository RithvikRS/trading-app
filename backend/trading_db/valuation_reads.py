"""Explicit snapshot/market projections with existing selection validity rules."""

from typing import Any
from uuid import UUID

from trading_api.evidence_read_contracts import HistoryPage, HistoryQuery, RevisionView
from trading_api.read_contracts import FinancialPage
from trading_api.valuation_read_contracts import (
    InspectQuery,
    ListingQuery,
    ListingView,
    MarketObservationView,
    MarketQuery,
    MarketResolution,
    MarketSelectionView,
    SnapshotQuery,
    SnapshotResolution,
    SnapshotSelectionView,
    SnapshotView,
)
from trading_db.evidence_reads import (
    PROVENANCE,
    SOURCE_JOINS,
    EvidenceReadTransaction,
    evidence_rows,
)
from trading_db.financial_reads import FinancialReadUnavailable, page_result
from trading_db.markets import MarketTransaction
from trading_db.snapshots import SnapshotTransaction

SNAPSHOT_SELECT = (
    "SELECT e.id::text AS id,e.revision,e.account_id::text AS account_id,"
    "e.position_id::text AS position_id,e.instrument_id::text AS instrument_id,"
    "e.currency,e.kind,e.status,e.correction_reason,e.as_of_date::text AS as_of_date,"
    "e.as_of_instant,e.snapshot_scope,r.reconciliation_boundary,"
    "e.booking_date::text AS booking_date,NOT EXISTS(SELECT 1 FROM app.snapshot_records n "
    "WHERE n.owner_id=e.owner_id AND n.id=e.id AND n.revision>e.revision) AS is_current,"
    + PROVENANCE
    + ",COALESCE((SELECT jsonb_agg(jsonb_build_object("
    "'role',c.role,'source',c.source,'currency',c.currency,'missing_reason',c.missing_reason) "
    "ORDER BY c.role) FROM (SELECT role,source,currency,missing_reason "
    "FROM app.snapshot_components WHERE owner_id=e.owner_id AND snapshot_id=e.id "
    "AND revision=e.revision ORDER BY role LIMIT 9) c),'[]'::jsonb) AS components "
    "FROM app.snapshot_records e JOIN app.financial_accounts a "
    "ON a.owner_id=e.owner_id AND a.id=e.account_id " + SOURCE_JOINS
)
SNAPSHOT_SELECTION = (
    "SELECT e.id::text AS id,e.revision,e.account_id::text AS account_id,"
    "e.position_id::text AS position_id,e.currency,e.snapshot_id::text AS snapshot_id,"
    "e.snapshot_revision,e.reason,NOT EXISTS(SELECT 1 FROM app.snapshot_selections n "
    "WHERE n.owner_id=e.owner_id AND n.id=e.id AND n.revision>e.revision) AS is_current "
    "FROM app.snapshot_selections e "
)
MARKET_TARGET = (
    "e.kind,e.instrument_id::text AS instrument_id,e.listing_id::text AS listing_id,"
    "e.currency,e.base_currency,e.quote_currency,e.basis,"
)
MARKET_SELECT = (
    "SELECT e.id::text AS id," + MARKET_TARGET + "e.previous_id::text AS previous_id,"
    "e.adjustment,e.namespace,e.observed_on::text AS observed_on,e.observed_at,"
    "e.source,e.missing_reason,NOT EXISTS(SELECT 1 FROM app.market_observations n "
    "WHERE n.owner_id=e.owner_id AND n.previous_id=e.id) AS is_current,"
    "(e.amount IS NOT NULL AND e.amount>0 AND "
    "(e.kind<>'quote' OR e.adjustment='unadjusted')) AS usable "
    "FROM app.market_observations e "
)
MARKET_SELECTION = (
    "SELECT e.id::text AS id,e.revision,"
    + MARKET_TARGET
    + "e.observation_id::text AS observation_id,e.reason,NOT EXISTS(SELECT 1 "
    "FROM app.market_selections n WHERE n.owner_id=e.owner_id AND n.id=e.id "
    "AND n.revision>e.revision) AS is_current FROM app.market_selections e "
)
NEXT = "AND (CAST(:after AS uuid) IS NULL OR e.id>CAST(:after AS uuid)) ORDER BY e.id LIMIT :limit"


def revision_page[T: RevisionView](
    model: type[T],
    response: type[HistoryPage[T]],
    rows: list[Any],
    limit: int,
) -> HistoryPage[T]:
    if len(rows) > limit + 1:
        raise FinancialReadUnavailable()
    items = tuple(model.model_validate(dict(row)) for row in rows[:limit])
    return response(items=items, next_before=items[-1].revision if len(rows) > limit else None)


class ValuationReadTransaction(EvidenceReadTransaction):
    def _exists(self, kind: str, identity: str) -> bool:
        table = {
            "snapshot": "snapshot_records",
            "snapshot_selection": "snapshot_selections",
            "market": "market_observations",
            "market_selection": "market_selections",
            "instrument": "instruments",
        }[kind]
        return bool(
            self._execute(
                f"SELECT EXISTS(SELECT 1 FROM app.{table} WHERE owner_id=:owner AND id=:id)",
                id=UUID(identity),
            ).scalar_one()
        )

    def _history(self, select: str, query: HistoryQuery) -> list[Any]:
        return list(
            self._execute(
                select + "WHERE e.owner_id=:owner AND e.id=:id AND "
                "(CAST(:before AS bigint) IS NULL OR e.revision<:before) "
                "ORDER BY e.revision DESC LIMIT :limit",
                id=UUID(query.id),
                before=query.before,
                limit=query.limit + 1,
            )
            .mappings()
            .all()
        )

    def snapshots(self, query: SnapshotQuery) -> FinancialPage[SnapshotView] | None:
        valid = SnapshotQuery.model_validate(query)
        if not self._owned("account", valid.account_id):
            return None
        rows = (
            self._execute(
                SNAPSHOT_SELECT + "WHERE e.owner_id=:owner AND e.account_id=:account "
                "AND NOT EXISTS(SELECT 1 FROM app.snapshot_records n WHERE n.owner_id=e.owner_id "
                "AND n.id=e.id AND n.revision>e.revision) " + NEXT,
                account=UUID(valid.account_id),
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return page_result(
            SnapshotView, FinancialPage[SnapshotView], evidence_rows(list(rows)), valid.limit
        )

    def snapshot_history(self, query: HistoryQuery) -> HistoryPage[SnapshotView] | None:
        valid = HistoryQuery.model_validate(query)
        if not self._exists("snapshot", valid.id):
            return None
        return revision_page(
            SnapshotView,
            HistoryPage[SnapshotView],
            evidence_rows(self._history(SNAPSHOT_SELECT, valid)),
            valid.limit,
        )

    def snapshot_selections(
        self, query: SnapshotQuery
    ) -> FinancialPage[SnapshotSelectionView] | None:
        valid = SnapshotQuery.model_validate(query)
        if not self._owned("account", valid.account_id):
            return None
        rows = (
            self._execute(
                SNAPSHOT_SELECTION + "WHERE e.owner_id=:owner AND e.account_id=:account "
                "AND NOT EXISTS(SELECT 1 FROM app.snapshot_selections n "
                "WHERE n.owner_id=e.owner_id AND n.id=e.id AND n.revision>e.revision) " + NEXT,
                account=UUID(valid.account_id),
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return page_result(
            SnapshotSelectionView, FinancialPage[SnapshotSelectionView], list(rows), valid.limit
        )

    def snapshot_selection_history(
        self, query: HistoryQuery
    ) -> HistoryPage[SnapshotSelectionView] | None:
        valid = HistoryQuery.model_validate(query)
        if not self._exists("snapshot_selection", valid.id):
            return None
        return revision_page(
            SnapshotSelectionView,
            HistoryPage[SnapshotSelectionView],
            self._history(SNAPSHOT_SELECTION, valid),
            valid.limit,
        )

    def snapshot_resolution(self, query: InspectQuery) -> SnapshotResolution | None:
        valid = InspectQuery.model_validate(query)
        result = SnapshotTransaction(self._accounts._unit).resolve(UUID(valid.id))
        if result is None:
            return None
        selection = (
            self._execute(
                SNAPSHOT_SELECTION + "WHERE e.owner_id=:owner AND e.id=:id "
                "ORDER BY e.revision DESC LIMIT 1",
                id=UUID(valid.id),
            )
            .mappings()
            .one()
        )
        snapshot = None
        if result.snapshot is not None:
            rows = (
                self._execute(
                    SNAPSHOT_SELECT
                    + "WHERE e.owner_id=:owner AND e.id=:id AND e.revision=:revision",
                    id=result.snapshot.id,
                    revision=result.snapshot.revision,
                )
                .mappings()
                .all()
            )
            if len(rows) != 1:
                raise FinancialReadUnavailable()
            snapshot = SnapshotView.model_validate(evidence_rows(list(rows))[0])
        return SnapshotResolution.model_validate(
            dict(selection=dict(selection), state=result.state, snapshot=snapshot)
        )

    def listings(self, query: ListingQuery) -> FinancialPage[ListingView] | None:
        valid = ListingQuery.model_validate(query)
        if not self._exists("instrument", valid.instrument_id):
            return None
        rows = (
            self._execute(
                "SELECT e.id::text AS id,e.instrument_id::text AS instrument_id,e.venue,e.symbol,"
                "e.series,e.quote_currency FROM app.instrument_listings e "
                "WHERE e.owner_id=:owner AND e.instrument_id=:instrument " + NEXT,
                instrument=UUID(valid.instrument_id),
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return page_result(ListingView, FinancialPage[ListingView], list(rows), valid.limit)

    def _market_rows(self, query: MarketQuery, *, selection: bool = False) -> list[Any] | None:
        if query.instrument_id is not None and not self._exists("instrument", query.instrument_id):
            return None
        select = MARKET_SELECTION if selection else MARKET_SELECT
        latest = (
            "AND NOT EXISTS(SELECT 1 FROM app.market_selections n WHERE n.owner_id=e.owner_id "
            "AND n.id=e.id AND n.revision>e.revision) "
            if selection
            else ""
        )
        return list(
            self._execute(
                select + "WHERE e.owner_id=:owner AND e.kind=:kind AND e.instrument_id "
                "IS NOT DISTINCT FROM CAST(:instrument AS uuid) " + latest + NEXT,
                kind=query.kind,
                instrument=UUID(query.instrument_id) if query.instrument_id else None,
                after=UUID(query.after) if query.after else None,
                limit=query.limit + 1,
            )
            .mappings()
            .all()
        )

    def market_observations(
        self, query: MarketQuery
    ) -> FinancialPage[MarketObservationView] | None:
        valid = MarketQuery.model_validate(query)
        rows = self._market_rows(valid)
        return (
            None
            if rows is None
            else page_result(
                MarketObservationView, FinancialPage[MarketObservationView], rows, valid.limit
            )
        )

    def market_selections(self, query: MarketQuery) -> FinancialPage[MarketSelectionView] | None:
        valid = MarketQuery.model_validate(query)
        rows = self._market_rows(valid, selection=True)
        return (
            None
            if rows is None
            else page_result(
                MarketSelectionView, FinancialPage[MarketSelectionView], rows, valid.limit
            )
        )

    def market_selection_history(
        self, query: HistoryQuery
    ) -> HistoryPage[MarketSelectionView] | None:
        valid = HistoryQuery.model_validate(query)
        if not self._exists("market_selection", valid.id):
            return None
        return revision_page(
            MarketSelectionView,
            HistoryPage[MarketSelectionView],
            self._history(MARKET_SELECTION, valid),
            valid.limit,
        )

    def market_inspect(self, query: InspectQuery) -> MarketObservationView | None:
        valid = InspectQuery.model_validate(query)
        row = (
            self._execute(MARKET_SELECT + "WHERE e.owner_id=:owner AND e.id=:id", id=UUID(valid.id))
            .mappings()
            .one_or_none()
        )
        return MarketObservationView.model_validate(dict(row)) if row else None

    def market_resolution(self, query: InspectQuery) -> MarketResolution | None:
        valid = InspectQuery.model_validate(query)
        result = MarketTransaction(self._accounts._unit).resolve(UUID(valid.id))
        if result is None:
            return None
        row = (
            self._execute(
                MARKET_SELECTION + "WHERE e.owner_id=:owner AND e.id=:id "
                "ORDER BY e.revision DESC LIMIT 1",
                id=UUID(valid.id),
            )
            .mappings()
            .one()
        )
        observation = (
            self.market_inspect(InspectQuery(id=str(result.observation.id)))
            if result.observation
            else None
        )
        return MarketResolution.model_validate(
            dict(selection=dict(row), state=result.state, observation=observation)
        )
