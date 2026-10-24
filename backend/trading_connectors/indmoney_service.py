"""Session-bound authorization and renewal; no provider I/O under database locks."""

import asyncio
import secrets
import threading
from collections.abc import Callable, Coroutine
from contextlib import AbstractContextManager
from typing import Any, TypeVar
from uuid import UUID

from pydantic import SecretStr

from trading_auth.browser import BrowserAuth
from trading_auth.session_models import verifier
from trading_connectors.indmoney_models import (
    AttemptSecrets,
    ConnectorBusy,
    ConnectorRejected,
    ConnectorUnavailable,
    TokenSecrets,
)
from trading_connectors.indmoney_provider import IndmoneyProvider
from trading_db.indmoney import IndmoneyDatabase

T = TypeVar("T")


class IndmoneyService:
    def __init__(
        self, browser: BrowserAuth, store: IndmoneyDatabase, provider: IndmoneyProvider
    ) -> None:
        self.browser, self.store, self.provider = browser, store, provider
        self._capacity = threading.BoundedSemaphore(4)

    def close(self) -> None:
        self.store.close()

    def network(self, operation: Callable[[], Coroutine[Any, Any, T]]) -> T:
        if not self._capacity.acquire(blocking=False):
            raise ConnectorBusy()
        try:
            return asyncio.run(operation())
        except ConnectorUnavailable:
            raise
        except Exception:
            raise ConnectorUnavailable() from None
        finally:
            self._capacity.release()

    def access(
        self, cookie: str, csrf: str, context: str, request: str, *, fresh: bool = False
    ) -> AbstractContextManager[tuple[UUID, Callable[[], None]]]:
        return self.browser.workspace_access(
            cookie, csrf, request, expected_context=context, fresh=fresh
        )

    def begin(self, cookie: str, csrf: str, context: str, request: str) -> tuple[str, str]:
        with self.access(cookie, csrf, context, request, fresh=True) as (owner, validate):
            self.store.admit(owner, request)
            validate()
        evidence = self.network(self.provider.discovery)
        attempt = AttemptSecrets(
            pkce=SecretStr(secrets.token_urlsafe(32)),
            issuer_required=evidence.response_issuer_advertised,
            refresh_supported=evidence.refresh_advertised,
            client_binding=self.provider.binding,
        )
        with self.browser.store.workspace_guard(verifier(cookie), owner) as validate:
            state, binding = self.store.begin(owner, verifier(cookie), attempt, request)
            validate()
        return self.provider.authorization_url(state, attempt.pkce.get_secret_value()), binding

    def complete(
        self, cookie: str, csrf: str, context: str, request: str, *, refresh: bool = False
    ) -> None:
        with self.access(cookie, csrf, context, request, fresh=not refresh) as (owner, validate):
            if refresh:
                self.store.admit(owner, request)
            operation = self.store.claim(owner, verifier(cookie), refresh=refresh)
            validate()
        tokens = None
        try:
            if refresh:
                previous = operation.tokens
                if previous is None:
                    raise ConnectorRejected()
                tokens = self.network(lambda: self.provider.refresh(previous))
            else:
                attempt = operation.attempt
                if attempt is None or attempt.code is None:
                    raise ConnectorRejected()
                code = attempt.code
                tokens = self.network(lambda: self.provider.exchange(code, attempt.pkce))
                if tokens.refresh_token is not None and not attempt.refresh_supported:
                    raise ConnectorUnavailable()
            with self.browser.store.workspace_guard(operation.session, owner) as validate:
                self.store.publish(operation, tokens, request, validate=validate)
        except BaseException:
            # Clearing local custody precedes best-effort upstream cleanup. Compare-and-set
            # prevents stale failure from deleting a later explicit connection attempt.
            try:
                self.store.fail(operation, request)
            finally:
                if tokens is not None:
                    self.cleanup(tokens, owner, request)
            raise

    def cleanup(self, tokens: TokenSecrets, owner: UUID, request: str) -> bool:
        try:
            self.network(lambda: self.provider.revoke(tokens))
            return True
        except Exception:
            with self.store.owned(owner) as connection:
                self.store.audit(connection, owner, "disconnect", "unavailable", request)
            return False

    def disconnect(self, cookie: str, csrf: str, context: str, request: str) -> dict[str, str]:
        with self.access(cookie, csrf, context, request) as (owner, validate):
            tokens, readable = self.store.disconnect(owner, request)
            validate()
        accepted = self.cleanup(tokens, owner, request) if tokens is not None else True
        cleaned = readable and accepted
        return dict(
            status="disconnected",
            provider_cleanup="confirmed"
            if cleaned and tokens is not None
            else "not_needed"
            if cleaned
            else "unavailable",
        )

    def status(
        self, cookie: str, csrf: str, context: str, request: str
    ) -> dict[str, str | bool | None]:
        with self.access(cookie, csrf, context, request) as (owner, validate):
            result = self.store.status(owner, verifier(cookie))
            validate()
            return result
