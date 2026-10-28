"""Protected existing-source assignment; history proves a saved transition only."""

from collections.abc import Callable

from fastapi import APIRouter, Request
from pydantic_core import PydanticSerializationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse, Response

from trading_api.authentication import CookiePolicy
from trading_api.bank_mapping_contracts import (
    BankMappingChange,
    BankMappingHistoryPage,
    BankMappingHistoryQuery,
    BankMappingTransition,
)
from trading_api.credit_read_contracts import serialize_response
from trading_api.read_contracts import WireModel
from trading_auth.browser import BrowserAuth
from trading_auth.models import AuthenticationDenied
from trading_db.accounts import AccountUnavailable
from trading_db.bank_mappings import BankMappingTransaction, BankMappingUnavailable
from trading_db.connections import DatabaseFailure
from trading_db.workspace import OwnerAccessDenied, WorkspaceDatabase


class MappingConflict(Exception):
    pass


def content[T: WireModel](
    model: type[T],
    operation: Callable[[BankMappingTransaction], T],
    mappings: BankMappingTransaction,
) -> bytes:
    try:
        result = operation(mappings)
    except AccountUnavailable, BankMappingUnavailable:
        raise MappingConflict() from None
    # Only declared data serialization lives inside this broad data exception boundary.
    try:
        encoded = serialize_response(model, result)
        if len(encoded) > 262144:
            raise ValueError()
        return encoded
    except ValueError, TypeError, AttributeError, KeyError, PydanticSerializationError:
        raise MappingConflict() from None


def routes(browser: BrowserAuth, database: WorkspaceDatabase, policy: CookiePolicy) -> APIRouter:
    router = APIRouter(prefix="/api/v1/finance/bank-source-mappings")

    def execute[T: WireModel](
        request: Request,
        model: type[T],
        operation: Callable[[BankMappingTransaction], T],
        *,
        read_only: bool = False,
    ) -> Response:
        status, encoded = 200, b""
        with browser.workspace_access(
            request.cookies.get(policy.session, ""),
            request.headers.get("x-csrftoken", ""),
            request.state.request_id,
            expected_context=request.headers.get("x-workspace-context", ""),
        ) as (owner, validate):
            try:
                with database.transaction(owner, read_only=read_only) as unit:
                    encoded = content(model, operation, BankMappingTransaction(unit))
                    validate()  # Auth denial/context/limits remain outside data exception handlers.
            except OwnerAccessDenied:
                raise AuthenticationDenied() from None
            except MappingConflict:
                status = 409
            except DatabaseFailure, SQLAlchemyError:
                status = 503
        if status != 200:
            return JSONResponse(
                {
                    "error": "bank_mapping_conflict"
                    if status == 409
                    else "financial_data_unavailable",
                    "request_id": request.state.request_id,
                },
                status_code=status,
            )
        return Response(encoded, media_type="application/json")

    @router.post("/history")
    def history(body: BankMappingHistoryQuery, request: Request) -> Response:
        return execute(
            request, BankMappingHistoryPage, lambda mappings: mappings.history(body), read_only=True
        )

    @router.post("/change")
    def change(body: BankMappingChange, request: Request) -> Response:
        return execute(request, BankMappingTransition, lambda mappings: mappings.change(body))

    return router
