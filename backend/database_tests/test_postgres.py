"""Keep the original 0001 baseline contract independent of later revisions."""

import shutil

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from trading_db import migrate
from trading_db.connections import DatabaseFailure, engine_for, require_disposable


def scalar(url, statement):
    engine = engine_for(url, migration=True)
    try:
        with engine.connect() as connection:
            return connection.execute(text(statement)).scalar_one()
    finally:
        engine.dispose()


def test_clean_upgrade_repeat_and_round_trip(database):
    url, project = database
    assert migrate.revision(url(), project) == "base"
    migrate.apply(url(), project, target="0001_private_schema")
    migrate.apply(url(), project, target="0001_private_schema")
    assert migrate.revision(url(), project) == "0001_private_schema"
    assert (
        scalar(url(), "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='app'")
        == "trading_migrator"
    )
    assert scalar(url(), "SELECT count(*) FROM pg_tables WHERE schemaname='app'") == 0
    migrate.apply(url(), project, direction="downgrade", target="base")
    assert migrate.revision(url(), project) == "base"
    assert scalar(url(), "SELECT count(*) FROM pg_namespace WHERE nspname='app'") == 0
    migrate.apply(url(), project, target="0001_private_schema")
    assert migrate.revision(url(), project) == "0001_private_schema"


@pytest.mark.parametrize("existing", [False, True])
def test_failed_revision_rolls_back_schema_and_version(database, tmp_path, existing):
    url, project = database
    if existing:
        migrate.apply(url(), project, target="0001_private_schema")
    directory = tmp_path / "migrations"
    (directory / "versions").mkdir(parents=True)
    shutil.copyfile(migrate.MIGRATIONS / "env.py", directory / "env.py")
    shutil.copyfile(
        migrate.MIGRATIONS / "versions/0001_private_schema.py",
        directory / "versions/0001_private_schema.py",
    )
    (directory / "versions/0002_failure.py").write_text(
        'from alembic import op\nrevision = "0002_failure"\n'
        'down_revision = "0001_private_schema"\n'
        "def upgrade():\n"
        '    op.execute("CREATE TABLE app.rollback_probe (id integer)")\n'
        '    raise RuntimeError("synthetic migration failure")\n'
        "def downgrade():\n    pass\n"
    )
    with pytest.raises(RuntimeError, match="synthetic migration failure"):
        migrate.apply(url(), project, directory=directory)
    assert migrate.revision(url(), project) == ("0001_private_schema" if existing else "base")
    assert scalar(url(), "SELECT to_regclass('app.rollback_probe') IS NULL")
    assert scalar(url(), "SELECT count(*) FROM pg_namespace WHERE nspname='app'") == int(existing)


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE app.denied (id integer)",
        "CREATE TABLE public.denied (id integer)",
        "CREATE TEMP TABLE denied (id integer)",
        "CREATE SCHEMA denied",
        "CREATE ROLE denied",
        "SET ROLE trading_migrator",
        "SET ROLE trading_bootstrap",
        "SET ROLE pg_read_all_data",
        "ALTER ROLE trading_runtime SUPERUSER",
        "ALTER TABLE app.permission_probe ADD COLUMN x integer",
        "DROP TABLE app.permission_probe",
        "TRUNCATE app.permission_probe",
        "SELECT * FROM app_meta.alembic_version",
        "DROP SCHEMA app",
        "CREATE DATABASE denied",
    ],
)
def test_runtime_cannot_administer_or_migrate_even_with_dml_grants(database, statement):
    url, project = database
    migrate.apply(url(), project, target="0001_private_schema")
    owner = engine_for(url(), migration=True)
    try:
        with owner.begin() as connection:
            connection.execute(text("CREATE TABLE app.permission_probe (id integer)"))
            connection.execute(
                text(
                    "GRANT SELECT, INSERT, UPDATE, DELETE "
                    "ON app.permission_probe TO trading_runtime"
                )
            )
    finally:
        owner.dispose()
    runtime = engine_for(url("runtime"))
    try:
        with runtime.connect() as connection:
            assert connection.execute(text("SELECT current_user")).scalar_one() == "trading_runtime"
            connection.rollback()
            # CREATE DATABASE requires autocommit; denial must be privilege-related.
            connection = connection.execution_options(isolation_level="AUTOCOMMIT")
            with pytest.raises(DBAPIError) as error:
                connection.execute(text(statement))
            assert error.value.orig.sqlstate == "42501"
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        runtime.dispose()
    assert migrate.revision(url(), project) == "0001_private_schema"


