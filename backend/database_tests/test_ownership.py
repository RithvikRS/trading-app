"""Real restricted-role tests; all identities are injected only by these fixtures."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from trading_db import migrate
from trading_db.connections import engine_for
from trading_db.workspace import OwnerAccessDenied, Preferences, WorkspaceDatabase

OWNER_A = UUID("10000000-0000-4000-8000-000000000001")
OWNER_B = UUID("10000000-0000-4000-8000-000000000002")
DISABLED = UUID("10000000-0000-4000-8000-000000000003")
UNKNOWN = UUID("10000000-0000-4000-8000-000000000004")


@pytest.fixture
def workspace(database):
    url, project = database
    migrate.apply(url(), project)
    admin = engine_for(url("bootstrap"), migration=True)
    with admin.begin() as connection:
        for owner, active in ((OWNER_A, True), (OWNER_B, True), (DISABLED, False)):
            connection.execute(
                text("INSERT INTO app.owners (id, is_active) VALUES (:id, :active)"),
                {"id": owner, "active": active},
            )
            connection.execute(
                text("""
                INSERT INTO app.owner_identities (issuer, subject, owner_id)
                VALUES ('https://identity.example.invalid', :subject, :owner)
            """),
                {"subject": str(owner), "owner": owner},
            )
            connection.execute(
                text("INSERT INTO app.workspace_preferences (owner_id) VALUES (:id)"), {"id": owner}
            )
    store = WorkspaceDatabase(url("runtime"), project)
    try:
        yield store, admin
    finally:
        store.close()
        admin.dispose()


def set_owner(connection, owner):
    connection.execute(text("SELECT set_config('app.owner_id', :id, true)"), {"id": str(owner)})


def visible(connection):
    return (
        connection.execute(text("SELECT owner_id FROM app.workspace_preferences")).scalars().all()
    )


def assert_empty_context(store, pid=None):
    with store._engine.connect() as connection:
        if pid is not None:
            assert connection.execute(text("SELECT pg_backend_pid()")).scalar_one() == pid
        assert connection.execute(text("SELECT app.current_owner_id()")).scalar_one() is None
        assert visible(connection) == []


def test_owner_repository_reads_and_writes_are_separate(workspace):
    store, _ = workspace
    for owner, preferences in (
        (OWNER_A, Preferences(theme="dark", display_currency="USD")),
        (OWNER_B, Preferences(amount_masked=False)),
    ):
        with store.transaction(owner) as unit:
            assert unit.get_preferences() == Preferences()
            unit.save_preferences(preferences)
    with store.transaction(OWNER_A) as unit:
        assert unit.get_preferences() == Preferences(theme="dark", display_currency="USD")
    with store.transaction(OWNER_B) as unit:
        assert unit.get_preferences() == Preferences(amount_masked=False)


@pytest.mark.parametrize("owner", [OWNER_A, OWNER_B])
def test_direct_unfiltered_queries_are_scoped_by_rls(workspace, owner):
    store, _ = workspace
    with store._engine.begin() as connection:
        set_owner(connection, owner)
        assert visible(connection) == [owner]
        assert connection.execute(text("SELECT id FROM app.owners")).scalars().all() == [owner]
        changed = (
            connection.execute(
                text("""
            UPDATE app.workspace_preferences SET theme='dark' RETURNING owner_id
        """)
            )
            .scalars()
            .all()
        )
        assert changed == [owner]
    assert_empty_context(store)


@pytest.mark.parametrize(
    "context", [None, "", "invalid", "' OR true --", "{}", "1" * 1000, str(UNKNOWN), str(DISABLED)]
)
def test_missing_invalid_unknown_and_disabled_context_denies_raw_access(workspace, context):
    store, _ = workspace
    with store._engine.begin() as connection:
        if context is not None:
            set_owner(connection, context)
        assert visible(connection) == []
        assert connection.execute(text("SELECT id FROM app.owners")).all() == []
        assert (
            connection.execute(text("UPDATE app.workspace_preferences SET theme='dark'")).rowcount
            == 0
        )
        with pytest.raises(DBAPIError) as error:
            connection.execute(
                text("INSERT INTO app.workspace_preferences (owner_id) VALUES (:id)"),
                {"id": OWNER_A},
            )
        assert error.value.orig.sqlstate == "42501"


@pytest.mark.parametrize("owner", [UNKNOWN, DISABLED])
def test_repository_rejects_unknown_or_disabled_owner(workspace, owner):
    store, _ = workspace
    with pytest.raises(OwnerAccessDenied, match="Workspace access denied"):
        with store.transaction(owner):
            pytest.fail("Unexpected workspace access")
    assert_empty_context(store)


def test_cross_owner_read_update_and_insert_are_denied(workspace):
    store, _ = workspace
    with store._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        assert (
            connection.execute(
                text("SELECT * FROM app.workspace_preferences WHERE owner_id=:id"), {"id": OWNER_B}
            ).all()
            == []
        )
        assert (
            connection.execute(
                text("UPDATE app.workspace_preferences SET theme='dark' WHERE owner_id=:id"),
                {"id": OWNER_B},
            ).rowcount
            == 0
        )
        with pytest.raises(DBAPIError) as error:
            connection.execute(
                text("""
                INSERT INTO app.workspace_preferences (owner_id, theme) VALUES (:id, 'dark')
                ON CONFLICT (owner_id) DO UPDATE SET theme=excluded.theme
            """),
                {"id": OWNER_B},
            )
        assert error.value.orig.sqlstate == "42501"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE app.workspace_preferences SET owner_id=:other WHERE owner_id=:self",
        "DELETE FROM app.workspace_preferences WHERE owner_id=:other",
        "TRUNCATE app.workspace_preferences",
        "ALTER TABLE app.workspace_preferences DISABLE ROW LEVEL SECURITY",
        "ALTER TABLE app.workspace_preferences NO FORCE ROW LEVEL SECURITY",
        "SELECT * FROM app.owner_identities",
        "INSERT INTO app.owners (id) VALUES (:other)",
        "UPDATE app.owners SET is_active=true WHERE id=:other",
        "DELETE FROM app.owners WHERE id=:other",
        "UPDATE app.owner_identities SET owner_id=:self WHERE owner_id=:other",
        "SET ROLE trading_migrator",
    ],
)
def test_runtime_grants_block_owner_mutation_provisioning_and_policy_bypass(workspace, statement):
    store, _ = workspace
    with store._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        with pytest.raises(DBAPIError) as error:
            connection.execute(text(statement), {"self": OWNER_A, "other": OWNER_B})
        assert error.value.orig.sqlstate == "42501"


def test_with_check_and_delete_policy_still_hold_if_column_grants_expand(workspace):
    store, admin = workspace
    # Test-only grants distinguish row-policy enforcement from the normal narrower ACLs.
    with admin.begin() as connection:
        connection.execute(
            text("GRANT UPDATE (owner_id), DELETE ON app.workspace_preferences TO trading_runtime")
        )
        connection.execute(
            text("DELETE FROM app.workspace_preferences WHERE owner_id=:id"), {"id": OWNER_B}
        )
    with store._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        with pytest.raises(DBAPIError) as error:
            connection.execute(
                text("UPDATE app.workspace_preferences SET owner_id=:other WHERE owner_id=:self"),
                {"self": OWNER_A, "other": OWNER_B},
            )
        assert error.value.orig.sqlstate == "42501"
    with store._engine.begin() as connection:
        set_owner(connection, OWNER_B)
        assert (
            connection.execute(
                text("DELETE FROM app.workspace_preferences WHERE owner_id=:id"), {"id": OWNER_A}
            ).rowcount
            == 0
        )
    with admin.begin() as connection:
        connection.execute(
            text(
                "REVOKE UPDATE (owner_id), DELETE ON app.workspace_preferences FROM trading_runtime"
            )
        )


def test_disabled_owner_loses_access_on_next_statement(workspace):
    store, admin = workspace
    with store.transaction(OWNER_A) as unit:
        assert unit.get_preferences() is not None
        with admin.begin() as connection:
            connection.execute(
                text("UPDATE app.owners SET is_active=false WHERE id=:id"), {"id": OWNER_A}
            )
        assert unit.get_preferences() is None
        with pytest.raises(DBAPIError) as error:
            unit.save_preferences(Preferences(theme="dark"))
        assert error.value.orig.sqlstate == "42501"
    with pytest.raises(OwnerAccessDenied):
        with store.transaction(OWNER_A):
            pytest.fail("Disabled owner retained access")


@pytest.mark.parametrize("failure", [None, ValueError, asyncio.CancelledError])
def test_same_physical_connection_clears_context_after_success_failure_or_cancel(
    workspace, failure
):
    store, _ = workspace

    def operation():
        nonlocal pid
        with store.transaction(OWNER_A) as unit:
            pid = unit._connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
            unit.save_preferences(Preferences(theme="dark"))
            if failure:
                raise failure()

    pid = None
    if failure:
        with pytest.raises(failure):
            operation()
    else:
        operation()
    assert_empty_context(store, pid)
    with store.transaction(OWNER_B) as unit:
        assert unit.get_preferences() == Preferences()
        assert unit._connection.execute(text("SELECT pg_backend_pid()")).scalar_one() == pid
    with store.transaction(OWNER_A) as unit:
        assert unit.get_preferences() == Preferences(theme="light" if failure else "dark")


def test_session_level_poison_is_scrubbed_before_pool_reuse(workspace):
    store, _ = workspace
    with store._engine.begin() as connection:
        pid = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
        connection.execute(
            text("SELECT set_config('app.owner_id', :id, false)"), {"id": str(OWNER_A)}
        )
        assert visible(connection) == [OWNER_A]
    assert_empty_context(store, pid)


def test_failed_sql_rolls_back_writes_and_clears_context(workspace):
    store, _ = workspace
    with pytest.raises(DBAPIError):
        with store.transaction(OWNER_A) as unit:
            pid = unit._connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
            unit.save_preferences(Preferences(theme="dark"))
            unit._connection.execute(text("SELECT 1 / 0"))
    assert_empty_context(store, pid)
    with store.transaction(OWNER_A) as unit:
        assert unit.get_preferences() == Preferences()


def test_uncommitted_raw_writes_are_not_committed_by_pool_reset(workspace):
    store, _ = workspace
    with store._engine.connect() as connection:
        set_owner(connection, OWNER_A)
        connection.execute(text("UPDATE app.workspace_preferences SET theme='dark'"))
    with store.transaction(OWNER_A) as unit:
        assert unit.get_preferences() == Preferences()


def test_database_cancellation_rolls_back_and_cleans_reused_connection(workspace):
    store, admin = workspace
    ready = Event()
    release = Event()
    pids = []

    def query():
        with store.transaction(OWNER_A) as unit:
            unit.save_preferences(Preferences(theme="dark"))
            pids.append(unit._connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            assert release.wait(5)
            unit._connection.execute(text("SELECT pg_sleep(10)"))

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(query)
        assert ready.wait(5)
        release.set()
        # The same transaction remains active between the signal and pg_sleep;
        # cancellation during either the query or the wait is a failed transaction.
        with admin.connect() as connection:
            import time

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                active = connection.execute(
                    text("""
                    SELECT wait_event='PgSleep' FROM pg_stat_activity WHERE pid=:pid
                """),
                    {"pid": pids[0]},
                ).scalar_one()
                connection.rollback()
                if active:
                    assert connection.execute(
                        text("SELECT pg_cancel_backend(:pid)"), {"pid": pids[0]}
                    ).scalar_one()
                    break
                time.sleep(0.01)
            else:
                pytest.fail("Database query did not enter the cancellable wait")
        with pytest.raises(DBAPIError) as error:
            future.result(timeout=5)
        assert error.value.orig.sqlstate == "57014"
    assert_empty_context(store, pids[0])
    with store.transaction(OWNER_A) as unit:
        assert unit.get_preferences() == Preferences()


def test_concurrent_owners_use_distinct_connections_without_context_leak(workspace):
    store, _ = workspace
    barrier = Barrier(2)

    def query(owner):
        with store.transaction(owner) as unit:
            barrier.wait(timeout=5)
            assert visible(unit._connection) == [owner]
            return unit._connection.execute(text("SELECT pg_backend_pid()")).scalar_one()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = [executor.submit(query, owner) for owner in (OWNER_A, OWNER_B)]
        assert first.result(timeout=10) != second.result(timeout=10)
    # Hold both pool checkouts to inspect every reused physical connection.
    with store._engine.connect() as first, store._engine.connect() as second:
        assert visible(first) == visible(second) == []


def test_row_security_off_cannot_bypass_policies(workspace):
    store, _ = workspace
    with store._engine.begin() as connection:
        connection.execute(text("SET LOCAL row_security=off"))
        with pytest.raises(DBAPIError) as error:
            visible(connection)
        assert error.value.orig.sqlstate == "42501"


def test_table_owner_is_subject_to_forced_row_security(database, workspace):
    url, _ = database
    owner = engine_for(url(), migration=True)
    try:
        with owner.begin() as connection:
            set_owner(connection, OWNER_A)
            assert visible(connection) == []
            with pytest.raises(DBAPIError) as error:
                connection.execute(
                    text("INSERT INTO app.owners (id) VALUES (:id)"), {"id": UNKNOWN}
                )
            assert error.value.orig.sqlstate == "42501"
    finally:
        owner.dispose()


def test_schema_constraints_identity_uniqueness_and_closed_default_grants(workspace):
    _, admin = workspace
    with admin.connect() as connection:
        tables = connection.execute(
            text("""
            SELECT relname, relrowsecurity, relforcerowsecurity, pg_get_userbyid(relowner)
            FROM pg_class JOIN pg_namespace ON pg_namespace.oid=relnamespace
            WHERE nspname='app' AND relkind='r' ORDER BY relname
        """)
        ).all()
        assert tables == [
            (name, True, True, "trading_migrator")
            for name in ("owner_identities", "owners", "workspace_preferences")
        ]
        assert (
            connection.execute(
                text("""
            SELECT count(*) FROM pg_proc JOIN pg_namespace ON pg_namespace.oid=pronamespace
            WHERE nspname='app' AND prosecdef
        """)
            ).scalar_one()
            == 0
        )
        connection.rollback()
        invalid = [
            (
                "INSERT INTO app.owner_identities (issuer, subject, owner_id) VALUES "
                "('https://identity.example.invalid', :subject, :id)",
                "23505",
            ),
            (
                "INSERT INTO app.owner_identities (issuer, subject, owner_id) "
                "VALUES ('', 's', :id)",
                "23514",
            ),
            (
                "INSERT INTO app.owner_identities (issuer, subject, owner_id) VALUES "
                "('https://another.example.invalid', 's', :unknown)",
                "23503",
            ),
            (
                "INSERT INTO app.owner_identities (issuer, subject, owner_id) VALUES "
                "('https://another.example.invalid', repeat('s', 257), :id)",
                "23514",
            ),
            (
                "INSERT INTO app.owners (id) VALUES ('00000000-0000-0000-0000-000000000000')",
                "23514",
            ),
            (
                "UPDATE app.workspace_preferences SET display_currency='EUR' WHERE owner_id=:id",
                "23514",
            ),
            ("UPDATE app.workspace_preferences SET theme='invalid' WHERE owner_id=:id", "23514"),
            ("UPDATE app.workspace_preferences SET amount_masked=NULL WHERE owner_id=:id", "23502"),
        ]
        for sql, code in invalid:
            with pytest.raises(DBAPIError) as error:
                connection.execute(
                    text(sql), {"id": OWNER_B, "subject": str(OWNER_A), "unknown": UNKNOWN}
                )
            assert error.value.orig.sqlstate == code
            connection.rollback()
        # A subject belongs to an exact issuer namespace, never an email-based shortcut.
        connection.execute(
            text("""
            INSERT INTO app.owner_identities (issuer, subject, owner_id)
            VALUES ('https://another.example.invalid', :subject, :id)
        """),
            {"subject": str(OWNER_A), "id": OWNER_B},
        )
        connection.commit()


def test_runtime_cannot_write_timestamps_and_database_stamps_updates(workspace):
    store, admin = workspace
    with admin.connect() as connection:
        created, updated = connection.execute(
            text("""
            SELECT created_at, updated_at FROM app.workspace_preferences WHERE owner_id=:id
        """),
            {"id": OWNER_A},
        ).one()
    assert created.tzinfo is not None
    with store.transaction(OWNER_A) as unit:
        unit.save_preferences(Preferences(theme="dark"))
    with admin.connect() as connection:
        later = connection.execute(
            text("""
            SELECT created_at, updated_at FROM app.workspace_preferences WHERE owner_id=:id
        """),
            {"id": OWNER_A},
        ).one()
    assert later.created_at == created and later.updated_at >= updated
    with store._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        with pytest.raises(DBAPIError) as error:
            connection.execute(text("UPDATE app.workspace_preferences SET updated_at='2000-01-01'"))
        assert error.value.orig.sqlstate == "42501"


def test_finished_unit_cannot_reenter_or_implicitly_open_a_transaction(workspace):
    store, _ = workspace
    with store.transaction(OWNER_A) as unit:
        assert unit.get_preferences() is not None
    with pytest.raises(ValueError, match="transaction has ended"):
        unit.get_preferences()
    with pytest.raises(ValueError, match="transaction has ended"):
        unit.save_preferences(Preferences())


def test_runtime_privilege_drift_is_rejected_before_workspace_access(workspace):
    store, admin = workspace
    with admin.begin() as connection:
        connection.execute(text("GRANT CREATE ON SCHEMA app TO trading_runtime"))
    try:
        with pytest.raises(ValueError, match="unexpected elevated privileges"):
            with store.transaction(OWNER_A):
                pytest.fail("Privilege drift was accepted")
    finally:
        with admin.begin() as connection:
            connection.execute(text("REVOKE CREATE ON SCHEMA app FROM trading_runtime"))


def test_cancelled_python_task_unwinds_transaction_before_connection_reuse(workspace):
    store, _ = workspace
    pid = None

    async def scenario():
        ready = asyncio.Event()

        async def operation():
            nonlocal pid
            with store.transaction(OWNER_A) as unit:
                unit.save_preferences(Preferences(theme="dark"))
                pid = unit._connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
                ready.set()
                await asyncio.Future()

        task = asyncio.create_task(operation())
        await asyncio.wait_for(ready.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert_empty_context(store, pid)
    with store.transaction(OWNER_A) as unit:
        assert unit.get_preferences() == Preferences()


def test_lost_connection_is_discarded_and_new_connection_has_no_identity(workspace):
    store, admin = workspace
    with pytest.raises(DBAPIError):
        with store.transaction(OWNER_A) as unit:
            pid = unit._connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
            unit.save_preferences(Preferences(theme="dark"))
            with admin.connect() as connection:
                assert connection.execute(
                    text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}
                ).scalar_one()
            unit.get_preferences()
    with store._engine.connect() as connection:
        assert connection.execute(text("SELECT pg_backend_pid()")).scalar_one() != pid
        assert visible(connection) == []
    with store.transaction(OWNER_B) as unit:
        assert unit.get_preferences() == Preferences()
    with store.transaction(OWNER_A) as unit:
        assert unit.get_preferences() == Preferences()
