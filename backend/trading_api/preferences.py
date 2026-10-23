"""Authenticated display settings; no client-supplied ownership or financial fields."""

from fastapi import APIRouter, HTTPException, Request

from trading_api.authentication import CookiePolicy
from trading_auth.browser import BrowserAuth
from trading_auth.models import AuthenticationDenied
from trading_db.workspace import (
    OwnerAccessDenied,
    PreferenceSnapshot,
    PreferenceUpdate,
    WorkspaceDatabase,
)


def routes(browser: BrowserAuth, database: WorkspaceDatabase, policy: CookiePolicy) -> APIRouter:
    router = APIRouter(prefix="/api/v1/preferences")

    def execute(request: Request, update: PreferenceUpdate | None = None) -> PreferenceSnapshot:
        with browser.workspace_access(
            request.cookies.get(policy.session, ""),
            request.headers.get("x-csrftoken", ""),
            request.state.request_id,
        ) as (owner, validate):
            try:
                with database.transaction(owner) as unit:
                    result = (
                        unit.preference_snapshot()
                        if update is None
                        else unit.compare_preferences(update)
                    )
                    validate()  # Expiry/disabled identity during SQL rolls back the write.
            except OwnerAccessDenied:
                raise AuthenticationDenied() from None
        # A conflict is an expected application result, not an authentication failure.
        if result is None:
            raise HTTPException(409)
        return result

    @router.get("")
    def read(request: Request) -> PreferenceSnapshot:
        return execute(request)

    @router.put("")
    def write(body: PreferenceUpdate, request: Request) -> PreferenceSnapshot:
        return execute(request, body)

    return router
