from contextlib import contextmanager

import pytest

from trading_oracle import bootstrap, connections, migrate
from trading_oracle.contracts import LocalTarget, OracleUnavailable, new_role_secrets
from trading_oracle.schema import BASELINE_CHECKSUM


class SqlPlusMetadata:
    """Fixed synthetic metadata with SQLPlus-style line wrapping for concatenated output."""

    def __init__(self, fault=None):
        self.fault = fault
        self.unlocked = False
        self.verified = False
        self.statements = []

    def sql(self, statement):
        self.statements.append(statement)
        if "ALTER USER TRADING_RUNTIME" in statement:
            assert self.verified
            self.unlocked = True
            return ""
        if "FROM dba_context" in statement:
            return "0" if self.fault == "context" else "1"
        if "FROM trading_migrator.installation" in statement:
            if "state||" in statement:
                source = "READY|" + BASELINE_CHECKSUM + "|" + "a" * 32
                assert len(source) == 103
                return source[:80] + "\n" + source[80:]
            return "0" if self.fault == "ready" else "1"
        if "FROM dba_users" in statement:
            return "1" if self.fault == "locked" else "2"
        if "FROM dba_sys_privs" in statement:
            if "grantee='PUBLIC'" in statement:
                return "1" if self.fault == "public" else "0"
            if "privilege='CREATE SESSION'" in statement:
                return "1" if self.fault == "allowed_system" else "2"
            return "3" if self.fault == "all_system" else "2"
        for name in ("role_privs", "objects", "ts_quotas", "tab_privs", "col_privs"):
            if "FROM dba_" + name in statement:
                return "1" if self.fault == name else "0"
        pytest.fail("Unexpected bootstrap command")


@pytest.fixture
def target(monkeypatch):
    value = LocalTarget(run_id="a" * 32, port=1521)
    monkeypatch.setattr(bootstrap, "_verify_owned_target", lambda run: value)

    @contextmanager
    def connection(*args):
        yield object()

    monkeypatch.setattr(connections, "migration_connection", connection)
    return bootstrap.BootstrapResult(value, new_role_secrets())


def test_unlock_uses_scalar_readiness_independent_of_sqlplus_line_width(target, monkeypatch):
    run = SqlPlusMetadata()
    monkeypatch.setattr(migrate, "install", lambda *args: setattr(run, "verified", True))
    bootstrap.unlock_clients(run, target)
    assert run.unlocked and run.verified
    assert not any("||" in statement for statement in run.statements)


@pytest.mark.parametrize(
    "fault",
    [
        "context",
        "ready",
        "locked",
        "all_system",
        "allowed_system",
        "public",
        "role_privs",
        "objects",
        "ts_quotas",
        "tab_privs",
        "col_privs",
    ],
)
def test_unlock_retains_each_metadata_and_least_privilege_guard(target, monkeypatch, fault):
    run = SqlPlusMetadata(fault)
    monkeypatch.setattr(migrate, "install", lambda *args: setattr(run, "verified", True))
    with pytest.raises(OracleUnavailable):
        bootstrap.unlock_clients(run, target)
    assert not run.unlocked
