import shutil

import pytest
from sqlalchemy import text

from trading_db import migrate
from trading_db.connections import engine_for

HEAD = "0004_browser_sessions"


def test_upgrade_and_disposable_downgrade_keep_identity_schema(database):
    url, project = database
    migrate.apply(url(), project, target="0003_auth_identity_lookup")
    migrate.apply(url(), project, target=HEAD)
    migrate.apply(url(), project, target=HEAD)
    assert migrate.revision(url(), project) == HEAD
    admin = engine_for(url("bootstrap"), migration=True)
    try:
        with admin.connect() as connection:
            rows = connection.execute(
                text("""
                SELECT relname, relrowsecurity, relforcerowsecurity, pg_get_userbyid(relowner)
                FROM pg_class WHERE relnamespace='app'::regnamespace AND relkind='r'
            """)
            ).all()
            assert len(rows) == 7
            assert all(row[1:] == (True, True, "trading_migrator") for row in rows)
        migrate.apply(url(), project, direction="downgrade", target="0003_auth_identity_lookup")
        with admin.connect() as connection:
            assert (
                connection.execute(text("SELECT to_regclass('app.auth_sessions')")).scalar_one()
                is None
            )
            assert connection.execute(
                text("SELECT to_regclass('app.owner_identities')")
            ).scalar_one()
        migrate.apply(url(), project, target=HEAD)
        assert migrate.revision(url(), project) == HEAD
    finally:
        admin.dispose()


@pytest.mark.parametrize("start", ["base", "0003_auth_identity_lookup", HEAD])
def test_failed_migration_rolls_back_security_tables_and_head(database, tmp_path, start):
    url, project = database
    if start != "base":
        migrate.apply(url(), project, target=start)
    directory = tmp_path / "migrations"
    shutil.copytree(migrate.MIGRATIONS, directory)
    (directory / "versions/0005_failure.py").write_text(
        'from alembic import op\nrevision="0005_failure"\n'
        'down_revision="0004_browser_sessions"\n'
        "def upgrade():\n"
        '    op.execute("ALTER TABLE app.security_events ADD COLUMN unexpected text")\n'
        '    raise RuntimeError("synthetic failure")\ndef downgrade():\n    pass\n',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="synthetic failure"):
        migrate.apply(url(), project, directory=directory, target="0005_failure")
    assert migrate.revision(url(), project) == start
    admin = engine_for(url("bootstrap"), migration=True)
    try:
        with admin.connect() as connection:
            assert bool(
                connection.execute(text("SELECT to_regclass('app.auth_sessions')")).scalar_one()
            ) == (start == HEAD)
            assert (
                connection.execute(
                    text("""
                SELECT count(*) FROM information_schema.columns WHERE table_schema='app'
                    AND table_name='security_events' AND column_name='unexpected'
            """)
                ).scalar_one()
                == 0
            )
    finally:
        admin.dispose()
