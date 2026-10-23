import shutil
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from trading_auth.models import AuthenticationDenied, AuthenticationUnavailable
from trading_db import migrate
from trading_db.connections import DatabaseFailure, engine_for
from trading_db.enrollment import provision_owner
from trading_db.identities import IdentityDatabase
from trading_db.workspace import Preferences, WorkspaceDatabase

ISSUER = "https://abcdefghijklmnopqrst.supabase.co/auth/v1"
SUBJECT_A = UUID("20000000-0000-4000-8000-000000000001")
SUBJECT_B = UUID("20000000-0000-4000-8000-000000000002")
HEAD = "0003_auth_identity_lookup"


@pytest.fixture
def identities(database):
    url, project = database
    migrate.apply(url(), project)
    provision_owner(url("bootstrap"), project, ISSUER, SUBJECT_A)
    provision_owner(url("bootstrap"), project, ISSUER, SUBJECT_B)
    store = IdentityDatabase(url("auth"), project)
    try:
        yield store
    finally:
        store.close()


def test_exact_identity_lookup_cannot_link_by_email_and_initial_mfa_is_closed(identities):
    first = identities.lookup(ISSUER, SUBJECT_A)
    second = identities.lookup(ISSUER, SUBJECT_B)
    assert first.owner_id != second.owner_id
    assert not first.mfa_enrolled and not second.mfa_enrolled
    assert identities.lookup(ISSUER + "/", SUBJECT_A) is None
    assert identities.lookup(ISSUER.upper(), SUBJECT_A) is None
    assert identities.lookup(ISSUER, UUID(int=42)) is None
    identities.complete_enrollment(ISSUER, SUBJECT_A, first.owner_id)
    assert identities.lookup(ISSUER, SUBJECT_A).mfa_enrolled
    assert not identities.lookup(ISSUER, SUBJECT_B).mfa_enrolled


def test_wrong_owner_and_disabled_mapping_cannot_complete(identities, database):
    url, _ = database
    first, second = identities.lookup(ISSUER, SUBJECT_A), identities.lookup(ISSUER, SUBJECT_B)
    with pytest.raises(AuthenticationDenied):
        identities.complete_enrollment(ISSUER, SUBJECT_A, second.owner_id)
    admin = engine_for(url("bootstrap"), migration=True)
    try:
        with admin.begin() as connection:
            connection.execute(
                text("UPDATE app.owners SET is_active=false WHERE id=:id"), {"id": first.owner_id}
            )
        assert identities.lookup(ISSUER, SUBJECT_A) is None
        with pytest.raises(AuthenticationDenied):
            identities.complete_enrollment(ISSUER, SUBJECT_A, first.owner_id)
    finally:
        admin.dispose()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM app.workspace_preferences",
        "SELECT created_at FROM app.owners",
        "SELECT created_at FROM app.owner_identities",
        "SELECT * FROM app_meta.alembic_version",
        "UPDATE app.owners SET is_active=true",
        "DELETE FROM app.owner_identities",
        "UPDATE app.owner_identities SET subject='replacement'",
        "TRUNCATE app.owner_identities",
        "ALTER TABLE app.owner_identities DISABLE ROW LEVEL SECURITY",
        "SET ROLE trading_runtime",
        "SET ROLE trading_migrator",
        "CREATE TABLE app.unexpected (id integer)",
        "CREATE TEMP TABLE unexpected (id integer)",
        "INSERT INTO app.owner_identities (issuer, subject, owner_id) "
        "SELECT issuer, 'new', owner_id FROM app.owner_identities",
    ],
)
def test_identity_role_cannot_access_workspace_or_administer_owners(identities, sql):
    with identities._engine.begin() as connection:
        with pytest.raises(DBAPIError) as error:
            connection.execute(text(sql))
        assert error.value.orig.sqlstate == "42501"


def test_enrollment_marker_cannot_be_cleared_by_auth_role(identities):
    binding = identities.lookup(ISSUER, SUBJECT_A)
    identities.complete_enrollment(ISSUER, SUBJECT_A, binding.owner_id)
    with identities._engine.begin() as connection:
        with pytest.raises(DBAPIError) as error:
            connection.execute(text("UPDATE app.owner_identities SET mfa_enrolled=false"))
        assert error.value.orig.sqlstate == "42501"
    assert identities.lookup(ISSUER, SUBJECT_A).mfa_enrolled


