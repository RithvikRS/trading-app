import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace
from uuid import UUID

import oracledb
import pytest

from trading_oracle import connections, workspace
from trading_oracle.contracts import LocalTarget, OracleUnavailable, new_role_secrets


class Cancellation(BaseException):
    pass


class NativePool:
    def __init__(self):
        self.connection = SimpleNamespace()
        self.events = []
        self.fail_release = False
        self.fail_drop = False

    def acquire(self):
        self.events.append("acquire")
        return self.connection

    def release(self, connection):
        assert connection is self.connection
        self.events.append("release")
        if self.fail_release:
            raise RuntimeError("synthetic release failure")

    def drop(self, connection):
        assert connection is self.connection
        self.events.append("drop")
        if self.fail_drop:
            raise RuntimeError("synthetic drop failure")

    def close(self, *, force):
        self.events.append(("close", force))


@pytest.fixture
def native(monkeypatch):
    pool = NativePool()
    monkeypatch.setattr(connections, "_parameters", lambda *args: {})
    monkeypatch.setattr(connections.oracledb, "create_pool", lambda **kwargs: pool)
    monkeypatch.setattr(connections, "_clean", lambda *args: pool.events.append("clean"))
    client = connections.ClientPool(
        LocalTarget(run_id="a" * 32, port=1521), new_role_secrets(), "TRADING_RUNTIME"
    )
    return pool, client


@pytest.mark.parametrize("failure", [None, ValueError("body"), Cancellation()])
def test_checkout_and_return_clean_the_same_custodied_connection(native, failure):
    pool, client = native
    caught = None
    try:
        with client.checkout() as connection:
            assert connection is pool.connection
            pool.events.append("body")
            if failure:
                raise failure
    except BaseException as error:
        caught = error
    assert caught is failure
    assert pool.events == ["acquire", "clean", "body", "clean", "release"]
    with client.checkout() as connection:
        assert connection is pool.connection
    client.close()
    with pytest.raises(OracleUnavailable):
        with client.checkout():
            pytest.fail("Closed pool reopened")


def test_driver_failure_is_redacted_and_dropped_without_retry(native):
    pool, client = native
    with pytest.raises(OracleUnavailable, match="^Oracle baseline is unavailable.$"):
        with client.checkout():
            raise oracledb.DatabaseError("synthetic sensitive driver detail")
    assert pool.events == ["acquire", "clean", "drop"]
    assert client._active == 0


@pytest.mark.parametrize("failure_index", [1, 2])
def test_cleanup_failure_discards_connection(native, monkeypatch, failure_index):
    pool, client = native
    calls = 0

    def clean(*args):
        nonlocal calls
        calls += 1
        pool.events.append("clean")
        if calls == failure_index:
            raise OracleUnavailable()

    monkeypatch.setattr(connections, "_clean", clean)
    with pytest.raises(OracleUnavailable):
        with client.checkout():
            pool.events.append("body")
    assert pool.events[-1] == "drop"
    assert pool.events.count("drop") == 1
    assert "release" not in pool.events
    assert ("body" in pool.events) == (failure_index == 2)
    assert client._active == 0


def test_failed_drop_poison_denies_new_checkout(native):
    pool, client = native
    pool.fail_drop = True
    with pytest.raises(OracleUnavailable):
        with client.checkout():
            raise oracledb.DatabaseError("synthetic")
    assert pool.events.count("drop") == 1
    with pytest.raises(OracleUnavailable):
        with client.checkout():
            pytest.fail("Poisoned pool admitted new work")
    client.close()
    assert pool.events[-1] == ("close", True)


def test_release_failure_drops_and_never_retries_release(native):
    pool, client = native
    pool.fail_release = True
    with pytest.raises(OracleUnavailable):
        with client.checkout():
            pass
    assert pool.events[-2:] == ["release", "drop"]
    assert pool.events.count("release") == 1


def test_close_does_not_seize_an_active_lease(native):
    pool, client = native
    with client.checkout():
        with pytest.raises(OracleUnavailable):
            client.close()
        assert not client._closed
    client.close()
    assert pool.events[-1] == ("close", False)


@pytest.mark.parametrize("rollback_fails", [False, True])
@pytest.mark.parametrize("close_fails", [False, True])
@pytest.mark.parametrize("body_fails", [False, True])
def test_migrator_cleanup_always_closes_and_redacts(
    monkeypatch, rollback_fails, close_fails, body_fails
):
    events = []

    def rollback():
        events.append("rollback")
        if rollback_fails:
            raise oracledb.DatabaseError("secret rollback diagnostic")

    def close():
        events.append("close")
        if close_fails:
            raise oracledb.DatabaseError("secret close diagnostic")

    connection = SimpleNamespace(rollback=rollback, close=close)
    monkeypatch.setattr(connections, "_parameters", lambda *args: {})
    monkeypatch.setattr(connections, "_server", lambda *args, **kwargs: None)
    monkeypatch.setattr(connections.oracledb, "connect", lambda **kwargs: connection)
    caught = None
    try:
        with connections.migration_connection(
            LocalTarget(run_id="a" * 32, port=1521), new_role_secrets()
        ):
            if body_fails:
                raise oracledb.DatabaseError("secret body diagnostic")
    except OracleUnavailable as error:
        caught = error
    assert events == ["rollback", "close"]
    assert (caught is not None) == (rollback_fails or close_fails or body_fails)
    if caught:
        rendered = "".join(traceback.format_exception(caught))
        assert all(
            f"secret {phase} diagnostic" not in rendered for phase in ("rollback", "close", "body")
        )


