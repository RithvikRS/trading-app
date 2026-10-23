"""Short-lived, server-only password/MFA operations; no application sessions."""

import hashlib
import re
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from uuid import UUID

from pydantic import SecretStr

from trading_auth.models import (
    AuthenticatedOwner,
    AuthenticationDenied,
    AuthenticationLimited,
    AuthenticationUnavailable,
    Enrollment,
    IdentityStore,
    OwnerBinding,
    Provider,
    Tokens,
)


class AttemptLimiter:
    """Bounded single-process admission, including failed and abandoned attempts."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._salt = secrets.token_bytes(32)
        self._lock = threading.Lock()
        self._buckets: dict[bytes, list[float]] = {}

    def take(self, identity: str) -> None:
        key = hashlib.blake2b(identity.encode(), key=self._salt, digest_size=32).digest()
        with self._lock:
            now = self._clock()
            self._buckets = {
                k: [stamp for stamp in values if now - stamp < 300]
                for k, values in self._buckets.items()
                if values and now - values[-1] < 300
            }
            total = self._buckets.setdefault(b"", [])
            values = self._buckets.setdefault(key, [])
            if len(total) >= 30 or len(values) >= 5:
                raise AuthenticationLimited()
            total.append(now)
            values.append(now)


class AuthenticationAttempt:
    def __init__(
        self,
        provider: Provider,
        identities: IdentityStore,
        tokens: Tokens,
        binding: OwnerBinding,
        clock: Callable[[], float],
        started: float,
    ) -> None:
        self._provider, self._identities = provider, identities
        self._tokens: Tokens | None = tokens
        self._binding, self._clock = binding, clock
        self._deadline = started + 300
        self._factor: UUID | None = None
        self._enrolling = False
        self._attempts = 0
        self._finished = False
        self._lock = threading.Lock()

    def _current(self) -> Tokens:
        tokens = self._tokens
        if (
            self._finished
            or tokens is None
            or self._clock() >= self._deadline
            or time.time() >= tokens.identity.expires_at
        ):
            raise AuthenticationDenied()
        binding = self._identities.lookup(tokens.identity.issuer, tokens.identity.subject)
        if binding is None or binding.owner_id != self._binding.owner_id:
            raise AuthenticationDenied()
        self._binding = binding
        return tokens

    @contextmanager
    def _operation(self) -> Iterator[Tokens]:
        if not self._lock.acquire(blocking=False):
            raise AuthenticationLimited()
        try:
            yield self._current()
        finally:
            self._lock.release()

    def prepare_mfa(self) -> Enrollment | None:
        """Return a secret once for first enrollment, or require the existing TOTP."""
        with self._operation() as tokens:
            if self._factor is not None:
                raise AuthenticationDenied()
            factors = self._provider.factors(tokens)
            verified = [factor for factor in factors if factor.verified and factor.kind == "totp"]
            if verified:
                self._factor = sorted(verified, key=lambda factor: str(factor.id))[0].id
                self._current()
                return None
            # Never turn missing/deleted/unsupported factors into a recovery bypass.
            if factors or self._binding.mfa_enrolled:
                raise AuthenticationDenied()
            enrollment = self._provider.enroll(tokens)
            self._factor, self._enrolling = enrollment.factor_id, True
            self._current()
            return enrollment

    def verify_mfa(self, code: SecretStr) -> AuthenticatedOwner:
        with self._operation() as tokens:
            if self._factor is None or self._attempts >= 5:
                raise AuthenticationDenied()
            self._attempts += 1
            if not re.fullmatch(r"[0-9]{6}", code.get_secret_value()):
                raise AuthenticationDenied()
            factors = self._provider.factors(tokens)
            selected = [
                factor for factor in factors if factor.id == self._factor and factor.kind == "totp"
            ]
            if len(selected) != 1 or (not self._enrolling and not selected[0].verified):
                raise AuthenticationDenied()
            verified = self._provider.verify(tokens, self._factor, code)
            if verified.identity.aal != "aal2" or (
                verified.identity.issuer,
                verified.identity.subject,
                verified.identity.session_id,
            ) != (tokens.identity.issuer, tokens.identity.subject, tokens.identity.session_id):
                raise AuthenticationDenied()
            self._tokens = verified
            self._current()
            # Check provider state after verification, not just the returned AAL claim.
            if not any(
                factor.id == self._factor and factor.kind == "totp" and factor.verified
                for factor in self._provider.factors(verified)
            ):
                raise AuthenticationDenied()
            self._identities.complete_enrollment(
                verified.identity.issuer,
                verified.identity.subject,
                self._binding.owner_id,
            )
            self._current()
            self._finished = True
            return AuthenticatedOwner(self._binding.owner_id, verified.identity)

    def close(self) -> None:
        with self._lock:
            tokens, self._tokens = self._tokens, None
            self._finished = True
            if tokens is not None:
                # Local provider-session cleanup, not application logout/revocation.
                # A failed discard never restores the local attempt.
                try:
                    self._provider.discard(tokens)
                except Exception:
                    raise AuthenticationUnavailable() from None


class Authenticator:
    def __init__(
        self,
        provider: Provider,
        identities: IdentityStore,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._provider, self._identities, self._clock = provider, identities, clock
        self._limiter = AttemptLimiter(clock)
        self._capacity = threading.BoundedSemaphore(4)
        self._owners_lock = threading.Lock()
        self._owners: set[UUID] = set()

    @contextmanager
    def begin(self, email: str, password: SecretStr) -> Iterator[AuthenticationAttempt]:
        if (
            not isinstance(email, str)
            or not re.fullmatch(r"[^\s@\x00-\x1f]{1,64}@[^\s@\x00-\x1f]{1,189}", email)
            or len(email) > 254
            or not 1 <= len(password.get_secret_value()) <= 1024
        ):
            raise AuthenticationDenied()
        self._limiter.take(email.casefold())
        if not self._capacity.acquire(blocking=False):
            raise AuthenticationLimited()
        tokens: Tokens | None = None
        attempt: AuthenticationAttempt | None = None
        owner: UUID | None = None
        started = self._clock()
        try:
            tokens = self._provider.password(email, password)
            password = SecretStr("")
            email = ""
            if tokens.identity.aal != "aal1":
                raise AuthenticationDenied()
            binding = self._identities.lookup(tokens.identity.issuer, tokens.identity.subject)
            if binding is None:
                raise AuthenticationDenied()
            with self._owners_lock:
                if binding.owner_id in self._owners:
                    raise AuthenticationLimited()
                owner = binding.owner_id
                self._owners.add(owner)
            attempt = AuthenticationAttempt(
                self._provider, self._identities, tokens, binding, self._clock, started
            )
            attempt._current()
            yield attempt
        except AuthenticationDenied, AuthenticationUnavailable:
            raise
        except Exception:
            raise AuthenticationUnavailable() from None
        finally:
            try:
                if attempt is not None:
                    attempt.close()
                elif tokens is not None:
                    try:
                        self._provider.discard(tokens)
                    except Exception:
                        raise AuthenticationUnavailable() from None
            finally:
                if owner is not None:
                    with self._owners_lock:
                        self._owners.discard(owner)
                self._capacity.release()
