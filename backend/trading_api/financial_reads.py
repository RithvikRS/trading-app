"""Read-only financial queries inside the authenticated browser and owner boundaries."""

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import Response

from trading_api.authentication import CookiePolicy
from trading_api.evidence_read_contracts import (
    EventQuery,
    EventView,
    HistoryPage,
    HistoryQuery,
    LotObservationQuery,
    LotObservationView,
    LotQuery,
    LotView,
)
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
from trading_api.read_contracts import (
    AccountView,
    FinancialPage,
    InstrumentView,
    PageQuery,
    PositionQuery,
    PositionView,
    SourceView,
    WireModel,
)
from trading_api.receipt_read_contracts import (
    ComparisonInputView,
    CompletedRowView,
    InputQuery,
    ReceiptChildrenQuery,
    ReceiptQuery,
    ReceiptView,
    ScopeInspection,
    ScopeView,
)
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
from trading_auth.browser import BrowserAuth
from trading_auth.models import AuthenticationDenied
from trading_db.connections import DatabaseFailure
from trading_db.financial_reads import FinancialReadUnavailable
from trading_db.receipt_reads import ReceiptReadTransaction
from trading_db.workspace import OwnerAccessDenied, WorkspaceDatabase

MAX_RESPONSE_BYTES = 262144


def routes(browser: BrowserAuth, database: WorkspaceDatabase, policy: CookiePolicy) -> APIRouter:
    router = APIRouter(prefix="/api/v1/finance")

    def execute[T: WireModel](
        request: Request,
        operation: Callable[[ReceiptReadTransaction], T | None],
    ) -> Response:
        unavailable = False
        content = None
        with browser.workspace_access(
            request.cookies.get(policy.session, ""),
            request.headers.get("x-csrftoken", ""),
            request.state.request_id,
        ) as (owner, validate):
            try:
                with database.transaction(owner, read_only=True) as unit:
                    reads = ReceiptReadTransaction(unit)
                    with reads.consistent():
                        result = operation(reads)
                        content = None if result is None else result.model_dump_json().encode()
                        if content is not None and len(content) > MAX_RESPONSE_BYTES:
                            raise FinancialReadUnavailable()
                    validate()
            except OwnerAccessDenied:
                raise AuthenticationDenied() from None
            except DatabaseFailure, SQLAlchemyError:
                # The auth guard must exit normally for an application-data failure.
                # Its registry wrapper deliberately maps unknown errors to auth outages.
                unavailable = True
        if unavailable:
            raise FinancialReadUnavailable()
        if content is None:
            raise HTTPException(404)
        return Response(content, media_type="application/json")

    @router.post("/accounts/query", response_model=FinancialPage[AccountView])
    def accounts(body: PageQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.accounts(body))

    @router.post("/sources/query", response_model=FinancialPage[SourceView])
    def sources(body: PageQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.sources(body))

    @router.post("/instruments/query", response_model=FinancialPage[InstrumentView])
    def instruments(body: PageQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.instruments(body))

    @router.post("/positions/query", response_model=FinancialPage[PositionView])
    def positions(body: PositionQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.positions(body))

    @router.post("/events/query", response_model=FinancialPage[EventView])
    def events(body: EventQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.events(body))

    @router.post("/events/history", response_model=HistoryPage[EventView])
    def event_history(body: HistoryQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.event_history(body))

    @router.post("/lots/query", response_model=FinancialPage[LotView])
    def lots(body: LotQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.lots(body))

    @router.post("/lots/observations/query", response_model=FinancialPage[LotObservationView])
    def lot_observations(body: LotObservationQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.lot_observations(body))

    @router.post("/lots/observations/history", response_model=HistoryPage[LotObservationView])
    def lot_history(body: HistoryQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.lot_history(body))

    @router.post("/snapshots/query", response_model=FinancialPage[SnapshotView])
    def snapshots(body: SnapshotQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.snapshots(body))

    @router.post("/snapshots/history", response_model=HistoryPage[SnapshotView])
    def snapshot_history(body: HistoryQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.snapshot_history(body))

    @router.post("/snapshots/selections/query", response_model=FinancialPage[SnapshotSelectionView])
    def snapshot_selections(body: SnapshotQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.snapshot_selections(body))

    @router.post("/snapshots/selections/history", response_model=HistoryPage[SnapshotSelectionView])
    def snapshot_selection_history(body: HistoryQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.snapshot_selection_history(body))

    @router.post("/snapshots/selections/resolve", response_model=SnapshotResolution)
    def snapshot_resolution(body: InspectQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.snapshot_resolution(body))

    @router.post("/listings/query", response_model=FinancialPage[ListingView])
    def listings(body: ListingQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.listings(body))

    @router.post("/markets/observations/query", response_model=FinancialPage[MarketObservationView])
    def market_observations(body: MarketQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.market_observations(body))

    @router.post("/markets/observations/inspect", response_model=MarketObservationView)
    def market_inspect(body: InspectQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.market_inspect(body))

    @router.post("/markets/selections/query", response_model=FinancialPage[MarketSelectionView])
    def market_selections(body: MarketQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.market_selections(body))

    @router.post("/markets/selections/history", response_model=HistoryPage[MarketSelectionView])
    def market_selection_history(body: HistoryQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.market_selection_history(body))

    @router.post("/markets/selections/resolve", response_model=MarketResolution)
    def market_resolution(body: InspectQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.market_resolution(body))

    @router.post("/imports/observations/query", response_model=FinancialPage[SourceObservationView])
    def source_observations(body: ObservationQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.source_observations(body))

    @router.post("/imports/batches/query", response_model=HistoryPage[BatchView])
    def import_batches(body: BatchQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.import_batches(body))

    @router.post("/imports/rows/query", response_model=RowPage)
    def import_rows(body: RowQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.import_rows(body))

    @router.post("/imports/rows/inspect", response_model=ImportRowView)
    def import_row(body: InspectQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.import_row(body))

    @router.post("/imports/reviews/history", response_model=HistoryPage[ReviewView])
    def review_history(body: HistoryQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.review_history(body))

    @router.post("/receipts/query", response_model=FinancialPage[ReceiptView])
    def receipts(body: ReceiptQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.receipts(body))

    @router.post("/receipts/inspect", response_model=ReceiptView)
    def receipt(body: InspectQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.receipt(body))

    @router.post("/receipts/rows/query", response_model=FinancialPage[CompletedRowView])
    def receipt_effects(body: ReceiptChildrenQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.receipt_effects(body))

    @router.post("/receipts/scopes/query", response_model=FinancialPage[ScopeView])
    def receipt_scopes(body: ReceiptChildrenQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.receipt_scopes(body))

    @router.post("/receipts/scopes/inspect", response_model=ScopeInspection)
    def scope_inspection(body: InspectQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.scope_inspection(body))

    @router.post("/receipts/inputs/query", response_model=FinancialPage[ComparisonInputView])
    def comparison_inputs(body: InputQuery, request: Request) -> Response:
        return execute(request, lambda reads: reads.comparison_inputs(body))

    return router