def test_native_close_failure_retains_custody_and_can_retry(native, monkeypatch):
    pool, client = native
    attempts = []

    def close(*, force):
        attempts.append(force)
        if len(attempts) == 1:
            raise oracledb.DatabaseError("secret close diagnostic")

    monkeypatch.setattr(pool, "close", close)
    with pytest.raises(OracleUnavailable):
        client.close()
    assert not client._closed and client._admission_closed and not client._closing
    with pytest.raises(OracleUnavailable):
        with client.checkout():
            pytest.fail("Failed-close pool admitted work")
    client.close()
    assert client._closed and attempts == [False, False]
    client.close()
    assert len(attempts) == 2


def test_repeated_native_close_failure_stays_visible_and_bounded(native, monkeypatch):
    pool, client = native
    attempts = []

    def close(*, force):
        attempts.append(force)
        raise oracledb.DatabaseError("synthetic close failure")

    monkeypatch.setattr(pool, "close", close)
    for _ in range(3):
        with pytest.raises(OracleUnavailable):
            client.close()
    assert attempts == [False, False]
    assert not client._closed and client._admission_closed


def test_queued_acquire_rechecks_poison_before_admission(native, monkeypatch):
    pool, client = native
    started, acquired = Event(), Event()
    uncertain, waiting = object(), object()
    dropped = []
    admitted = []

    def acquire():
        started.set()
        assert acquired.wait(5)
        return waiting

    def drop(connection):
        dropped.append(connection)
        if connection is uncertain:
            raise oracledb.DatabaseError("synthetic drop failure")

    def queued():
        with pytest.raises(OracleUnavailable):
            with client.checkout():
                admitted.append(True)

    monkeypatch.setattr(pool, "acquire", acquire)
    monkeypatch.setattr(pool, "drop", drop)
    with ThreadPoolExecutor(max_workers=1) as worker:
        pending = worker.submit(queued)
        try:
            assert started.wait(5)
            with pytest.raises(OracleUnavailable):
                client._drop(uncertain)
        finally:
            acquired.set()
        pending.result(timeout=5)
    assert dropped == [uncertain, waiting]
    assert admitted == [] and client._active == 0
    assert "release" not in pool.events


def test_clean_rolls_back_then_clears_context_identifier_and_verifies(monkeypatch):
    events = []
    state = {"owner": "old-owner", "identifier": "pretend-owner", "zone": "+05:30"}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def callproc(self, name):
            assert name == "TRADING_MIGRATOR.OWNER_CONTEXT.CLEAR_OWNER"
            events.append("clear")
            state["owner"] = None

        def execute(self, statement):
            if "CLEAR_IDENTIFIER" in statement:
                state["identifier"] = None
            elif "TIME_ZONE" in statement:
                state["zone"] = "+00:00"
            else:
                pytest.fail("Unexpected cleanup mutation")

    connection = SimpleNamespace(
        rollback=lambda: events.append("rollback"),
        cursor=Cursor,
        transaction_in_progress=False,
    )
    monkeypatch.setattr(connections, "_server", lambda *args, **kwargs: events.append("verify"))

    def query(connection, statement, **kwargs):
        return (
            [(state["owner"],)]
            if "OWNER_ID" in statement
            else [(state["identifier"], state["zone"])]
        )

    monkeypatch.setattr(connections, "rows", query)
    connections._clean(connection, LocalTarget(run_id="a" * 32, port=1521), "TRADING_RUNTIME")
    assert events == ["rollback", "verify", "clear"]
    assert state == {"owner": None, "identifier": None, "zone": "+00:00"}
    assert connection.call_timeout == 5000


def test_closed_workspace_unit_never_queries_or_reopens(monkeypatch):
    monkeypatch.setattr(
        workspace, "rows", lambda *args, **kwargs: pytest.fail("Closed unit queried")
    )
    unit = workspace.WorkspaceTransaction(object(), UUID(int=1), read_only=False)
    unit._open = False
    with pytest.raises(OracleUnavailable):
        unit.preference_snapshot()


@pytest.mark.parametrize("failure", [None, Cancellation(), ValueError("body")])
def test_workspace_commit_and_closed_unit_on_every_exit(monkeypatch, failure):
    events = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def callproc(self, name, parameters):
            events.append("enter")

    connection = SimpleNamespace(cursor=Cursor, commit=lambda: events.append("commit"))

    @contextmanager
    def checkout():
        try:
            yield connection
        finally:
            events.append("return")

    pool = SimpleNamespace(role="TRADING_RUNTIME", checkout=checkout)
    monkeypatch.setattr(workspace.WorkspaceTransaction, "_require_open", lambda self: None)
    database = workspace.WorkspaceDatabase(pool)
    caught = None
    try:
        with database.transaction(UUID(int=1)) as unit:
            if failure:
                raise failure
    except BaseException as error:
        caught = error
    assert caught is failure
    assert not unit._open
    assert events == (["enter", "commit", "return"] if failure is None else ["enter", "return"])