def test_runtime_role_defaults_and_future_objects_are_closed(database):
    url, project = database
    migrate.apply(url(), project, target="0001_private_schema")
    assert not scalar(
        url("runtime"),
        "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls "
        "FROM pg_roles WHERE rolname=current_user",
    )
    assert (
        scalar(
            url("runtime"),
            "SELECT count(*) FROM pg_auth_members "
            "WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user)",
        )
        == 0
    )
    assert not scalar(
        url("runtime"),
        "SELECT has_database_privilege(current_database(), 'CREATE') "
        "OR has_database_privilege(current_database(), 'TEMP')",
    )
    owner = engine_for(url(), migration=True)
    try:
        with owner.begin() as connection:
            connection.execute(text("CREATE TABLE app.future_data (id integer)"))
            connection.execute(
                text(
                    "CREATE FUNCTION app.private_function() RETURNS integer "
                    "LANGUAGE sql AS 'SELECT 1'"
                )
            )
    finally:
        owner.dispose()
    assert not scalar(url("runtime"), "SELECT has_table_privilege('app.future_data', 'SELECT')")
    assert not scalar(
        url("runtime"), "SELECT has_function_privilege('app.private_function()', 'EXECUTE')"
    )
    assert scalar(url("runtime"), "SHOW search_path") == "pg_catalog"
    assert scalar(url("runtime"), "SHOW statement_timeout") == "15s"


def test_database_authentication_requires_password_and_scram(database):
    url, _ = database
    engine = engine_for(url("runtime").set(password="incorrect-synthetic-password"))
    try:
        with pytest.raises(DBAPIError):
            with engine.connect():
                pytest.fail("Incorrect password unexpectedly authenticated")
    finally:
        engine.dispose()
    assert scalar(
        url("bootstrap"),
        "SELECT bool_and(auth_method='scram-sha-256') FROM pg_hba_file_rules WHERE error IS NULL",
    )
    assert scalar(
        url("bootstrap"),
        "SELECT bool_and(rolpassword LIKE 'SCRAM-SHA-256$%') FROM pg_authid WHERE rolcanlogin",
    )


def test_server_marker_prevents_wrong_cluster_reset(database):
    url, _ = database
    with pytest.raises(DatabaseFailure):
        require_disposable(url(), "trading-test-0000000000000000")


def test_migration_refuses_runtime_and_bootstrap_identities(database):
    url, project = database
    for role in ("runtime", "bootstrap"):
        with pytest.raises(DatabaseFailure):
            migrate.apply(url(role), project)
    assert migrate.revision(url(), project) == "base"


def test_downgrade_refuses_unexpected_objects_without_cascade(database):
    url, project = database
    migrate.apply(url(), project, target="0001_private_schema")
    engine = engine_for(url(), migration=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE app.keep_data (id integer)"))
        with pytest.raises(DBAPIError) as error:
            migrate.apply(url(), project, direction="downgrade", target="base")
        assert error.value.orig.sqlstate == "2BP01"
        assert scalar(url(), "SELECT to_regclass('app.keep_data') IS NOT NULL")
        assert migrate.revision(url(), project) == "0001_private_schema"
    finally:
        engine.dispose()


def test_competing_migration_times_out_without_changing_schema(database):
    url, project = database
    engine = engine_for(url(), migration=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(714039231)"))
            with pytest.raises(DBAPIError) as error:
                migrate.apply(url(), project, target="0001_private_schema")
            assert error.value.orig.sqlstate == "55P03"
            assert migrate.revision(url(), project) == "base"
        migrate.apply(url(), project, target="0001_private_schema")
        assert migrate.revision(url(), project) == "0001_private_schema"
    finally:
        engine.dispose()


def test_libpq_environment_cannot_redirect_local_connection(database, monkeypatch):
    url, project = database
    monkeypatch.setenv("PGHOSTADDR", "192.0.2.1")
    migrate.apply(url(), project, target="0001_private_schema")
    assert migrate.revision(url(), project) == "0001_private_schema"
