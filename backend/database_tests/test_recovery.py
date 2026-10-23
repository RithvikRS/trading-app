"""Encrypted synthetic export restored into a separately bootstrapped PostgreSQL cluster."""

import json
import time
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from starlette.testclient import TestClient

from database_tests.test_preferences import environment as environment
from database_tests.test_preferences import login, sql
from tests.auth_support import ISSUER, SUBJECT
from tests.browser_support import BrowserProviderStub
from trading_api.application import create_app
from trading_auth.browser import BrowserAuth
from trading_auth.models import AuthenticationDenied
from trading_auth.session_models import verifier
from trading_db import migrate, recovery
from trading_db.connections import DatabaseFailure, engine_for
from trading_db.enrollment import provision_owner
from trading_db.local import ROOT, disposable, private_directory
from trading_db.sessions import SessionDatabase
from trading_db.workspace import PreferenceUpdate, WorkspaceDatabase


def signature(engine):
    return {
        "policies": sql(
            engine,
            "SELECT tablename, policyname, roles, cmd, qual, with_check FROM pg_policies "
            "WHERE schemaname='app' ORDER BY tablename,policyname",
        ),
        "roles": sql(
            engine,
            "SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles "
            "WHERE rolname LIKE 'trading_%' ORDER BY rolname",
        ),
        "grants": sql(
            engine,
            "SELECT table_name,grantee,privilege_type FROM information_schema.table_privileges "
            "WHERE table_schema='app' ORDER BY table_name,grantee,privilege_type",
        ),
    }


