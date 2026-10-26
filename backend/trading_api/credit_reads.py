"""Protected identity/provenance reads; no credit financial payload or mutation."""

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import Response

from trading_api.authentication import CookiePolicy
from trading_api.credit_read_contracts import (
    CreditAccountView,
    CreditMappingHistoryPage,
    CreditMappingHistoryQuery,
    CreditPage,
    CreditSourceView,
    serialize_response,
)
from trading_api.read_contracts import PageQuery, WireModel
from trading_api.valuation_read_contracts import InspectQuery
from trading_auth.browser import BrowserAuth
from trading_auth.models import AuthenticationDenied
from trading_db.connections import DatabaseFailure
from trading_db.credit_reads import CreditReadTransaction
from trading_db.financial_reads import FinancialReadUnavailable
from trading_db.workspace import OwnerAccessDenied, WorkspaceDatabase

MAX_RESPONSE_BYTES = 262144


def routes(browser: BrowserAuth, database: WorkspaceDatabase, policy: CookiePolicy) -> APIRouter:
    router = APIRouter(prefix="/api/v1/finance/credit")

    def execute[T: WireModel](
        request: Request, model: type[T], operation: Callable[[CreditReadTransaction], T | None]
    ) -> Response:
        unavailable = False
        content = None
        with browser.workspace_access(
            request.cookies.get(policy.session, ""),
            request.headers.get("x-csrftoken", ""),
            request.state.request_id,
            expected_context=request.headers.get("x-workspace-context", ""),
        ) as (owner, validate):
            try:
                with database.transaction(owner, read_only=True) as unit:
                    reads = CreditReadTransaction(unit)
                    with reads.consistent():
                        result = operation(reads)
                        content = None if result is None else serialize_response(model, result)
                        if content is not None and len(content) > MAX_RESPONSE_BYTES:
                            raise FinancialReadUnavailable()
                    validate()
            except OwnerAccessDenied:
                raise AuthenticationDenied() from None
            except DatabaseFailure, SQLAlchemyError:
                # Exit auth's guard normally on data/serialization failures; no payload escapes.
                unavailable = True
        if unavailable:
            raise FinancialReadUnavailable()
        if content is None:
            raise HTTPException(404)
        return Response(content, media_type="application/json")

    @router.post("/accounts/query", response_model=CreditPage[CreditAccountView])
    def accounts(body: PageQuery, request: Request) -> Response:
        return execute(request, CreditPage[CreditAccountView], lambda reads: reads.accounts(body))

    @router.post("/accounts/inspect", response_model=CreditAccountView)
    def account(body: InspectQuery, request: Request) -> Response:
        return execute(request, CreditAccountView, lambda reads: reads.account(body))

    @router.post("/sources/query", response_model=CreditPage[CreditSourceView])
    def sources(body: PageQuery, request: Request) -> Response:
        return execute(request, CreditPage[CreditSourceView], lambda reads: reads.sources(body))

    @router.post("/sources/mappings/history", response_model=CreditMappingHistoryPage)
    def mappings(body: CreditMappingHistoryQuery, request: Request) -> Response:
        return execute(request, CreditMappingHistoryPage, lambda reads: reads.mapping_history(body))

    return router
