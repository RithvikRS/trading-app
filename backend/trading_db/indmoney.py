"""Credential registry operations. Caller holds the session guard around owned mutations."""

import hashlib
import json
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import Connection, text

from trading_auth.models import AuthenticationDenied, AuthenticationUnavailable
from trading_connectors.indmoney_keys import ConnectorKeys
from trading_connectors.indmoney_models import (
    AttemptSecrets,
    ConnectorBusy,
    ConnectorRejected,
    ConnectorUnavailable,
    TokenSecrets,
    private_document,
)
from trading_db.identities import IdentityDatabase
from trading_db.sessions import ACTIVE, LOCK


def digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


@dataclass(frozen=True, repr=False)
class Operation:
    owner: UUID
    connection: UUID
    revision: int
    lease: UUID
    session: bytes
    expires: datetime
    attempt: AttemptSecrets | None = None
    tokens: TokenSecrets | None = None


class IndmoneyDatabase(IdentityDatabase):
    expected_errors = (
        AuthenticationDenied,
        AuthenticationUnavailable,
        ConnectorRejected,
        ConnectorBusy,
        ConnectorUnavailable,
    )

    def __init__(self, *args: Any, keys: ConnectorKeys, binding: str) -> None:
        super().__init__(*args)
        self.keys, self.binding = keys, binding

    @contextmanager
    def owned(self, owner: UUID) -> Iterator[Connection]:
        try:
            with self._transaction() as connection:
                connection.execute(
                    text("SELECT set_config('app.owner_id', :owner, true)"), {"owner": str(owner)}
                )
                yield connection
        except AuthenticationUnavailable:
            raise ConnectorUnavailable() from None

    @staticmethod
    def audit(connection: Connection, owner: UUID, event: str, outcome: str, request: str) -> None:
        connection.execute(
            text("""
            INSERT INTO app.indmoney_events(id,owner_id,event,outcome,request_id)
            VALUES (:id,:owner,:event,:outcome,:request)
        """),
            dict(id=uuid4(), owner=owner, event=event, outcome=outcome, request=request),
        )

    def admit(self, owner: UUID, request: str) -> None:
        # The caller's session guard already holds LOCK. A distinct connection must not
        # acquire it again: ordering is session guard -> connector transaction throughout.
        with self.owned(owner) as connection:
            counts = connection.execute(
                text("""
                SELECT count(*) AS total, count(*) FILTER (WHERE owner_id=:owner) AS own
                FROM app.indmoney_events WHERE event='start'
                    AND occurred_at>clock_timestamp()-interval '5 minutes'
            """),
                dict(owner=owner),
            ).one()
            if counts.total >= 30 or counts.own >= 5:
                raise ConnectorBusy()
            self.audit(connection, owner, "start", "success", request)

    def begin(
        self, owner: UUID, session: bytes, attempt: AttemptSecrets, request: str
    ) -> tuple[str, str]:
        state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.owned(owner) as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM app.indmoney_connections WHERE owner_id=:owner FOR UPDATE"),
                    dict(owner=owner),
                )
                .mappings()
                .one_or_none()
            )
            if row and (
                row["status"] in {"authorized", "refreshing", "reconnect_required"}
                or row["lease"] is not None
            ):
                raise ConnectorRejected()
            identity = row["id"] if row else uuid4()
            revision = row["revision"] + 1 if row else 1
            connection.execute(
                text("""
                INSERT INTO app.indmoney_connections(id,owner_id,revision,status,client_binding)
                VALUES (:id,:owner,:revision,'pending',:binding)
                ON CONFLICT (owner_id) DO UPDATE SET revision=:revision,status='pending',
                    sealed=NULL,expires_at=NULL,lease=NULL,lease_until=NULL,lease_session=NULL,
                    client_binding=:binding,updated_at=clock_timestamp()
            """),
                dict(id=identity, owner=owner, revision=revision, binding=self.binding),
            )
            connection.execute(
                text(
                    "DELETE FROM app.indmoney_attempts WHERE connection_id=:id "
                    "OR expires_at<=clock_timestamp()"
                ),
                dict(id=identity),
            )
            connection.execute(
                text("""
                INSERT INTO app.indmoney_attempts
                    (state_hash,browser_hash,owner_id,connection_id,revision,session_verifier,sealed,stage)
                VALUES (:state,:browser,:owner,:id,:revision,:session,:sealed,'awaiting')
            """),
                dict(
                    state=digest(state),
                    browser=digest(browser),
                    owner=owner,
                    id=identity,
                    revision=revision,
                    session=session,
                    sealed=self.keys.seal(
                        owner, identity, "attempt", revision, attempt.private_bytes()
                    ),
                ),
            )
        return state, browser

    def receive(
        self, state: str, browser: str, code: SecretStr | None, issuer: str | None, request: str
    ) -> None:
        # This is the sole cross-site boundary. It has no token exchange or financial access.
        with self._transaction() as connection:
            connection.execute(text(LOCK))
            row = (
                connection.execute(
                    text(f"""
                SELECT a.* FROM app.indmoney_attempts a JOIN app.auth_sessions s
                    ON s.verifier=a.session_verifier AND s.owner_id=a.owner_id
                WHERE a.state_hash=:state AND a.browser_hash=:browser AND a.stage='awaiting'
                    AND a.expires_at>clock_timestamp() AND s.stage='active'
                    AND s.expires_at>clock_timestamp() AND s.idle_until>clock_timestamp()
                    AND {ACTIVE} FOR UPDATE OF a
            """),
                    dict(state=digest(state), browser=digest(browser)),
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ConnectorRejected()
            attempt = self._attempt(row)
            from trading_connectors.indmoney_discovery import ISSUER

            valid = (issuer is None and not attempt.issuer_required) or issuer == ISSUER
            if not valid or code is None:
                connection.execute(
                    text("DELETE FROM app.indmoney_attempts WHERE state_hash=:state"),
                    dict(state=row["state_hash"]),
                )
                self.audit(connection, row["owner_id"], "callback", "denied", request)
            else:
                attempt = attempt.model_copy(update={"code": code})
                connection.execute(
                    text(
                        "UPDATE app.indmoney_attempts SET sealed=:sealed,stage='received' "
                        "WHERE state_hash=:state"
                    ),
                    dict(
                        state=row["state_hash"],
                        sealed=self.keys.seal(
                            row["owner_id"],
                            row["connection_id"],
                            "attempt",
                            row["revision"],
                            attempt.private_bytes(),
                        ),
                    ),
                )
                self.audit(connection, row["owner_id"], "callback", "success", request)

    def _attempt(self, row: Any) -> AttemptSecrets:
        try:
            value = AttemptSecrets.model_validate_json(
                self.keys.open(
                    row["owner_id"],
                    row["connection_id"],
                    "attempt",
                    row["revision"],
                    bytes(row["sealed"]),
                )
            )
            if value.client_binding != self.binding:
                raise ConnectorUnavailable()
            return value
        except ValueError:
            raise ConnectorUnavailable() from None

    def claim(self, owner: UUID, session: bytes, *, refresh: bool = False) -> Operation:
        with self.owned(owner) as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT *,clock_timestamp() AS now FROM app.indmoney_connections "
                        "WHERE owner_id=:owner FOR UPDATE"
                    ),
                    dict(owner=owner),
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["client_binding"] != self.binding:
                raise ConnectorRejected()
            if row["lease"] is not None:
                raise ConnectorBusy()
            attempt, tokens = None, None
            if refresh:
                if row["status"] != "authorized":
                    raise ConnectorRejected()
                tokens = self._tokens(row)
                if tokens.refresh_token is None:
                    raise ConnectorRejected()
            else:
                if row["status"] != "pending":
                    raise ConnectorRejected()
                pending = (
                    connection.execute(
                        text("""
                    DELETE FROM app.indmoney_attempts WHERE owner_id=:owner AND connection_id=:id
                        AND revision=:revision AND session_verifier=:session AND stage='received'
                        AND expires_at>clock_timestamp() RETURNING *
                """),
                        dict(owner=owner, id=row["id"], revision=row["revision"], session=session),
                    )
                    .mappings()
                    .one_or_none()
                )
                if pending is None:
                    raise ConnectorRejected()
                attempt = self._attempt(pending)
            lease = uuid4()
            expires = connection.execute(
                text("""
                UPDATE app.indmoney_connections SET lease=:lease,lease_session=:session,
                    lease_until=clock_timestamp()+interval '30 seconds',
                    status=CASE WHEN :refresh THEN 'refreshing' ELSE status END
                WHERE owner_id=:owner RETURNING lease_until
            """),
                dict(owner=owner, lease=lease, session=session, refresh=refresh),
            ).scalar_one()
            return Operation(
                owner, row["id"], row["revision"], lease, session, expires, attempt, tokens
            )

    def publish(
        self,
        operation: Operation,
        tokens: TokenSecrets,
        request: str,
        *,
        validate: Callable[[], None],
    ) -> None:
        with self.owned(operation.owner) as connection:
            revision = operation.revision + 1
            changed = connection.execute(
                text("""
                UPDATE app.indmoney_connections SET status='authorized',sealed=:sealed,
                    revision=:next,expires_at=:started+:ttl*interval '1 second',
                    lease=NULL,lease_until=NULL,lease_session=NULL,updated_at=clock_timestamp()
                WHERE owner_id=:owner AND id=:id AND revision=:revision AND lease=:lease
                    AND lease_session=:session AND lease_until>clock_timestamp()
                    AND client_binding=:binding AND :started+:ttl*interval '1 second'
                        >clock_timestamp() RETURNING id
            """),
                dict(
                    owner=operation.owner,
                    id=operation.connection,
                    revision=operation.revision,
                    next=revision,
                    lease=operation.lease,
                    session=operation.session,
                    binding=self.binding,
                    ttl=tokens.expires_in,
                    started=operation.expires - timedelta(seconds=30),
                    sealed=self.keys.seal(
                        operation.owner,
                        operation.connection,
                        "tokens",
                        revision,
                        self._token_bytes(tokens),
                    ),
                ),
            ).one_or_none()
            if changed is None:
                raise ConnectorRejected()
            self.audit(
                connection,
                operation.owner,
                "refresh" if operation.tokens else "authorize",
                "success",
                request,
            )
            validate()

    def fail(self, operation: Operation, request: str) -> None:
        with self.owned(operation.owner) as connection:
            changed = connection.execute(
                text("""
                UPDATE app.indmoney_connections SET status='reconnect_required',sealed=NULL,
                    expires_at=NULL,lease=NULL,lease_until=NULL,lease_session=NULL,
                    revision=revision+1,updated_at=clock_timestamp()
                WHERE owner_id=:owner AND id=:id AND revision=:revision AND lease=:lease
                RETURNING id
            """),
                dict(
                    owner=operation.owner,
                    id=operation.connection,
                    revision=operation.revision,
                    lease=operation.lease,
                ),
            ).one_or_none()
            if changed:
                self.audit(
                    connection,
                    operation.owner,
                    "refresh" if operation.tokens else "authorize",
                    "unavailable",
                    request,
                )

    def _tokens(self, row: Any) -> TokenSecrets:
        try:
            values = private_document(
                self.keys.open(
                    row["owner_id"], row["id"], "tokens", row["revision"], bytes(row["sealed"])
                )
            )
            if values.pop("client_binding", None) != self.binding:
                raise ConnectorUnavailable()
            return TokenSecrets.model_validate(values)
        except ValueError:
            raise ConnectorUnavailable() from None

    def _token_bytes(self, tokens: TokenSecrets) -> bytes:
        values = private_document(tokens.private_bytes())
        values["client_binding"] = self.binding
        return json.dumps(values, separators=(",", ":")).encode()

    def disconnect(self, owner: UUID, request: str) -> tuple[TokenSecrets | None, bool]:
        tokens, readable = None, True
        with self.owned(owner) as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM app.indmoney_connections WHERE owner_id=:owner FOR UPDATE"),
                    dict(owner=owner),
                )
                .mappings()
                .one_or_none()
            )
            if row and row["sealed"] is not None:
                try:
                    if row["client_binding"] != self.binding:
                        raise ConnectorUnavailable()
                    tokens = self._tokens(row)
                except ConnectorUnavailable:
                    readable = False
            if row and (row["lease"] is not None or row["status"] == "reconnect_required"):
                readable = False  # In-flight issuance cannot be confirmed by revoking old tokens.
            connection.execute(
                text("DELETE FROM app.indmoney_attempts WHERE owner_id=:owner"), dict(owner=owner)
            )
            connection.execute(
                text("""
                UPDATE app.indmoney_connections SET status='disconnected',revision=revision+1,
                    sealed=NULL,expires_at=NULL,lease=NULL,lease_until=NULL,lease_session=NULL,
                    updated_at=clock_timestamp() WHERE owner_id=:owner
            """),
                dict(owner=owner),
            )
            self.audit(connection, owner, "disconnect", "success", request)
        return tokens, readable

    def status(self, owner: UUID, session: bytes) -> dict[str, str | bool | None]:
        with self.owned(owner) as connection:
            row = connection.execute(
                text("""
                SELECT c.status,c.expires_at,c.lease_until,c.client_binding,
                    EXISTS (SELECT 1 FROM app.indmoney_attempts a WHERE a.connection_id=c.id
                        AND a.session_verifier=:session AND a.stage='received'
                        AND a.expires_at>clock_timestamp()) AS can_complete,
                    clock_timestamp() AS now FROM app.indmoney_connections c WHERE owner_id=:owner
            """),
                dict(owner=owner, session=session),
            ).one_or_none()
            status = row.status if row else "disconnected"
            if row and (
                (row.lease_until and row.lease_until <= row.now)
                or row.client_binding != self.binding
            ):
                status = "reconnect_required"
            return dict(
                status=status,
                can_complete=bool(row and row.can_complete),
                expires_at=row.expires_at.isoformat() if row and row.expires_at else None,
                financial_access_enabled=False,
            )

    def rotate(self, owner: UUID, request: str) -> None:
        with self.owned(owner) as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM app.indmoney_connections WHERE owner_id=:owner FOR UPDATE"),
                    dict(owner=owner),
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return
            if row["lease"] is not None:
                raise ConnectorBusy()
            if row["sealed"] is not None:
                tokens = self._tokens(row)
                connection.execute(
                    text(
                        "UPDATE app.indmoney_connections SET sealed=:sealed WHERE owner_id=:owner"
                    ),
                    dict(
                        owner=owner,
                        sealed=self.keys.seal(
                            owner, row["id"], "tokens", row["revision"], self._token_bytes(tokens)
                        ),
                    ),
                )
            for attempt in connection.execute(
                text("SELECT * FROM app.indmoney_attempts WHERE owner_id=:owner"), dict(owner=owner)
            ).mappings():
                value = self._attempt(attempt)
                connection.execute(
                    text("UPDATE app.indmoney_attempts SET sealed=:sealed WHERE state_hash=:state"),
                    dict(
                        state=attempt["state_hash"],
                        sealed=self.keys.seal(
                            owner,
                            attempt["connection_id"],
                            "attempt",
                            attempt["revision"],
                            value.private_bytes(),
                        ),
                    ),
                )
            self.audit(connection, owner, "rotate", "success", request)
