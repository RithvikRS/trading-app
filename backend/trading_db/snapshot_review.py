"""Bounded browser orchestration over the existing immutable snapshot services."""

from uuid import UUID

from trading_api.import_read_contracts import BatchView, ReviewView, RowQuery
from trading_api.read_contracts import FinancialPage, InstrumentView, PageQuery, PositionQuery
from trading_api.snapshot_review_contracts import (
    DecisionCommand,
    InvestmentView,
    MappingView,
    ReviewInspection,
)
from trading_api.valuation_read_contracts import InspectQuery
from trading_db.completion import CompletionTransaction
from trading_db.completion_baseline import CompletionUnavailable
from trading_db.completion_contracts import CompletionRequest
from trading_db.financial_reads import page_result
from trading_db.import_reads import BATCH_SELECT, review_view
from trading_db.imports import ImportTransaction
from trading_db.instruments import InstrumentTransaction
from trading_db.receipt_reads import ReceiptReadTransaction


class SnapshotReviewTransaction(ReceiptReadTransaction):
    def queue(self, query: PageQuery) -> FinancialPage[BatchView]:
        rows = (
            self._execute(
                BATCH_SELECT + "WHERE b.owner_id=:owner AND o.coverage='snapshot' "
                "AND NOT EXISTS(SELECT 1 FROM app.import_batches n WHERE n.owner_id=b.owner_id "
                "AND n.observation_id=b.observation_id AND n.revision>b.revision) "
                "AND NOT EXISTS(SELECT 1 FROM app.source_observations n "
                "WHERE n.owner_id=o.owner_id "
                "AND n.previous_id=o.id) AND (CAST(:after AS uuid) IS NULL OR b.id>:after) "
                "ORDER BY b.id LIMIT :limit",
                after=UUID(query.after) if query.after else None,
                limit=query.limit + 1,
            )
            .mappings()
            .all()
        )
        return page_result(BatchView, FinancialPage[BatchView], list(rows), query.limit)

    def inspect(self, identity: UUID) -> ReviewInspection:
        row = (
            self._execute(
                BATCH_SELECT + "WHERE b.owner_id=:owner AND b.id=:id AND o.coverage='snapshot'",
                id=identity,
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise CompletionUnavailable()
        batch = BatchView.model_validate(dict(row))
        page = self.import_rows(RowQuery(batch_id=str(identity), limit=100))
        if page is None or page.next_after_occurrence is not None:
            raise CompletionUnavailable()
        mapping = self._accounts.mapping(UUID(batch.source_id))
        instruments = InstrumentTransaction(self._accounts._unit)
        mappings = []
        for item in page.items:
            current = (
                instruments.mapping(UUID(item.instrument_identifier_id))
                if item.instrument_identifier_id
                else None
            )
            mappings.append(
                MappingView(
                    row_id=item.id,
                    instrument_id=str(current.instrument_id)
                    if current and current.instrument_id
                    else None,
                    listing_id=str(current.listing_id) if current and current.listing_id else None,
                    revision=current.revision if current else 0,
                )
            )
        receipt = self._execute(
            "SELECT id FROM app.completion_receipts WHERE owner_id=:owner AND batch_id=:id",
            id=identity,
        ).scalar_one_or_none()
        return ReviewInspection(
            batch=batch,
            account_id=str(mapping.account_id) if mapping and mapping.account_id else None,
            account_mapping_revision=mapping.revision if mapping else 0,
            rows=page.items,
            mappings=tuple(mappings),
            receipt=self.receipt(InspectQuery(id=str(receipt))) if receipt else None,
        )

    def decide(self, command: DecisionCommand) -> ReviewView:
        imports = ImportTransaction(self._accounts._unit)
        row = imports.get_row(UUID(command.row_id))
        if row is None:
            raise CompletionUnavailable()
        inspection = self.inspect(row.batch_id)
        if (
            inspection.receipt
            or not inspection.batch.is_current
            or not inspection.batch.source_current
        ):
            raise CompletionUnavailable()
        return review_view(
            imports.decide(row.id, command.action, expected_revision=command.expected_revision)
        )

    def snapshot_only(self, request: CompletionRequest) -> None:
        inspection = self.inspect(request.batch_id)
        if any(
            row.kind not in {"position_snapshot", "cash_snapshot", "cancellation"}
            for row in inspection.rows
        ):
            raise CompletionUnavailable()
        if request.mode != "limited" or any(
            row.operation == "correct" and row.target_kind != "snapshot" for row in request.rows
        ):
            raise CompletionUnavailable()

    def rehearse(self, request: CompletionRequest) -> None:
        self.snapshot_only(request)
        # Exercise the actual atomic writer, including deferred constraints. Nothing
        # survives this savepoint, even when validation or serialization fails.
        connection = self._accounts._unit._connection
        savepoint = connection.begin_nested()
        try:
            CompletionTransaction(self._accounts._unit, None).complete(request)
            self._execute("SET CONSTRAINTS ALL IMMEDIATE")
        finally:
            savepoint.rollback()

    def investments(self, query: PositionQuery) -> FinancialPage[InvestmentView] | None:
        positions = self.positions(query)
        if positions is None:
            return None
        instruments = InstrumentTransaction(self._accounts._unit)
        items = []
        for position in positions.items:
            instrument = instruments.get(UUID(position.instrument_id))
            if instrument is None:
                raise CompletionUnavailable()
            identifiers = (
                self._execute(
                    "SELECT e.id FROM app.snapshot_selections e WHERE e.owner_id=:owner "
                    "AND e.position_id=:position AND NOT EXISTS(SELECT 1 "
                    "FROM app.snapshot_selections n "
                    "WHERE n.owner_id=e.owner_id AND n.id=e.id AND n.revision>e.revision) "
                    "ORDER BY e.id LIMIT 4",
                    position=UUID(position.id),
                )
                .scalars()
                .all()
            )
            if len(identifiers) > 3:
                raise CompletionUnavailable()
            choices = tuple(
                self.snapshot_resolution(InspectQuery(id=str(identity))) for identity in identifiers
            )
            if any(choice is None for choice in choices):
                raise CompletionUnavailable()
            items.append(
                InvestmentView.model_validate(
                    dict(
                        **position.model_dump(),
                        instrument=InstrumentView.model_validate(
                            dict(
                                id=str(instrument.id),
                                **instrument.definition.model_dump(mode="json"),
                            )
                        ),
                        choices=choices,
                    )
                )
            )
        return FinancialPage[InvestmentView](items=tuple(items), next_after=positions.next_after)