def test_encrypted_restore_preserves_records_and_isolation_but_not_sessions(environment, database):
    client, service, workspace, _, admin = environment
    source_url, source_project = database
    headers = login(client)
    assert (
        client.put(
            "/api/v1/preferences",
            headers=headers,
            json=dict(theme="dark", display_currency="USD", amount_masked=False, revision=0),
        ).status_code
        == 200
    )
    provision_owner(source_url("bootstrap"), source_project, ISSUER, uuid4())
    own = sql(
        admin,
        "SELECT owner_id FROM app.owner_identities WHERE subject=:subject",
        subject=str(SUBJECT),
    )[0][0]
    other = sql(admin, "SELECT id FROM app.owners WHERE id<>:own", own=own)[0][0]
    with workspace.transaction(other) as unit:
        unit.compare_preferences(
            PreferenceUpdate(theme="light", display_currency="INR", amount_masked=True, revision=0)
        )
    key = Fernet.generate_key()
    started = time.monotonic()
    encrypted = recovery.export_snapshot(source_url("bootstrap"), source_project, key)
    data = recovery.decode_snapshot(encrypted, key)
    assert "auth_sessions" not in data and "auth_admissions" not in data
    assert str(own).encode() not in encrypted
    old_started = datetime.now(UTC)
    baseline = signature(admin)
    with disposable() as target:
        migrate.apply(target.url("migrator"), target.project)
        restored_admin = engine_for(target.url("bootstrap"), migration=True)
        target_url = target.url("bootstrap")
        try:
            objects, keys = target.directory / "objects", target.directory / "keys"
            private_directory(objects)
            private_directory(keys)
            (objects / "foundation.fernet").write_bytes(encrypted)
            (keys / "recovery.key").write_bytes(key)
            del key
            recovered_key = (keys / "recovery.key").read_bytes()
            recovered_object = (objects / "foundation.fernet").read_bytes()
            for invalid, supplied_key in [
                (recovered_object, Fernet.generate_key()),
                (recovered_object[:-8] + b"tampered", recovered_key),
            ]:
                with pytest.raises(DatabaseFailure):
                    recovery.restore_snapshot(target_url, target.project, invalid, supplied_key)
                assert sql(restored_admin, "SELECT count(*) FROM app.owners")[0][0] == 0
            # Valid encryption, but a late database constraint failure must roll back earlier rows.
            broken = json.loads(Fernet(recovered_key).decrypt(recovered_object))
            broken["rows"]["workspace_preferences"][0]["theme"] = "invalid"
            with pytest.raises(DatabaseFailure, match="rolled back"):
                recovery.restore_snapshot(
                    target_url,
                    target.project,
                    Fernet(recovered_key).encrypt(json.dumps(broken).encode()),
                    recovered_key,
                )
            assert sql(restored_admin, "SELECT count(*) FROM app.owners")[0][0] == 0
            counts = recovery.restore_snapshot(
                target_url, target.project, recovered_object, recovered_key
            )
            assert (
                counts["owners"]
                == counts["workspace_preferences"]
                == counts["auth_revocations"]
                == 2
            )
            assert counts["auth_sessions"] == counts["auth_admissions"] == 0
            assert signature(restored_admin) == baseline
            restored_data = recovery.decode_snapshot(
                recovery.export_snapshot(target_url, target.project, recovered_key), recovered_key
            )
            for table in set(data) - {"auth_revocations"}:
                assert sorted(restored_data[table], key=str) == sorted(data[table], key=str)
            assert all(
                row[0] >= old_started
                for row in sql(restored_admin, "SELECT revoked_before FROM app.auth_revocations")
            )
            with pytest.raises(DatabaseFailure, match="must be empty"):
                recovery.restore_snapshot(
                    target_url, target.project, recovered_object, recovered_key
                )
            restored_workspace = WorkspaceDatabase(target.url("runtime"), target.project)
            restored_sessions = SessionDatabase(target.url("auth"), target.project)
            try:
                for owner, theme in [(own, "dark"), (other, "light")]:
                    with restored_workspace.transaction(owner) as unit:
                        assert unit.preference_snapshot().theme == theme
                        assert (
                            unit._connection.execute(
                                text(
                                    "SELECT count(*) FROM app.workspace_preferences "
                                    "WHERE owner_id<>:owner"
                                ),
                                {"owner": owner},
                            ).scalar_one()
                            == 0
                        )
                        assert (
                            unit._connection.execute(
                                text(
                                    "UPDATE app.workspace_preferences SET theme='dark' "
                                    "WHERE owner_id<>:owner"
                                ),
                                {"owner": owner},
                            ).rowcount
                            == 0
                        )
                with restored_workspace._engine.begin() as connection:
                    assert (
                        connection.execute(
                            text("SELECT count(*) FROM app.workspace_preferences")
                        ).scalar_one()
                        == 0
                    )
                with restored_workspace._engine.begin() as connection, pytest.raises(DBAPIError):
                    connection.execute(text("SELECT * FROM app.auth_sessions"))
                with restored_sessions._engine.begin() as connection, pytest.raises(DBAPIError):
                    connection.execute(text("SELECT * FROM app.workspace_preferences"))
                with pytest.raises(AuthenticationDenied):
                    restored_sessions.create(
                        verifier(client.cookies["trading_dev_session"]),
                        own,
                        ISSUER,
                        SUBJECT,
                        "login",
                        b"synthetic-encrypted-state",
                        old_started,
                        "a" * 32,
                        "login",
                    )
                restored_auth = BrowserAuth(
                    BrowserProviderStub().provider(), restored_sessions, service.vault
                )
                with TestClient(
                    create_app(browser=restored_auth, workspace=restored_workspace),
                    base_url="http://127.0.0.1:8000",
                ) as recovered_client:
                    recovered_client.cookies.update(client.cookies)
                    assert (
                        recovered_client.get("/api/v1/preferences", headers=headers).status_code
                        == 401
                    )
            finally:
                restored_workspace.close()
                restored_sessions.close()
            report = {
                "scope": "synthetic foundation records; separate PostgreSQL clusters",
                "encrypted_bytes": len(encrypted),
                "rows": counts,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "measured_at": datetime.now(UTC).isoformat(),
            }
            destination = ROOT / ".cache/operations"
            private_directory(destination)
            (destination / "recovery-report.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
        finally:
            restored_admin.dispose()
