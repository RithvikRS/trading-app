"""Browser authentication lifecycle. Cookies are opaque; provider credentials stay here."""

import hashlib
import re
import secrets
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import SecretStr

from trading_auth.models import (
    AuthenticationDenied,
    AuthenticationLimited,
    AuthenticationUnavailable,
)
from trading_auth.session_models import (
    Event,
    SessionRow,
    SessionState,
    Stage,
    Vault,
    new_cookie,
    verifier,
)
from trading_auth.supabase import SupabaseProvider
from trading_db.sessions import SessionDatabase


class BrowserAuth:
    def __init__(
        self,
        provider: SupabaseProvider,
        store: SessionDatabase,
        vault: Vault,
        *,
        recovery_email: bool = False,
    ) -> None:
        self.provider, self.store, self.vault = provider, store, vault
        self.recovery_email = recovery_email
        self._capacity = threading.BoundedSemaphore(4)

    def close(self) -> None:
        self.provider.close()
        self.store.close()

    @contextmanager
    def _admission(self, email: str) -> Iterator[datetime]:
        if len(email) > 254 or not re.fullmatch(
            r"[^\s@\x00-\x1f]{1,64}@[^\s@\x00-\x1f]{1,189}",
            email,
        ):
            raise AuthenticationDenied()
        started = self.store.admit(self.vault.rate_key(email))
        if not self._capacity.acquire(blocking=False):
            raise AuthenticationLimited()
        try:
            yield started
        finally:
            self._capacity.release()

    @contextmanager
    def _lease(
        self,
        cookie: str,
        stages: tuple[Stage, ...],
        request: str,
        csrf: str,
        name: Event,
        *,
        interrupt: bool = False,
    ) -> Iterator[tuple[SessionRow, SessionState]]:
        row = self.store.claim(verifier(cookie), stages, request, interrupt=interrupt)
        state = None
        try:
            state = self.vault.open(row)
            if not secrets.compare_digest(state.csrf, hashlib.sha256(csrf.encode()).hexdigest()):
                raise AuthenticationDenied()
            binding = self.store.lookup(state.issuer, state.subject)
            if binding is None or binding.owner_id != row.owner:
                raise AuthenticationDenied()
            yield row, state
        except BaseException as error:
            self.store.revoke(
                row.verifier,
                request,
                name=name,
                outcome=("denied" if isinstance(error, AuthenticationDenied) else "unavailable"),
            )
            if state is not None:
                self._discard(state, request, row)
            if isinstance(error, (AuthenticationDenied, AuthenticationUnavailable)):
                raise
            if not isinstance(error, Exception):
                raise
            raise AuthenticationUnavailable() from None

    def _discard(
        self,
        state: SessionState,
        request: str,
        row: SessionRow | None = None,
        *,
        all_sessions: bool = False,
    ) -> bool:
        try:
            self.provider.discard(state.tokens(), all_sessions=all_sessions)
            return True
        except Exception:
            self.store.audit(
                "logout",
                "unavailable",
                request,
                row.owner if row else None,
                row.reference if row else None,
            )
            return False

    def start(
        self,
        email: str,
        credential: SecretStr,
        csrf: str,
        request: str,
        *,
        recovery: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        if recovery and not self.recovery_email:
            raise AuthenticationUnavailable()
        if not 1 <= len(credential.get_secret_value()) <= 1024 or (
            recovery and not re.fullmatch(r"[0-9]{6,10}", credential.get_secret_value())
        ):
            raise AuthenticationDenied()
        name: Event = "recovery_verify" if recovery else "login"
        with self._admission(email) as started:
            state = None
            try:
                tokens = (
                    self.provider.verify_recovery(email, credential)
                    if recovery
                    else self.provider.password(email, credential)
                )
                state = SessionState.from_tokens(
                    tokens,
                    primary="otp" if recovery else "password",
                    csrf=hashlib.sha256(csrf.encode()).hexdigest(),
                    fresh_until=int(started.timestamp()) + 300,
                )
                binding = self.store.lookup(state.issuer, state.subject)
                if binding is None or (recovery and not binding.mfa_enrolled):
                    raise AuthenticationDenied()
                factors = self.provider.factors(tokens)
                choices = [
                    factor.id for factor in factors if factor.kind == "totp" and factor.verified
                ]
                enrollment = None
                enrolling = None
                if not choices:
                    if recovery or binding.mfa_enrolled:
                        raise AuthenticationDenied()
                    if not factors:
                        enrollment = self.provider.enroll(tokens)
                        enrolling = enrollment.factor_id
                    elif (
                        len(factors) == 1 and factors[0].kind == "totp" and not factors[0].verified
                    ):
                        # Resume with the previously displayed seed; never reveal or replace it.
                        enrolling = factors[0].id
                    else:
                        raise AuthenticationDenied()
                    choices = [enrolling]
                state = state.model_copy(update={"factors": tuple(choices), "enrolling": enrolling})
                cookie = new_cookie()
                key = verifier(cookie)
                self.store.create(
                    key,
                    binding.owner_id,
                    state.issuer,
                    state.subject,
                    "recovery" if recovery else "login",
                    self.vault.seal(state, key),
                    started,
                    request,
                    name,
                )
                result: dict[str, Any] = {
                    "status": "mfa_required",
                    "factors": [str(x) for x in choices],
                }
                if enrollment is not None:
                    result["setup_key"] = enrollment.secret.get_secret_value()
                return cookie, result
            except BaseException as error:
                self.store.audit(
                    name,
                    "denied" if isinstance(error, AuthenticationDenied) else "unavailable",
                    request,
                )
                if state is not None:
                    self._discard(state, request)
                if isinstance(error, (AuthenticationDenied, AuthenticationUnavailable)):
                    raise
                if not isinstance(error, Exception):
                    raise
                raise AuthenticationUnavailable() from None

    def mfa(
        self,
        cookie: str,
        factor: UUID,
        code: SecretStr,
        csrf: str,
        request: str,
    ) -> tuple[str, dict[str, Any]]:
        with self._lease(cookie, ("login", "recovery"), request, csrf, "mfa") as (row, state):
            if factor not in state.factors or not re.fullmatch(
                r"[0-9]{6}", code.get_secret_value()
            ):
                raise AuthenticationDenied()
            if not any(
                f.id == factor and f.kind == "totp" and (f.verified or factor == state.enrolling)
                for f in self.provider.factors(state.tokens())
            ):
                raise AuthenticationDenied()
            tokens = self.provider.verify(state.tokens(), factor, code, primary=state.primary)
            if not any(
                f.id == factor and f.kind == "totp" and f.verified
                for f in self.provider.factors(tokens)
            ):
                raise AuthenticationDenied()
            self.store.complete_enrollment(state.issuer, state.subject, row.owner)
            state = SessionState.from_tokens(
                tokens,
                factors=state.factors,
                primary=state.primary,
                proof=factor,
                csrf=state.csrf,
                fresh_until=state.fresh_until,
            )
            new = new_cookie()
            key = verifier(new)
            stage: Stage = "password" if row.stage == "recovery" else "active"
            self.store.finish(
                row,
                key,
                self.vault.seal(state, key),
                stage,
                request,
                name="mfa",
                revoke_others=stage == "password",
            )
            return new, {"status": "password_required" if stage == "password" else "authenticated"}

    def _refresh(self, state: SessionState) -> SessionState:
        state = state.renewed(self.provider.refresh(state.tokens(), primary=state.primary))
        current = self.provider.factors(state.tokens())
        factors = tuple(f.id for f in current if f.kind == "totp" and f.verified)
        if state.proof not in factors:
            raise AuthenticationDenied()
        return state.model_copy(
            update={
                "factors": factors,
                "unverified": tuple(f.id for f in current if f.kind == "totp" and not f.verified),
            }
        )

    def session(
        self,
        cookie: str,
        csrf: str,
        request: str,
        *,
        activity: bool = False,
    ) -> dict[str, Any]:
        with self._lease(cookie, ("active",), request, csrf, "renewal") as (row, state):
            state = self._refresh(state)
            self.store.finish(
                row,
                row.verifier,
                self.vault.seal(state, row.verifier),
                "active",
                request,
                activity=activity,
            )
            return {
                "status": "authenticated",
                "expires_at": row.expires.isoformat(),
                "idle_expires_at": min(
                    row.expires, datetime.now(UTC) + timedelta(minutes=15) if activity else row.idle
                ).isoformat(),
                "fresh_until": datetime.fromtimestamp(state.fresh_until, UTC).isoformat(),
                "factors": [str(factor) for factor in state.factors],
                "unverified_factors": [str(factor) for factor in state.unverified],
            }

    @contextmanager
    def workspace_access(
        self, cookie: str, csrf: str, request: str
    ) -> Iterator[tuple[UUID, Callable[[], None]]]:
        with self._lease(cookie, ("active",), request, csrf, "renewal") as (row, state):
            state = self._refresh(state)
            self.store.finish(
                row, row.verifier, self.vault.seal(state, row.verifier), "active", request
            )
        # A concurrent logout between refresh and this guard denies access. A logout
        # after admission waits for the bounded workspace transaction to commit/roll back.
        with self.store.workspace_guard(row.verifier, row.owner) as validate:
            yield row.owner, validate

    def logout(
        self,
        cookie: str,
        csrf: str,
        request: str,
        *,
        all_sessions: bool = False,
    ) -> dict[str, Any]:
        stages: tuple[Stage, ...] = (
            ("active",)
            if all_sessions
            else (
                "active",
                "login",
                "recovery",
                "password",
                "factor",
            )
        )
        with self._lease(cookie, stages, request, csrf, "logout", interrupt=True) as (row, state):
            self.store.revoke(
                row.verifier,
                request,
                all_sessions=all_sessions,
                name="revoke_all" if all_sessions else "logout",
                lease=row.lease,
            )
            cleaned = self._discard(state, request, row, all_sessions=all_sessions)
            return {
                "status": "signed_out",
                "provider_cleanup": "complete" if cleaned else "unavailable",
            }

    def recovery_request(self, email: str, request: str) -> None:
        if not self.recovery_email:
            raise AuthenticationUnavailable()
        with self._admission(email):
            try:
                self.provider.request_recovery(email)
            except AuthenticationLimited:
                self.store.audit("recovery_request", "denied", request)
                raise
            except AuthenticationDenied:
                # Uniform response for provider-side unknown/unconfirmed/disabled accounts.
                pass
            except Exception:
                self.store.audit("recovery_request", "unavailable", request)
                raise AuthenticationUnavailable() from None
            self.store.audit("recovery_request", "success", request)

    def password(self, cookie: str, password: SecretStr, csrf: str, request: str) -> None:
        with self._lease(cookie, ("password",), request, csrf, "password_change") as (row, state):
            if not 16 <= len(password.get_secret_value()) <= 128:
                raise AuthenticationDenied()
            # Revoke first. Timeout or provider failure cannot leave an old local session alive.
            self.store.revoke(
                row.verifier, request, all_sessions=True, name="revoke_all", lease=row.lease
            )
            try:
                self.provider.change_password(state.tokens(), password)
            except Exception:
                self.store.audit(
                    "password_change", "unavailable", request, row.owner, row.reference
                )
                raise AuthenticationUnavailable() from None
            self.store.audit("password_change", "success", request, row.owner, row.reference)
            self._discard(state, request, row, all_sessions=True)

    @staticmethod
    def _fresh(state: SessionState) -> None:
        if datetime.now(UTC).timestamp() >= state.fresh_until:
            raise AuthenticationDenied()

    def backup(self, cookie: str, csrf: str, request: str) -> tuple[str, dict[str, str]]:
        with self._lease(cookie, ("active",), request, csrf, "factor_add") as (row, state):
            self._fresh(state)
            state = self._refresh(state)
            factors = self.provider.factors(state.tokens())
            if len(factors) != 1 or not factors[0].verified or factors[0].kind != "totp":
                raise AuthenticationDenied()
            self._fresh(state)
            enrollment = self.provider.enroll(state.tokens(), backup=True)
            self._fresh(state)
            state = state.model_copy(update={"enrolling": enrollment.factor_id})
            new = new_cookie()
            key = verifier(new)
            self.store.finish(row, key, self.vault.seal(state, key), "factor", request)
            return new, {
                "status": "backup_code_required",
                "setup_key": enrollment.secret.get_secret_value(),
                "factor_id": str(enrollment.factor_id),
            }

    def backup_verify(self, cookie: str, code: SecretStr, csrf: str, request: str) -> None:
        with self._lease(cookie, ("factor",), request, csrf, "factor_add") as (row, state):
            self._fresh(state)
            if state.enrolling is None or not re.fullmatch(r"[0-9]{6}", code.get_secret_value()):
                raise AuthenticationDenied()
            tokens = self.provider.verify(state.tokens(), state.enrolling, code)
            factors = {
                f.id for f in self.provider.factors(tokens) if f.verified and f.kind == "totp"
            }
            if state.enrolling not in factors or state.proof not in factors or len(factors) < 2:
                raise AuthenticationDenied()
            self.store.revoke(
                row.verifier, request, all_sessions=True, name="factor_add", lease=row.lease
            )
            self._discard(state.renewed(tokens), request, row, all_sessions=True)

    def remove(self, cookie: str, factor: UUID, csrf: str, request: str) -> None:
        with self._lease(cookie, ("active",), request, csrf, "factor_remove") as (row, state):
            self._fresh(state)
            state = self._refresh(state)
            removing_verified = factor in state.factors and len(state.factors) >= 2
            removing_abandoned = factor in state.unverified and len(state.factors) >= 1
            if factor == state.proof or not (removing_verified or removing_abandoned):
                raise AuthenticationDenied()
            self._fresh(state)
            self.store.revoke(
                row.verifier, request, all_sessions=True, name="revoke_all", lease=row.lease
            )
            try:
                self.provider.remove_factor(state.tokens(), factor)
            except Exception:
                self.store.audit("factor_remove", "unavailable", request, row.owner, row.reference)
                raise AuthenticationUnavailable() from None
            self.store.audit("factor_remove", "success", request, row.owner, row.reference)
            self._discard(state, request, row, all_sessions=True)
