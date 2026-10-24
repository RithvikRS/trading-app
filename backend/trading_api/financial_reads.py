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
from trading_auth.browser import BrowserAuth
from trading_auth.models import AuthenticationDenied
from trading_db.connections import DatabaseFailure
from trading_db.evidence_reads import EvidenceReadTransaction
from trading_db.financial_reads import FinancialReadUnavailable
from trading_db.workspace import OwnerAccessDenied, WorkspaceDatabase

MAX_RESPONSE_BYTES = 262144


def routes(browser: BrowserAuth, database: WorkspaceDatabase, policy: CookiePolicy) -> APIRouter:
    router = APIRouter(prefix="/api/v1/finance")

    def execute[T: WireModel](
        request: Request,
        operation: Callable[[EvidenceReadTransaction], T | None],
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
                    reads = EvidenceReadTransaction(unit)
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

    return router
