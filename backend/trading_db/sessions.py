"""Short database transactions; provider I/O never runs inside a registry transaction."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from trading_auth.models import AuthenticationDenied, AuthenticationLimited
from trading_auth.session_models import Event, Outcome, SessionRow, Stage
from trading_connectors.indmoney_models import (
    ConnectorBusy,
    ConnectorRejected,
    ConnectorUnavailable,
)
from trading_db.identities import IdentityDatabase

# Serializes small registry mutations, including revocation versus in-flight completion.
# This lock is transaction-scoped and is never held during network/provider work.
LOCK = "SELECT pg_advisory_xact_lock(714039232)"
ACTIVE = """
    EXISTS (SELECT 1 FROM app.owner_identities i JOIN app.owners o ON o.id=i.owner_id
        WHERE i.issuer=s.issuer AND i.subject=s.subject AND i.owner_id=s.owner_id AND o.is_active)
"""


def event(
    connection: Connection,
    name: Event,
    outcome: Outcome,
    request: str,
    owner: UUID | None = None,
    reference: UUID | None = None,
) -> None:
    connection.execute(
        text("""
        INSERT INTO app.security_events (id, event, outcome, request_id, actor, session_reference)
        VALUES (:id, :event, :outcome, :request, :actor, :reference)
    """),
        dict(
            id=uuid4(),
            event=name,
            outcome=outcome,
            request=request,
            actor=owner,
            reference=reference,
        ),
    )


class SessionDatabase(IdentityDatabase):
    expected_errors = IdentityDatabase.expected_errors + (
        ConnectorRejected,
        ConnectorUnavailable,
        ConnectorBusy,
    )

    @contextmanager
    def workspace_guard(self, key: bytes, owner: UUID) -> Iterator[Callable[[], None]]:
        # Share the revocation/renewal lock only during short local SQL work.
        # Provider I/O has already completed. Runtime retains no access to this registry.
        with self._transaction() as connection:
            connection.execute(text(LOCK))

            def validate() -> None:
                row = connection.execute(
                    text(f"""
                        SELECT s.lease FROM app.auth_sessions s
                        WHERE verifier=:key AND owner_id=:owner AND stage='active'
                            AND expires_at>clock_timestamp() AND idle_until>clock_timestamp()
                            AND {ACTIVE}
                    """),
                    {"key": key, "owner": owner},
                ).one_or_none()
                if row is None:
                    raise AuthenticationDenied()
                if row.lease is not None:
                    raise AuthenticationLimited()

            validate()
            yield validate

    def audit(
        self,
        name: Event,
        outcome: Outcome,
        request: str,
        owner: UUID | None = None,
        reference: UUID | None = None,
    ) -> None:
        with self._transaction() as connection:
            event(connection, name, outcome, request, owner, reference)

    def admit(self, key: bytes) -> datetime:
        limited = False
        with self._transaction() as connection:
            connection.execute(text(LOCK))
            connection.execute(
                text(
                    "DELETE FROM app.auth_admissions WHERE created_at <= clock_timestamp() "
                    "- interval '5 minutes'"
                )
            )
            row = connection.execute(
                text("""
                SELECT count(*) AS total, count(*) FILTER (WHERE key=:key) AS individual
                FROM app.auth_admissions
            """),
                {"key": key},
            ).one()
            limited = row.total >= 30 or row.individual >= 5
            now = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
            if not limited:
                connection.execute(
                    text("INSERT INTO app.auth_admissions (key) VALUES (:key)"), {"key": key}
                )
            # Expired ciphertext is removed on admitted traffic, without touching event history.
            connection.execute(
                text("""
                DELETE FROM app.auth_sessions WHERE expires_at <= clock_timestamp()
                    OR idle_until <= clock_timestamp()
            """)
            )
        if limited:
            raise AuthenticationLimited()
        return now  # type: ignore[no-any-return]

    def create(
        self,
        key: bytes,
        owner: UUID,
        issuer: str,
        subject: UUID,
        stage: Stage,
        sealed: bytes,
        started: datetime,
        request: str,
        name: Event,
    ) -> None:
        with self._transaction() as connection:
            connection.execute(text(LOCK))
            row = connection.execute(
                text("""
                INSERT INTO app.auth_sessions
                    (verifier, reference, owner_id, issuer, subject, stage, sealed,
                     expires_at, idle_until)
                SELECT :key, :reference, :owner, :issuer, :subject, :stage, :sealed,
                    :started + interval '5 minutes', :started + interval '5 minutes'
                WHERE :started > clock_timestamp() - interval '5 minutes'
                    AND EXISTS (SELECT 1 FROM app.owner_identities
                        WHERE issuer=:issuer AND subject=:subject AND owner_id=:owner)
                    AND NOT EXISTS (SELECT 1 FROM app.auth_revocations
                        WHERE owner_id=:owner AND revoked_before >= :started)
                RETURNING reference
            """),
                dict(
                    key=key,
                    reference=uuid4(),
                    owner=owner,
                    issuer=issuer,
                    subject=str(subject),
                    stage=stage,
                    sealed=sealed,
                    started=started,
                ),
            ).one_or_none()
            if row is None:
                raise AuthenticationDenied()
            event(connection, name, "success", request, owner, row.reference)

    def claim(
        self,
        key: bytes,
        stages: tuple[Stage, ...],
        request: str,
        *,
        interrupt: bool = False,
    ) -> SessionRow:
        result = None
        busy = False
        with self._transaction() as connection:
            connection.execute(text(LOCK))
            row = connection.execute(
                text(f"""
                SELECT s.*, clock_timestamp() AS now, {ACTIVE} AS valid
                FROM app.auth_sessions s WHERE verifier=:key FOR UPDATE
            """),
                {"key": key},
            ).one_or_none()
            if row is not None:
                if (
                    not row.valid
                    or row.expires_at <= row.now
                    or row.idle_until <= row.now
                    or (row.lease is not None and row.lease_until <= row.now)
                ):
                    connection.execute(
                        text("DELETE FROM app.auth_sessions WHERE verifier=:key"), {"key": key}
                    )
                    event(connection, "expiry", "denied", request, row.owner_id, row.reference)
                elif row.stage in stages:
                    if row.lease is not None and not interrupt:
                        busy = True
                    else:
                        lease = uuid4()
                        connection.execute(
                            text("""
                            UPDATE app.auth_sessions SET lease=:lease,
                                lease_until=clock_timestamp() + interval '90 seconds'
                            WHERE verifier=:key
                        """),
                            dict(lease=lease, key=key),
                        )
                        result = SessionRow(
                            key,
                            row.reference,
                            row.owner_id,
                            row.stage,
                            bytes(row.sealed),
                            row.created_at,
                            row.expires_at,
                            row.idle_until,
                            lease,
                        )
        if busy:
            raise AuthenticationLimited()
        if result is None:
            raise AuthenticationDenied()
        return result

    def finish(
        self,
        row: SessionRow,
        key: bytes,
        sealed: bytes,
        stage: Stage,
        request: str,
        *,
        activity: bool = False,
        name: Event | None = None,
        revoke_others: bool = False,
    ) -> None:
        with self._transaction() as connection:
            connection.execute(text(LOCK))
            changed = connection.execute(
                text(f"""
                UPDATE app.auth_sessions s SET verifier=:newkey, sealed=:sealed, stage=:stage,
                    lease=NULL, lease_until=NULL,
                    created_at=CASE WHEN :activate THEN statement_timestamp() ELSE created_at END,
                    expires_at=CASE WHEN :activate THEN statement_timestamp() + interval '8 hours'
                        ELSE expires_at END,
                    idle_until=CASE WHEN :activate OR :activity
                        THEN clock_timestamp() + interval '15 minutes' ELSE idle_until END
                WHERE verifier=:key AND lease=:lease AND lease_until > clock_timestamp()
                    AND expires_at > clock_timestamp() AND idle_until > clock_timestamp()
                    AND {ACTIVE}
                RETURNING reference
            """),
                dict(
                    key=row.verifier,
                    lease=row.lease,
                    newkey=key,
                    sealed=sealed,
                    stage=stage,
                    activate=row.stage == "login" and stage == "active",
                    activity=activity,
                ),
            ).one_or_none()
            if changed is None:
                raise AuthenticationDenied()
            if revoke_others:
                connection.execute(
                    text("""
                    INSERT INTO app.auth_revocations (owner_id) VALUES (:owner)
                    ON CONFLICT (owner_id) DO UPDATE SET revoked_before=clock_timestamp()
                """),
                    {"owner": row.owner},
                )
                connection.execute(
                    text("DELETE FROM app.auth_sessions WHERE owner_id=:owner AND verifier<>:key"),
                    dict(owner=row.owner, key=key),
                )
            if name is not None:
                event(connection, name, "success", request, row.owner, row.reference)

    def revoke(
        self,
        key: bytes,
        request: str,
        *,
        all_sessions: bool = False,
        name: Event = "logout",
        outcome: Outcome = "success",
        lease: UUID | None = None,
    ) -> None:
        with self._transaction() as connection:
            connection.execute(text(LOCK))
            row = connection.execute(
                text(
                    f"SELECT s.*, clock_timestamp() AS now, {ACTIVE} AS valid "
                    "FROM app.auth_sessions s WHERE verifier=:key"
                ),
                {"key": key},
            ).one_or_none()
            if row is None:
                if lease is not None:
                    raise AuthenticationDenied()
                return
            if lease is not None and (
                row.lease != lease
                or not row.valid
                or row.lease_until <= row.now
                or row.expires_at <= row.now
                or row.idle_until <= row.now
            ):
                raise AuthenticationDenied()
            if all_sessions:
                connection.execute(
                    text("""
                    INSERT INTO app.auth_revocations (owner_id) VALUES (:owner)
                    ON CONFLICT (owner_id) DO UPDATE SET revoked_before=clock_timestamp()
                """),
                    {"owner": row.owner_id},
                )
                connection.execute(
                    text("DELETE FROM app.auth_sessions WHERE owner_id=:owner"),
                    {"owner": row.owner_id},
                )
            else:
                connection.execute(
                    text("DELETE FROM app.auth_sessions WHERE verifier=:key"), {"key": key}
                )
            event(connection, name, outcome, request, row.owner_id, row.reference)
