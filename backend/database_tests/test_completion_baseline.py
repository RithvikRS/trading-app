"""Real owner isolation, stale-state races and transactional completion prerequisites."""

import re
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_accounts import definition, seed
from database_tests.test_imports import batch, observation
from database_tests.test_ownership import DISABLED, OWNER_A, OWNER_B, UNKNOWN, set_owner
from trading_db import migrate
from trading_db.account_keys import ReferenceKeys
from trading_db.accounts import AccountTransaction
from trading_db.completion_baseline import CompletionBaseline, CompletionUnavailable
from trading_db.connections import engine_for
from trading_db.events import EventTransaction
from trading_db.imports import ImportTransaction
from trading_db.workspace import Preferences


def baseline(store, owner=OWNER_A):
    with store.transaction(owner) as unit:
        return CompletionBaseline(unit._unit).current()


def test_owner_isolation_and_changes_track_only_financial_evidence(accounts):
    store, _ = accounts
    original = baseline(store)
    assert re.fullmatch(r"[0-9a-f]{64}", original)
    assert original != baseline(store, OWNER_B)
    seed(store, OWNER_B)
    assert baseline(store) == original
    account, source = seed(store)
    first = baseline(store)
    assert first != original and baseline(store) == first
    with store.transaction(OWNER_A) as unit:
        unit._unit.save_preferences(Preferences(theme="dark"))
        rotated = AccountTransaction(unit._unit, ReferenceKeys({1: b"a" * 32, 2: b"b" * 32}, 2))
        assert rotated.rotate_references() == 1
    assert baseline(store) == first
    with store.transaction(OWNER_A) as unit:
        unit.map(source.id, None, expected_revision=1)
    unlinked = baseline(store)
    assert unlinked != first
    with store.transaction(OWNER_A) as unit:
        unit.map(source.id, account.id, expected_revision=2)
    assert baseline(store) not in (first, unlinked)
    with store.transaction(OWNER_A) as unit:
        unit.archive(account.id, expected_revision=1)
    assert baseline(store) != first


def test_new_observations_reviews_and_financial_effects_invalidate_old_tokens(accounts):
    store, _ = accounts
    _, source = seed(store)
    values = [baseline(store)]
    with store.transaction(OWNER_A) as unit:
        imports = ImportTransaction(unit._unit)
        observed = imports.observation(source.id, observation())
        values.append(CompletionBaseline(unit._unit).current())
        staged = imports.stage(observed.id, batch(), expected_revision=0)
        values.append(CompletionBaseline(unit._unit).current())
        row = imports.rows(staged.id)[0]
        imports.decide(row.id, "include", expected_revision=0)
        values.append(CompletionBaseline(unit._unit).current())
        EventTransaction(unit._unit).record(row.id, expected_review_revision=1)
        values.append(CompletionBaseline(unit._unit).current())
    assert len(set(values)) == len(values)
    assert baseline(store) == values[-1]


def test_stale_guards_and_failed_dependent_writes_preserve_the_prior_state(accounts):
    store, _ = accounts
    old = baseline(store)
    seed(store)
    current = baseline(store)
    with store.transaction(OWNER_A) as unit:
        check = CompletionBaseline(unit._unit)
        with pytest.raises(CompletionUnavailable), check.guard(old):
            pytest.fail("Stale preview reached dependent writes")
        for invalid in (None, True, b"a" * 64, "A" * 64, "a" * 64 + "\n"):
            with pytest.raises(CompletionUnavailable), check.guard(invalid):
                pytest.fail("Invalid preview reached dependent writes")
        with pytest.raises(RuntimeError), check.guard(current):
            unit.create(definition(institution="sbi"))
            raise RuntimeError("Synthetic interruption")
        assert check.current() == current
        assert len(unit.list()) == 1
        with check.guard(current):
            unit.create(definition(institution="sbi"))
    assert baseline(store) != current


@pytest.mark.parametrize("owner", (None, "malformed", UNKNOWN, DISABLED, uuid4()))
def test_raw_runtime_calls_require_an_active_owner(accounts, owner):
    store, _ = accounts
    with store._workspace._engine.begin() as connection, pytest.raises(DBAPIError):
        if owner is not None:
            set_owner(connection, owner)
        connection.execute(text("SELECT app.financial_baseline()"))


