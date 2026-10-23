"""Pre-owner identity lookup with separate credentials and no workspace access."""

from uuid import UUID

from sqlalchemy import URL, text

from trading_auth.models import AuthenticationDenied, AuthenticationUnavailable, OwnerBinding
from trading_db.connections import DatabaseFailure, engine_for, verify_server


class IdentityDatabase:
    def __init__(self, url: URL, project: str) -> None:
        if url.username != "trading_auth":
            raise DatabaseFailure("Identity lookup requires its dedicated restricted identity.")
        self._engine, self._project = engine_for(url), project

    def close(self) -> None:
        self._engine.dispose()

    def _query(self, issuer: str, subject: UUID, owner: UUID | None) -> OwnerBinding | None:
        try:
            with self._engine.begin() as connection:
                verify_server(connection, str(self._engine.url.database), self._project)
                valid = connection.execute(
                    text("""
                    SELECT current_user='trading_auth' AND session_user='trading_auth'
                        AND NOT (rolsuper OR rolcreatedb OR rolcreaterole
                            OR rolreplication OR rolbypassrls)
                        AND NOT EXISTS (SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid)
                        AND NOT has_database_privilege(current_database(), 'CREATE')
                        AND NOT has_database_privilege(current_database(), 'TEMP')
                        AND NOT has_schema_privilege('app', 'CREATE')
                        AND NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspowner=pg_roles.oid)
                        AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relowner=pg_roles.oid)
                    FROM pg_roles WHERE rolname=current_user
                """)
                ).scalar_one()
                if not valid:
                    raise AuthenticationUnavailable()
                if owner is not None:
                    row = connection.execute(
                        text("""
                        UPDATE app.owner_identities SET mfa_enrolled=true
                        WHERE issuer=:issuer AND subject=:subject AND owner_id=:owner
                        RETURNING owner_id, mfa_enrolled
                    """),
                        {"issuer": issuer, "subject": str(subject), "owner": owner},
                    ).one_or_none()
                else:
                    row = connection.execute(
                        text("""
                        SELECT owner_id, mfa_enrolled FROM app.owner_identities
                        WHERE issuer=:issuer AND subject=:subject
                    """),
                        {"issuer": issuer, "subject": str(subject)},
                    ).one_or_none()
                return OwnerBinding(row.owner_id, row.mfa_enrolled) if row is not None else None
        except AuthenticationUnavailable:
            raise
        except Exception:
            raise AuthenticationUnavailable() from None

    def lookup(self, issuer: str, subject: UUID) -> OwnerBinding | None:
        return self._query(issuer, subject, None)

    def complete_enrollment(self, issuer: str, subject: UUID, owner_id: UUID) -> None:
        if self._query(issuer, subject, owner_id) is None:
            raise AuthenticationDenied()
