"""Session-bound preview and atomic completion of already saved snapshot evidence."""

import hmac
import json
from collections.abc import Callable
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Request
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse, Response

from trading_api.authentication import CookiePolicy
from trading_api.read_contracts import PageQuery, PositionQuery, WireModel
from trading_api.snapshot_review_contracts import (
    AccountMappingCommand,
    CompleteCommand,
    DecisionCommand,
    InstrumentMappingCommand,
    PositionCommand,
    PreviewCommand,
    PreviewView,
)
from trading_api.valuation_read_contracts import InspectQuery
from trading_auth.browser import BrowserAuth
from trading_auth.models import AuthenticationDenied
from trading_db.accounts import AccountUnavailable
from trading_db.completion import CompletionTransaction
from trading_db.completion_baseline import CompletionUnavailable
from trading_db.completion_contracts import CompletionRequest
from trading_db.connections import DatabaseFailure
from trading_db.imports import ImportUnavailable
from trading_db.instruments import InstrumentTransaction, InstrumentUnavailable
from trading_db.snapshot_review import SnapshotReviewTransaction
from trading_db.snapshots import SnapshotUnavailable
from trading_db.workspace import OwnerAccessDenied, WorkspaceDatabase


class PreviewTokens:
    """Ephemeral per-worker keys. Restart invalidates previews, never durable receipts."""

    def __init__(self) -> None:
        self._cipher = Fernet(Fernet.generate_key())

    def seal(self, owner: UUID, context: str, request: CompletionRequest) -> str:
        payload = json.dumps(
            {"owner": str(owner), "context": context, "request": request.model_dump_json()}
        ).encode()
        return self._cipher.encrypt(payload).decode("ascii")

    def open(self, owner: UUID, context: str, token: str) -> CompletionRequest:
        try:
            payload = json.loads(self._cipher.decrypt(token.encode("ascii"), ttl=300))
            if not hmac.compare_digest(payload["owner"], str(owner)) or not hmac.compare_digest(
                payload["context"], context
            ):
                raise CompletionUnavailable()
            return CompletionRequest.model_validate_json(payload["request"])
        except InvalidToken, ValueError, KeyError, TypeError, UnicodeError:
            raise CompletionUnavailable() from None


def routes(browser: BrowserAuth, database: WorkspaceDatabase, policy: CookiePolicy) -> APIRouter:
    router = APIRouter(prefix="/api/v1/finance")
    tokens = PreviewTokens()

    def execute(
        request: Request, operation: Callable[[SnapshotReviewTransaction], WireModel | None]
    ) -> Response:
        status, content = 200, None
        with browser.workspace_access(
            request.cookies.get(policy.session, ""),
            request.headers.get("x-csrftoken", ""),
            request.state.request_id,
            expected_context=request.headers.get("x-workspace-context", ""),
        ) as (owner, validate):
            try:
                with database.transaction(owner) as unit:
                    review = SnapshotReviewTransaction(unit)
                    with review._accounts._write():
                        result = operation(review)
                        content = None if result is None else result.model_dump_json().encode()
                        if content is not None and len(content) > 262144:
                            raise CompletionUnavailable()
                        validate()  # Any expired/revoked original session rolls back every effect.
            except OwnerAccessDenied:
                raise AuthenticationDenied() from None
            except AuthenticationDenied:
                raise
            except (
                AccountUnavailable,
                CompletionUnavailable,
                ImportUnavailable,
                InstrumentUnavailable,
                SnapshotUnavailable,
                ValueError,
            ):
                status = 409
            except DatabaseFailure, SQLAlchemyError:
                status = 503
        if status != 200:
            return JSONResponse(
                {
                    "error": "snapshot_review_conflict"
                    if status == 409
                    else "financial_data_unavailable",
                    "request_id": request.state.request_id,
                },
                status_code=status,
            )
        if content is None:
            return JSONResponse(
                {"error": "not_found", "request_id": request.state.request_id}, status_code=404
            )
        return Response(content, media_type="application/json")

    @router.post("/investments/query")
    def investments(body: PositionQuery, request: Request) -> Response:
        return execute(request, lambda review: review.investments(body))

    @router.post("/snapshot-review/query")
    def queue(body: PageQuery, request: Request) -> Response:
        return execute(request, lambda review: review.queue(body))

    @router.post("/snapshot-review/inspect")
    def inspect(body: InspectQuery, request: Request) -> Response:
        return execute(request, lambda review: review.inspect(UUID(body.id)))

    @router.post("/snapshot-review/decide")
    def decide(body: DecisionCommand, request: Request) -> Response:
        return execute(request, lambda review: review.decide(body))

    @router.post("/snapshot-review/account-mapping")
    def account_mapping(body: AccountMappingCommand, request: Request) -> Response:
        def apply(review: SnapshotReviewTransaction) -> WireModel:
            review._accounts.map(
                UUID(body.source_id),
                UUID(body.account_id),
                expected_revision=body.expected_revision,
            )
            return body

        return execute(request, apply)

    @router.post("/snapshot-review/instrument-mapping")
    def instrument_mapping(body: InstrumentMappingCommand, request: Request) -> Response:
        def apply(review: SnapshotReviewTransaction) -> WireModel:
            InstrumentTransaction(review._accounts._unit).map(
                UUID(body.identifier_id),
                UUID(body.instrument_id),
                expected_revision=body.expected_revision,
                listing_id=UUID(body.listing_id) if body.listing_id else None,
            )
            return body

        return execute(request, apply)

    @router.post("/snapshot-review/position")
    def position(body: PositionCommand, request: Request) -> Response:
        def apply(review: SnapshotReviewTransaction) -> WireModel:
            saved = InstrumentTransaction(review._accounts._unit).position(
                UUID(body.account_id), UUID(body.instrument_id), body.holding_form
            )
            return InspectQuery(id=str(saved.id))

        return execute(request, apply)

    @router.post("/snapshot-review/preview")
    def preview(body: PreviewCommand, request: Request) -> Response:
        def prepare(review: SnapshotReviewTransaction) -> PreviewView:
            unit = review._accounts._unit
            command = body.completion(CompletionTransaction(unit, None).baseline())
            review.rehearse(command)
            return PreviewView(
                token=tokens.seal(unit._owner_id, request.headers["x-workspace-context"], command),
                batch_id=body.batch_id,
                batch_revision=body.batch_revision,
                row_count=len(command.rows),
                selection_count=len(command.selections),
            )

        return execute(request, prepare)

    @router.post("/snapshot-review/complete")
    def complete(body: CompleteCommand, request: Request) -> Response:
        def apply(review: SnapshotReviewTransaction) -> WireModel | None:
            unit = review._accounts._unit
            command = tokens.open(
                unit._owner_id, request.headers["x-workspace-context"], body.token
            )
            review.snapshot_only(command)
            saved = CompletionTransaction(unit, None).complete(command)
            return review.receipt(InspectQuery(id=str(saved.id)))

        return execute(request, apply)

    return router