@pytest.mark.parametrize("role", ("auth", "migrator", "bootstrap"))
def test_other_database_roles_cannot_obtain_financial_tokens(accounts, database, role):
    url, _ = database
    engine = engine_for(url(role), migration=True)
    try:
        with engine.begin() as connection, pytest.raises(DBAPIError):
            set_owner(connection, OWNER_A)
            connection.execute(text("SELECT app.financial_baseline()"))
    finally:
        engine.dispose()


@pytest.mark.parametrize("isolation", ("REPEATABLE READ", "SERIALIZABLE"))
def test_stale_snapshot_isolation_is_not_accepted(accounts, isolation):
    store, _ = accounts
    with store._workspace._engine.connect().execution_options(
        isolation_level=isolation
    ) as connection:
        with connection.begin(), pytest.raises(DBAPIError):
            set_owner(connection, OWNER_A)
            connection.execute(text("SELECT app.financial_baseline()"))


def wait_for_owner_lock(admin, pid):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with admin.connect() as connection:
            waiting = connection.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid "
                    "AND locktype='advisory' AND NOT granted)"
                ),
                dict(pid=pid),
            ).scalar_one()
        if waiting:
            return
        time.sleep(0.02)
    pytest.fail("Expected concurrent statement did not wait on the owner lock")


def test_raw_baseline_reads_a_commit_that_happened_after_its_statement_started(accounts):
    store, admin = accounts
    old = baseline(store)
    pending = Queue()

    def read():
        with store._workspace._engine.begin() as connection:
            set_owner(connection, OWNER_A)
            pending.put(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
            return connection.execute(text("SELECT app.financial_baseline()")).scalar_one()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.transaction(OWNER_A) as unit:
            unit.create(definition())
            future = pool.submit(read)
            wait_for_owner_lock(admin, pending.get(timeout=5))
            assert not future.done()
        result = future.result(timeout=5)
    assert result != old and result == baseline(store)


def test_raw_identity_insert_waits_for_an_existing_baseline_guard(accounts):
    store, admin = accounts
    original = baseline(store)
    pending = Queue()

    def create():
        with store._workspace._engine.begin() as connection:
            set_owner(connection, OWNER_A)
            pending.put(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
            connection.execute(
                text(
                    "INSERT INTO app.fund_schemes (owner_id,id,name) "
                    "VALUES (:owner,:id,'Synthetic')"
                ),
                dict(owner=OWNER_A, id=uuid4()),
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.transaction(OWNER_A) as unit:
            with CompletionBaseline(unit._unit).guard(original):
                future = pool.submit(create)
                wait_for_owner_lock(admin, pending.get(timeout=5))
                assert CompletionBaseline(unit._unit).current() == original
        future.result(timeout=5)
    assert baseline(store) != original


def test_over_budget_owner_state_is_rejected_instead_of_truncated(accounts):
    store, admin = accounts
    # Trusted fixture bypasses service admission solely in this disposable database.
    with admin.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO app.fund_schemes (owner_id,id,name) SELECT :owner,gen_random_uuid(),"
                "'Synthetic' FROM generate_series(1,1001)"
            ),
            dict(owner=OWNER_A),
        )
    with pytest.raises(CompletionUnavailable):
        baseline(store)
    assert re.fullmatch(r"[0-9a-f]{64}", baseline(store, OWNER_B))


def test_baseline_migration_round_trip_preserves_financial_data(accounts, database):
    store, admin = accounts
    url, project = database
    seed(store)
    original = baseline(store)
    migrate.apply(url(), project, target="0014_statement_boundaries", direction="downgrade")
    with admin.connect() as connection:
        assert (
            connection.execute(
                text("SELECT to_regprocedure('app.financial_baseline()')")
            ).scalar_one()
            is None
        )
        assert (
            connection.execute(text("SELECT count(*) FROM app.financial_accounts")).scalar_one()
            == 1
        )
    migrate.apply(url(), project)
    assert baseline(store) == original
