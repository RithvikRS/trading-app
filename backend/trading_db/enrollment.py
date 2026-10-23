"""Explicit local administrator enrollment; never called by ordinary authentication."""

import re
from uuid import UUID, uuid4

from sqlalchemy import URL, text

from trading_db.connections import DatabaseFailure, engine_for, verify_server
from trading_db.sessions import LOCK, event


def provision_owner(url: URL, project: str, issuer: str, subject: UUID) -> None:
    if (
        url.username != "trading_bootstrap"
        or not isinstance(subject, UUID)
        or not subject.int
        or not re.fullmatch(r"https://[a-z0-9]{20}\.supabase\.co/auth/v1", issuer)
    ):
        raise DatabaseFailure("Invalid administrative enrollment target.")
    engine = engine_for(url, migration=True)
    try:
        with engine.begin() as connection:
            verify_server(connection, str(url.database), project)
            # No upsert, implicit relinking, activation, or MFA reset for an existing identity.
            owner = uuid4()
            connection.execute(
                text("INSERT INTO app.owners (id, is_active) VALUES (:owner, true)"),
                {"owner": owner},
            )
            connection.execute(
                text("""
                INSERT INTO app.owner_identities (issuer, subject, owner_id)
                VALUES (:issuer, :subject, :owner)
            """),
                {"issuer": issuer, "subject": str(subject), "owner": owner},
            )
    except Exception:
        raise DatabaseFailure("Administrative enrollment failed; no mapping was changed.") from None
    finally:
        engine.dispose()


def revoke_owner(url: URL, project: str, issuer: str, subject: UUID) -> None:
    """Administrative local revocation, including when the provider or owner is unavailable."""
    if (
        url.username != "trading_bootstrap"
        or not isinstance(subject, UUID)
        or not subject.int
        or not re.fullmatch(r"https://[a-z0-9]{20}\.supabase\.co/auth/v1", issuer)
    ):
        raise DatabaseFailure("Invalid administrative revocation target.")
    engine = engine_for(url, migration=True)
    try:
        with engine.begin() as connection:
            verify_server(connection, str(url.database), project)
            connection.execute(text(LOCK))
            owner = connection.execute(
                text(
                    "SELECT owner_id FROM app.owner_identities "
                    "WHERE issuer=:issuer AND subject=:subject"
                ),
                {"issuer": issuer, "subject": str(subject)},
            ).scalar_one()
            connection.execute(
                text("""
                INSERT INTO app.auth_revocations (owner_id) VALUES (:owner)
                ON CONFLICT (owner_id) DO UPDATE SET revoked_before=clock_timestamp()
            """),
                {"owner": owner},
            )
            connection.execute(
                text("DELETE FROM app.auth_sessions WHERE owner_id=:owner"), {"owner": owner}
            )
            event(connection, "revoke_all", "success", uuid4().hex, owner)
    except Exception:
        raise DatabaseFailure(
            "Administrative revocation failed; no change was committed."
        ) from None
    finally:
        engine.dispose()
