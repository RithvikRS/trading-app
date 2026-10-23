import shutil

import pytest
from sqlalchemy import text

from trading_db import migrate
from trading_db.connections import engine_for

HEAD = "0002_workspace_ownership"


def test_fresh_head_and_disposable_downgrade_reupgrade(database):
    url, project = database
    migrate.apply(url(), project)
    assert migrate.revision(url(), project) == HEAD
    migrate.apply(url(), project, direction="downgrade", target="0001_private_schema")
    owner = engine_for(url(), migration=True)
    try:
        with owner.connect() as connection:
            assert (
                connection.execute(
                    text("""
                SELECT count(*) FROM pg_tables WHERE schemaname='app'
            """)
                ).scalar_one()
                == 0
            )
        migrate.apply(url(), project)
        assert migrate.revision(url(), project) == HEAD
        with owner.connect() as connection:
            assert (
                connection.execute(
                    text("""
                SELECT count(*) FROM pg_tables WHERE schemaname='app'
            """)
                ).scalar_one()
                == 3
            )
        migrate.apply(url(), project, direction="downgrade", target="base")
        assert migrate.revision(url(), project) == "base"
    finally:
        owner.dispose()


def test_upgrade_from_baseline_and_repeat_preserve_existing_data(database):
    url, project = database
    migrate.apply(url(), project, target="0001_private_schema")
    owner = engine_for(url(), migration=True)
    admin = engine_for(url("bootstrap"), migration=True)
    try:
        with owner.begin() as connection:
            connection.execute(text("CREATE TABLE app.migration_probe (id integer PRIMARY KEY)"))
            connection.execute(text("INSERT INTO app.migration_probe VALUES (1)"))
        migrate.apply(url(), project)
        with admin.begin() as connection:
            connection.execute(
                text("""
                INSERT INTO app.owners (id) VALUES ('10000000-0000-4000-8000-000000000001')
            """)
            )
            # Provisioning is disabled by default until an explicit administrative activation.
            assert (
                connection.execute(text("SELECT is_active FROM app.owners")).scalar_one() is False
            )
            connection.execute(
                text("""
                INSERT INTO app.workspace_preferences (owner_id)
                VALUES ('10000000-0000-4000-8000-000000000001')
            """)
            )
            original = connection.execute(text("SELECT * FROM app.workspace_preferences")).one()
        migrate.apply(url(), project)
        with admin.connect() as connection:
            assert (
                connection.execute(text("SELECT * FROM app.workspace_preferences")).one()
                == original
            )
            assert connection.execute(text("SELECT id FROM app.migration_probe")).scalar_one() == 1
        assert migrate.revision(url(), project) == HEAD
    finally:
        owner.dispose()
        admin.dispose()


@pytest.mark.parametrize("start", ["base", "0001_private_schema", HEAD])
def test_failure_after_ownership_revision_rolls_back_to_start(database, tmp_path, start):
    url, project = database
    if start != "base":
        migrate.apply(url(), project, target=start)
    directory = tmp_path / "migrations"
    shutil.copytree(migrate.MIGRATIONS, directory)
    (directory / "versions/0003_failure.py").write_text(
        'from alembic import op\nrevision = "0003_failure"\n'
        'down_revision = "0002_workspace_ownership"\n'
        "def upgrade():\n"
        '    op.execute("ALTER TABLE app.workspace_preferences ADD COLUMN failure integer")\n'
        '    raise RuntimeError("synthetic migration failure")\n'
        "def downgrade():\n    pass\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="synthetic migration failure"):
        migrate.apply(url(), project, directory=directory)
    assert migrate.revision(url(), project) == start
    admin = engine_for(url("bootstrap"), migration=True)
    try:
        with admin.connect() as connection:
            assert (
                connection.execute(
                    text("""
                SELECT count(*) FROM information_schema.columns
                WHERE table_schema='app' AND table_name='workspace_preferences'
                  AND column_name='failure'
            """)
                ).scalar_one()
                == 0
            )
            assert connection.execute(
                text("""
                SELECT count(*) FROM pg_tables WHERE schemaname='app'
            """)
            ).scalar_one() == (3 if start == HEAD else 0)
    finally:
        admin.dispose()
