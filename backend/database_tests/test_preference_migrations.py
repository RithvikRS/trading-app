"""Revision migration preserves preferences and existing role boundaries."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from trading_db import migrate
from trading_db.connections import engine_for
from trading_db.enrollment import provision_owner
from trading_db.workspace import Preferences, WorkspaceDatabase

HEAD = "0005_preference_revisions"
PREVIOUS = "0004_browser_sessions"


def test_preference_upgrade_downgrade_and_reupgrade_preserve_values(database):
    url, project = database
    migrate.apply(url(), project, target=PREVIOUS)
    provision_owner(
        url("bootstrap"), project, "https://abcdefghijklmnopqrst.supabase.co/auth/v1", uuid4()
    )
    admin = engine_for(url("bootstrap"), migration=True)
    store = WorkspaceDatabase(url("runtime"), project)
    try:
        with admin.connect() as connection:
            owner = connection.execute(text("SELECT id FROM app.owners")).scalar_one()
        preferences = Preferences(theme="dark", display_currency="USD", amount_masked=False)
        with store.transaction(owner) as unit:
            unit.save_preferences(preferences)
        for _ in range(2):
            migrate.apply(url(), project)
            migrate.apply(url(), project)
            assert migrate.revision(url(), project) == HEAD
            with store.transaction(owner) as unit:
                assert unit.preference_snapshot().model_dump() == {
                    **preferences.model_dump(),
                    "revision": 1,
                }
                unit.save_preferences(preferences)
                assert unit.preference_snapshot().revision == 2
            with admin.connect() as connection:
                assert connection.execute(
                    text(
                        "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                        "WHERE oid='app.workspace_preferences'::regclass"
                    )
                ).scalar_one()
                assert not connection.execute(
                    text(
                        "SELECT has_column_privilege('trading_runtime',"
                        "'app.workspace_preferences','revision','UPDATE')"
                    )
                ).scalar_one()
                assert not connection.execute(
                    text(
                        "SELECT has_table_privilege('trading_auth',"
                        "'app.workspace_preferences','SELECT')"
                    )
                ).scalar_one()
            migrate.apply(url(), project, direction="downgrade", target=PREVIOUS)
            with store.transaction(owner) as unit:
                assert unit.get_preferences() == preferences
    finally:
        store.close()
        admin.dispose()


def test_failed_revision_upgrade_is_atomic(database, monkeypatch):
    url, project = database
    migrate.apply(url(), project, target=PREVIOUS)
    from alembic.operations import Operations

    original = Operations.execute

    def failure(self, statement, *args, **kwargs):
        result = original(self, statement, *args, **kwargs)
        if "ADD COLUMN revision" in str(statement):
            raise RuntimeError("synthetic upgrade failure")
        return result

    monkeypatch.setattr(Operations, "execute", failure)
    with pytest.raises(RuntimeError, match="synthetic upgrade failure"):
        migrate.apply(url(), project)
    assert migrate.revision(url(), project) == PREVIOUS
    admin = engine_for(url("bootstrap"), migration=True)
    try:
        with admin.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_schema='app' AND table_name='workspace_preferences' "
                        "AND column_name='revision'"
                    )
                ).scalar_one()
                == 0
            )
    finally:
        admin.dispose()