def test_workspace_runtime_still_cannot_resolve_identity(identities, database):
    url, project = database
    first, second = identities.lookup(ISSUER, SUBJECT_A), identities.lookup(ISSUER, SUBJECT_B)
    runtime = WorkspaceDatabase(url("runtime"), project)
    try:
        with runtime.transaction(first.owner_id) as unit:
            unit.save_preferences(Preferences(theme="dark"))
        with runtime.transaction(second.owner_id) as unit:
            assert unit.get_preferences() is None
            with pytest.raises(DBAPIError) as error:
                unit._connection.execute(text("SELECT * FROM app.owner_identities"))
            assert error.value.orig.sqlstate == "42501"
    finally:
        runtime.close()


def test_provision_is_atomic_rejects_duplicates_and_never_resets_mfa(identities, database):
    url, project = database
    binding = identities.lookup(ISSUER, SUBJECT_A)
    identities.complete_enrollment(ISSUER, SUBJECT_A, binding.owner_id)
    with pytest.raises(DatabaseFailure):
        provision_owner(url("bootstrap"), project, ISSUER, SUBJECT_A)
    assert identities.lookup(ISSUER, SUBJECT_A).mfa_enrolled
    with identities._engine.connect() as connection:
        assert connection.execute(text("SELECT count(id) FROM app.owners")).scalar_one() == 2


@pytest.mark.parametrize("role", ["runtime", "migrator", "auth"])
def test_non_admin_cannot_provision(identities, database, role):
    url, project = database
    with pytest.raises(DatabaseFailure):
        provision_owner(url(role), project, ISSUER, SUBJECT_A)


def test_identity_privilege_drift_fails_closed(identities, database):
    url, _ = database
    admin = engine_for(url("bootstrap"), migration=True)
    try:
        with admin.begin() as connection:
            connection.execute(text("GRANT CREATE ON SCHEMA app TO trading_auth"))
        with pytest.raises(AuthenticationUnavailable):
            identities.lookup(ISSUER, SUBJECT_A)
    finally:
        with admin.begin() as connection:
            connection.execute(text("REVOKE CREATE ON SCHEMA app FROM trading_auth"))
        admin.dispose()


def test_head_upgrade_preserves_preferences_and_downgrade_revokes_auth_access(database):
    url, project = database
    migrate.apply(url(), project, target="0002_workspace_ownership")
    provision_owner(url("bootstrap"), project, ISSUER, SUBJECT_A)
    admin = engine_for(url("bootstrap"), migration=True)
    try:
        with admin.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO app.workspace_preferences (owner_id, theme) "
                    "SELECT id, 'dark' FROM app.owners"
                )
            )
        migrate.apply(url(), project)
        store = IdentityDatabase(url("auth"), project)
        try:
            original = store.lookup(ISSUER, SUBJECT_A)
            store.complete_enrollment(ISSUER, SUBJECT_A, original.owner_id)
            migrate.apply(url(), project)
            assert store.lookup(ISSUER, SUBJECT_A).mfa_enrolled
            with admin.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT theme FROM app.workspace_preferences")
                    ).scalar_one()
                    == "dark"
                )
            migrate.apply(url(), project, direction="downgrade", target="0002_workspace_ownership")
            with pytest.raises(AuthenticationUnavailable):
                store.lookup(ISSUER, SUBJECT_A)
            migrate.apply(url(), project)
            assert not store.lookup(ISSUER, SUBJECT_A).mfa_enrolled
            migrate.apply(url(), project, direction="downgrade", target="base")
        finally:
            store.close()
    finally:
        admin.dispose()


@pytest.mark.parametrize("start", ["base", "0002_workspace_ownership", HEAD])
def test_failed_later_migration_rolls_back_identity_changes(database, tmp_path, start):
    url, project = database
    if start != "base":
        migrate.apply(url(), project, target=start)
    directory = tmp_path / "migrations"
    shutil.copytree(migrate.MIGRATIONS, directory)
    (directory / "versions/0004_failure.py").write_text(
        'from alembic import op\nrevision="0004_failure"\n'
        'down_revision="0003_auth_identity_lookup"\n'
        "def upgrade():\n"
        '    op.execute("ALTER TABLE app.owner_identities ADD COLUMN unexpected text")\n'
        '    raise RuntimeError("synthetic failure")\ndef downgrade():\n    pass\n',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="synthetic failure"):
        migrate.apply(url(), project, directory=directory)
    assert migrate.revision(url(), project) == start
    admin = engine_for(url("bootstrap"), migration=True)
    try:
        with admin.connect() as connection:
            columns = (
                connection.execute(
                    text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema='app' AND table_name='owner_identities'
            """)
                )
                .scalars()
                .all()
            )
            assert "unexpected" not in columns
            assert ("mfa_enrolled" in columns) == (start == HEAD)
            assert connection.execute(
                text("""
                SELECT count(*) FROM pg_policies
                WHERE schemaname='app' AND policyname LIKE 'auth_%'
            """)
            ).scalar_one() == (3 if start == HEAD else 0)
    finally:
        admin.dispose()
