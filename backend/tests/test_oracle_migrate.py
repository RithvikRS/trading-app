from contextlib import contextmanager
from decimal import Decimal

import pytest

from trading_oracle import migrate
from trading_oracle.contracts import LocalTarget, OracleMigrationInterrupted, OracleUnavailable
from trading_oracle.schema import STEPS


def record(index=0, *, attempt=1, state="APPLIED", checksum=None, complete=True):
    step = STEPS[index]
    return (
        step.key,
        Decimal(attempt),
        checksum or step.checksum,
        state,
        object() if complete else None,
    )


@pytest.mark.parametrize(
    "entries",
    [
        [record(checksum="0" * 64)],
        [record(attempt=2)],
        [record(), record(attempt=2)],
        [record(state="STARTED", complete=False), record(1)],
        [record(1)],
        [record(state="STARTED")],
        [record(complete=False)],
        [("unknown", 1, "0" * 64, "STARTED", None)],
    ],
)
def test_journal_rejects_drift_holes_rewrite_and_invalid_completion(monkeypatch, entries):
    monkeypatch.setattr(migrate, "rows", lambda *args, **kwargs: entries)
    with pytest.raises(OracleUnavailable):
        migrate.journal(object())


def test_journal_preserves_bounded_abandoned_attempts(monkeypatch):
    entries = [
        record(state="ABANDONED"),
        record(attempt=2, state="ABANDONED"),
        record(attempt=3, state="STARTED", complete=False),
    ]
    monkeypatch.setattr(migrate, "rows", lambda *args, **kwargs: entries)
    assert migrate.journal(object()) == {STEPS[0].key: (3, "STARTED")}
    entries.append(record(attempt=4))
    with pytest.raises(OracleUnavailable):
        migrate.journal(object())


class JournalConnection:
    """Algorithm fixture only: real DDL durability is exercised by the separate Oracle suite."""

    def __init__(self):
        self.history = []
        self.objects = set()
        self.state = "INITIALIZING"
        self.commits = 0
        self.events = []

    def commit(self):
        self.commits += 1

    def cursor(self):
        return Cursor(self)


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, statement, **parameters):
        connection = self.connection
        if statement.startswith("INSERT INTO migration_journal"):
            connection.history.append(
                [
                    parameters["key"],
                    parameters["attempt"],
                    parameters["checksum"],
                    "STARTED",
                    None,
                ]
            )
        elif statement.startswith("UPDATE migration_journal"):
            found = [
                row
                for row in connection.history
                if row[0] == parameters["key"]
                and row[1] == parameters["attempt"]
                and row[3] == "STARTED"
            ]
            assert len(found) == 1
            found[0][3:] = ["ABANDONED" if "ABANDONED" in statement else "APPLIED", object()]
            self.rowcount = 1
        elif statement.startswith("UPDATE installation"):
            connection.state = "READY"
            self.rowcount = 1
        else:
            step = next(step for step in STEPS if step.sql == statement)
            assert connection.history[-1][0] == step.key
            assert connection.history[-1][3] == "STARTED"
            connection.objects.add(step.key)
            connection.events.append(("ddl", step.key))


@pytest.fixture
def algorithm(monkeypatch):
    connection = JournalConnection()

    @contextmanager
    def lock(connection):
        connection.events.append("lock")
        try:
            yield
        finally:
            connection.events.append("unlock")

    def exact(connection, step):
        if step.key not in connection.objects:
            raise OracleUnavailable()

    monkeypatch.setattr(migrate, "migration_lock", lock)
    monkeypatch.setattr(migrate, "_control_plane", lambda connection, target: connection.state)
    monkeypatch.setattr(
        migrate, "rows", lambda connection, *args, **kwargs: sorted(connection.history)
    )
    monkeypatch.setattr(
        migrate, "step_exists", lambda connection, step: step.key in connection.objects
    )
    monkeypatch.setattr(migrate, "step_exact", exact)
    monkeypatch.setattr(
        migrate, "validate_schema", lambda connection: [exact(connection, step) for step in STEPS]
    )
    return connection, LocalTarget(run_id="a" * 32, port=1521)


@pytest.mark.parametrize("step", STEPS, ids=lambda step: step.key)
@pytest.mark.parametrize("stage", ["before_ddl", "after_ddl", "after_postcondition"])
def test_every_committing_step_requires_explicit_reconciliation(algorithm, step, stage):
    connection, target = algorithm

    def interrupt(key, location):
        if key == step.key and location == stage:
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        migrate.install(connection, target, checkpoint=interrupt)
    assert connection.history[-1][0] == step.key
    assert connection.history[-1][3:] == ["STARTED", None]
    assert connection.events[-1] == "unlock"
    before = list(connection.events)
    with pytest.raises(OracleMigrationInterrupted):
        migrate.install(connection, target)
    assert connection.events[len(before) :] == ["lock", "unlock"]
    expected = "ABANDONED" if stage == "before_ddl" else "APPLIED"
    assert migrate.reconcile(connection, target, step.key) == expected
    migrate.install(connection, target)
    assert connection.state == "READY"
    assert connection.objects == {step.key for step in STEPS}
    if expected == "ABANDONED":
        assert [row[3] for row in connection.history if row[0] == step.key] == [
            "ABANDONED",
            "APPLIED",
        ]
    commits = connection.commits
    migrate.install(connection, target)
    assert connection.commits == commits


def test_interrupted_partial_object_is_not_blessed_or_replayed(algorithm, monkeypatch):
    connection, target = algorithm

    def interrupt(key, location):
        if location == "after_ddl":
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        migrate.install(connection, target, checkpoint=interrupt)

    def drift(connection, step):
        raise OracleUnavailable()

    monkeypatch.setattr(migrate, "step_exact", drift)
    with pytest.raises(OracleUnavailable):
        migrate.reconcile(connection, target, STEPS[0].key)
    assert connection.history[-1][3] == "STARTED"
    assert connection.events.count(("ddl", STEPS[0].key)) == 1
