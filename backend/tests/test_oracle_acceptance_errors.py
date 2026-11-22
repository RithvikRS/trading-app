from types import SimpleNamespace

import oracledb
import pytest

from oracle_tests import acceptance
from oracle_tests.acceptance import MISSING_OBJECT_PRIVILEGE, denial, execute, lock_expiry
from trading_oracle.contracts import OracleUnavailable


def driver_error(code):
    return oracledb.DatabaseError(SimpleNamespace(code=code))


def test_new_missing_object_privilege_code_is_an_expected_deliberate_denial():
    with denial(942, 1031, MISSING_OBJECT_PRIVILEGE):
        raise driver_error(41900)


@pytest.mark.parametrize("expected", [28115, 30006, 20001, 28000])
def test_missing_privilege_cannot_substitute_for_policy_lock_context_or_login_checks(expected):
    with pytest.raises(OracleUnavailable):
        with denial(expected):
            raise driver_error(41900)


def test_success_of_a_deliberately_forbidden_operation_still_fails_acceptance():
    with pytest.raises(OracleUnavailable):
        with denial(942, 1031, MISSING_OBJECT_PRIVILEGE):
            pass


def test_missing_privilege_on_positive_operation_is_not_swallowed_or_retried():
    calls = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement, parameters):
            calls.append(statement)
            raise driver_error(41900)

    with pytest.raises(oracledb.DatabaseError) as caught:
        execute(SimpleNamespace(cursor=Cursor), "SELECT id FROM trading_migrator.owners")
    assert caught.value.args[0].code == 41900
    assert calls == ["SELECT id FROM trading_migrator.owners"]


@pytest.mark.parametrize("code", [30006, 54])
def test_deliberate_lock_expiry_accepts_documented_server_variants_after_wait(monkeypatch, code):
    clock = iter([100.0, 105.0])
    monkeypatch.setattr(acceptance, "monotonic", lambda: next(clock))
    with lock_expiry():
        raise driver_error(code)


@pytest.mark.parametrize("code", [30006, 54])
@pytest.mark.parametrize("elapsed", [0.1, 3.9, 12.0, 20.0])
def test_lock_error_does_not_pass_without_the_bounded_elapsed_wait(monkeypatch, code, elapsed):
    clock = iter([100.0, 100.0 + elapsed])
    monkeypatch.setattr(acceptance, "monotonic", lambda: next(clock))
    with pytest.raises(OracleUnavailable):
        with lock_expiry():
            raise driver_error(code)


@pytest.mark.parametrize("code", [None, 41900])
def test_lock_expiry_still_rejects_success_and_unrelated_error(monkeypatch, code):
    monkeypatch.setattr(acceptance, "monotonic", lambda: 100.0)
    with pytest.raises(OracleUnavailable):
        with lock_expiry():
            if code is not None:
                raise driver_error(code)


def test_lock_busy_on_a_positive_operation_remains_an_error():
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement, parameters):
            raise driver_error(54)

    with pytest.raises(oracledb.DatabaseError) as caught:
        execute(SimpleNamespace(cursor=Cursor), "SELECT id FROM trading_migrator.owners")
    assert caught.value.args[0].code == 54
