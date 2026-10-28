"""Protected owner-declared bank setup; no issuer credentials or acquisition."""

from collections.abc import Callable

from fastapi import APIRouter, Request
from pydantic_core import PydanticSerializationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse, Response

from trading_api.authentication import CookiePolicy
from trading_api.bank_setup_contracts import (
    BankSetupCommand,
    BankSetupHead,
    BankSetupQuery,
    BankSetupReceipt,
)
from trading_api.credit_read_contracts import serialize_response
from trading_api.read_contracts import WireModel
from trading_auth.browser import BrowserAuth
from trading_auth.models import AuthenticationDenied
from trading_db.accounts import AccountUnavailable
from trading_db.bank_setup import BankSetupTransaction, BankSetupUnavailable
from trading_db.connections import DatabaseFailure
from trading_db.workspace import OwnerAccessDenied, WorkspaceDatabase


class SetupConflict(Exception):
    pass


def content[T: WireModel](
    model: type[T], operation: Callable[[BankSetupTransaction], T], setup: BankSetupTransaction
) -> bytes:
    try:
        result = operation(setup)
    except AccountUnavailable, BankSetupUnavailable:
        raise SetupConflict() from None
    # Only declared, bounded data extraction occurs inside this handler. Neither the
    # operation nor final session validation can be mistaken for a serialization error.
    try:
        encoded = serialize_response(model, result)
        if len(encoded) > 8192:
            raise ValueError()
        return encoded
    except ValueError, TypeError, AttributeError, KeyError, PydanticSerializationError:
        raise SetupConflict() from None


def routes(browser: BrowserAuth, database: WorkspaceDatabase, policy: CookiePolicy) -> APIRouter:
    router = APIRouter(prefix="/api/v1/finance/bank-account-setup")

    def execute[T: WireModel](
        request: Request,
        model: type[T],
        operation: Callable[[BankSetupTransaction], T],
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
                    encoded = content(model, operation, BankSetupTransaction(unit))
                    validate()  # Denial/context/limit exceptions retain their auth semantics.
            except OwnerAccessDenied:
                raise AuthenticationDenied() from None
            except SetupConflict:
                status = 409
            except DatabaseFailure, SQLAlchemyError:
                status = 503
        if status != 200:
            return JSONResponse(
                {
                    "error": "bank_setup_conflict"
                    if status == 409
                    else "financial_data_unavailable",
                    "request_id": request.state.request_id,
                },
                status_code=status,
            )
        return Response(encoded, media_type="application/json")

    @router.post("/query")
    def query(body: BankSetupQuery, request: Request) -> Response:
        return execute(request, BankSetupHead, lambda setup: setup.query(), read_only=True)

    @router.post("/create")
    def create(body: BankSetupCommand, request: Request) -> Response:
        return execute(request, BankSetupReceipt, lambda setup: setup.create(body))

    return router
