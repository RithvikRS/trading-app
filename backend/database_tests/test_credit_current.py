"""Credit current history, structural SQL boundaries and owner-write races."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from queue import Queue
from threading import Barrier
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests import test_credit_statements as statement_sql
from database_tests.test_credit_accounts import create
from database_tests.test_credit_accounts import credit_accounts as credit_accounts
from database_tests.test_credit_sources import credit_sources as credit_sources
from database_tests.test_credit_sources import source
from database_tests.test_ownership import DISABLED, OWNER_A, OWNER_B, UNKNOWN, set_owner
from tests.test_credit_current import current_values
from trading_api.finance import FinancialDate, FinancialInstant, FinancialValue
from trading_db.credit_current import (
    DAYS,
    ROLES,
    CreditCurrentDatabase,
    CreditCurrentUnavailable,
    new_current_id,
)
from trading_db.credit_statements import CreditStatementTransaction
from trading_db.workspace import OwnerAccessDenied

OBSERVATIONS = "app.credit_evidence_observations"
VALUES = "app.credit_current_values"
PARENT = (
    f"INSERT INTO {OBSERVATIONS} "
    " (owner_id,id,revision,previous_revision,source_id,mapping_revision,account_id,"
    "kind,statement_child_kind,current_child_kind,contract_version,reason) "
    "VALUES (:owner,:id,:revision,:previous,:source,:mapping,:account,"
    ":kind,NULL,'current',:version,:reason)"
)
VALUE_COLUMNS = (
    *DAYS,
    "as_of_instant",
    *(f"{role}_{part}" for role in ROLES for part in ("source", "amount", "missing")),
)
CHILD = (
    f"INSERT INTO {VALUES} (owner_id,observation_id,revision,"
    + ",".join(VALUE_COLUMNS)
    + ") VALUES (:owner,:id,:revision,"
    + ",".join(":" + name for name in VALUE_COLUMNS)
    + ")"
)


@pytest.fixture
def currents(credit_sources, database):
    sources, accounts, admin = credit_sources
    url, project = database
    store = CreditCurrentDatabase(url("runtime"), project)
    try:
        yield store, sources, accounts, admin
    finally:
        store.close()


def binding(sources, accounts, owner=OWNER_A):
    account, stream = create(accounts, owner), source(sources, owner)
    with sources.transaction(owner) as unit:
        unit.map(stream.id, account.id, expected_revision=0)
    return stream.id, account.id


def parameters(stream, account, *, owner=OWNER_A, root=None, revision=1, mapping=1, values=None):
    values = values or current_values()
    result = dict(
        owner=owner,
        id=root or uuid4(),
        revision=revision,
        previous=revision - 1 if revision > 1 else None,
        source=stream,
        mapping=mapping,
        account=account,
        kind="current",
        version=1,
        reason="initial" if revision == 1 else "correction",
    )
    result.update(
        {name: getattr(values, name).value if getattr(values, name) else None for name in DAYS}
    )
    result["as_of_instant"] = values.as_of_instant.source if values.as_of_instant else None
    for role in ROLES:
        value = getattr(values, role)
        result.update(
            {
                f"{role}_source": value.source,
                f"{role}_amount": value.value,
                f"{role}_missing": value.missing_reason,
            }
        )
    return result


def pair(connection, params):
    connection.execute(text(PARENT), params)
    connection.execute(text(CHILD), params)


def test_exact_history_retries_missing_zero_and_independent_date(currents):
    store, sources, accounts, _ = currents
    stream, account = binding(sources, accounts)
    root, values = new_current_id(), current_values()
    changed = replace(
        values,
        outstanding=FinancialValue("cash", "-0.00", currency="INR"),
        as_of_date=FinancialDate("0001-01-01"),
        as_of_instant=None,
    )
    with store.transaction(OWNER_A) as unit:
        original = unit.record(root, stream, 1, values)
        assert unit.record(root, stream, 1, values) == original
        corrected = unit.record(root, stream, 1, changed, expected_revision=1)
        assert corrected.revision == 2 and corrected.previous_revision == 1
        assert unit.record(root, stream, 1, values) == original
        assert unit.record(root, stream, 1, changed, expected_revision=1) == corrected
        assert unit.list(account) == (corrected,)
        assert unit.history(root, limit=1) == (corrected,)
        assert unit.history(root, before=2) == (original,)
        assert unit.get(root, at_revision=1).values == values
        assert unit.get(root, at_revision=2).values.outstanding.source == "-0.00"
        with pytest.raises(CreditCurrentUnavailable):
            unit.record(root, stream, 1, changed)
        spelling = replace(values, outstanding=FinancialValue("cash", "123.4", currency="INR"))
        with pytest.raises(CreditCurrentUnavailable):
            unit.record(root, stream, 1, spelling)
    with store.transaction(OWNER_A) as unit:
        assert unit.history(root) == (corrected, original)


def test_root_pages_keep_identical_reports_separate_and_unknown_foreign_ids_absent(currents):
    store, sources, accounts, _ = currents
    stream, account = binding(sources, accounts)
    other_stream, other_account = binding(sources, accounts, OWNER_B)
    ids = [new_current_id() for _ in range(4)]
    with store.transaction(OWNER_A) as unit:
        for root in ids:
            unit.record(root, stream, 1, current_values())
        first = unit.list(account, limit=2)
        second = unit.list(account, limit=2, after=first[-1].id)
        assert [item.id for item in (*first, *second)] == sorted(ids)
        assert unit.list(other_account) == ()
        for unknown in (uuid4(), other_stream):
            assert unit.get(unknown, at_revision=1) is None and unit.history(unknown) == ()
            with pytest.raises(CreditCurrentUnavailable):
                unit.record(uuid4(), unknown, 1, current_values())
    with store.transaction(OWNER_B) as unit:
        assert unit.list(account) == ()
        for root in ids:
            assert unit.history(root) == () and unit.get(root, at_revision=1) is None
        unit.record(uuid4(), other_stream, 1, current_values())


def test_remap_unlink_archive_do_not_reinterpret_history_or_authorize_retry(currents):
    store, sources, accounts, _ = currents
    stream, account = binding(sources, accounts)
    root, values = uuid4(), current_values()
    with store.transaction(OWNER_A) as unit:
        original = unit.record(root, stream, 1, values)
    with sources.transaction(OWNER_A) as unit:
        unit.map(stream, None, expected_revision=1)
        unit.map(stream, account, expected_revision=2)
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(CreditCurrentUnavailable):
            unit.record(root, stream, 1, values)
        corrected = unit.record(root, stream, 3, values, expected_revision=1)
        assert corrected.mapping_revision == 3
        assert unit.get(root, at_revision=1) == original
    replacement = create(accounts)
    with sources.transaction(OWNER_A) as unit:
        unit.map(stream, replacement.id, expected_revision=3)
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(CreditCurrentUnavailable):
            unit.record(root, stream, 4, values, expected_revision=2)
        assert unit.list(account) == (corrected,) and unit.list(replacement.id) == ()
    with accounts.transaction(OWNER_A) as unit:
        unit.archive(account, expected_revision=1)
    with store.transaction(OWNER_A) as unit:
        assert unit.history(root) == (corrected, original)


@pytest.mark.parametrize("owner", [DISABLED, UNKNOWN, None, str(OWNER_A)])
def test_invalid_owner_is_denied(currents, owner):
    store, _, _, _ = currents
    with pytest.raises(OwnerAccessDenied), store.transaction(owner):
        pytest.fail("Owner entered")


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
@pytest.mark.parametrize("table", [OBSERVATIONS, VALUES])
def test_runtime_cannot_mutate_retained_evidence(currents, table, operation):
    store, sources, accounts, _ = currents
    stream, _ = binding(sources, accounts)
    with store.transaction(OWNER_A) as unit:
        unit.record(uuid4(), stream, 1, current_values())
    query = (
        f"UPDATE {table} SET revision=revision"
        if operation == "UPDATE"
        else (f"DELETE FROM {table}" if operation == "DELETE" else f"TRUNCATE {table}")
    )
    with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        connection.execute(text(query))


@pytest.mark.parametrize("target", ["parent", "child"])
def test_orphan_rows_cannot_commit_even_with_bootstrap_privileges(currents, target):
    _, sources, accounts, admin = currents
    stream, account = binding(sources, accounts)
    params = parameters(stream, account)
    with pytest.raises(DBAPIError), admin.begin() as connection:
        connection.execute(text(PARENT if target == "parent" else CHILD), params)
    with admin.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {OBSERVATIONS}")).scalar_one() == 0
        assert connection.execute(text(f"SELECT count(*) FROM {VALUES}")).scalar_one() == 0


@pytest.mark.parametrize(
    "updates",
    [
        {"as_of_date": "infinity"},
        {"as_of_date": "10000-01-01"},
        {"as_of_date": "0001-01-01 BC"},
        {"as_of_date": "2026-10-14"},
        {"as_of_instant": "2026-10-15T24:00:00Z"},
        {"as_of_instant": "2026-10-15T00:00:60Z"},
        {"as_of_instant": "2026-10-15T00:00:00-00:00"},
        {"as_of_instant": "2026-10-15T00:00:00+14:01"},
        {"as_of_instant": "2026-10-15T00:00:00.1234567Z"},
        {"as_of_instant": "2026-10-15T00:00:00"},
        {"as_of_date": "0001-01-01", "as_of_instant": "0001-01-01T00:00:00+14:00"},
        {"as_of_date": "9999-12-31", "as_of_instant": "9999-12-31T23:59:59-14:00"},
        {"outstanding_source": "1.001", "outstanding_amount": "1.001"},
        {"outstanding_amount": "999.00"},
        {"outstanding_source": "NaN", "outstanding_amount": "NaN"},
        {"outstanding_missing": "not_supplied"},
        {"unbilled_missing": None},
        {"credit_limit_source": "-1.00", "credit_limit_amount": "-1.00"},
        {"kind": "statement"},
        {"version": 2},
        {"previous": 1},
        {"reason": "correction"},
    ],
)
def test_direct_sql_cannot_bypass_value_date_or_parent_structure(currents, updates):
    _, sources, accounts, admin = currents
    stream, account = binding(sources, accounts)
    params = parameters(stream, account) | updates
    with pytest.raises(DBAPIError), admin.begin() as connection:
        pair(connection, params)


def test_structural_mapping_and_root_identity_are_enforced_during_restore(currents):
    store, sources, accounts, admin = currents
    stream, account = binding(sources, accounts)
    foreign_stream, foreign_account = binding(sources, accounts, OWNER_B)
    another_stream, another_account = binding(sources, accounts)
    root = uuid4()
    with store.transaction(OWNER_A) as unit:
        unit.record(root, stream, 1, current_values())
    cases = [
        parameters(stream, foreign_account),
        parameters(foreign_stream, foreign_account),
        parameters(stream, another_account),
        parameters(another_stream, another_account, root=root, revision=2),
        parameters(stream, account, root=root, revision=3),
    ]
    for params in cases:
        with pytest.raises(DBAPIError), admin.begin() as connection:
            pair(connection, params)


@pytest.mark.parametrize("operation", ["insert", "delete", "update"])
def test_bootstrap_cannot_rewrite_immutable_rows_or_duplicate_children(currents, operation):
    store, sources, accounts, admin = currents
    stream, account = binding(sources, accounts)
    params = parameters(stream, account)
    with admin.begin() as connection:
        pair(connection, params)
    with pytest.raises(DBAPIError), admin.begin() as connection:
        if operation == "insert":
            connection.execute(text(CHILD), params)
        elif operation == "update":
            connection.execute(text(f"UPDATE {OBSERVATIONS} SET account_id=account_id"))
        else:
            connection.execute(text(f"DELETE FROM {VALUES}"))


def test_failed_child_and_outer_failure_leave_no_partial_record(currents):
    store, sources, accounts, admin = currents
    stream, account = binding(sources, accounts)
    invalid = parameters(stream, account) | {"credit_limit_source": "-1", "credit_limit_amount": -1}
    with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        pair(connection, invalid)
    with pytest.raises(RuntimeError), store.transaction(OWNER_A) as unit:
        unit.record(uuid4(), stream, 1, current_values())
        raise RuntimeError("Synthetic rollback")
    with admin.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {OBSERVATIONS}")).scalar_one() == 0
        assert connection.execute(text(f"SELECT count(*) FROM {VALUES}")).scalar_one() == 0


@pytest.mark.parametrize("same", [False, True])
def test_concurrent_correction_has_one_revision_and_exact_retry(same, currents):
    store, sources, accounts, _ = currents
    stream, _ = binding(sources, accounts)
    root, values = uuid4(), current_values()
    with store.transaction(OWNER_A) as unit:
        unit.record(root, stream, 1, values)
    barrier = Barrier(2)

    def correct(amount):
        barrier.wait(timeout=10)
        try:
            with store.transaction(OWNER_A) as unit:
                return unit.record(
                    root,
                    stream,
                    1,
                    replace(
                        values,
                        outstanding=FinancialValue("cash", amount, currency="INR"),
                    ),
                    expected_revision=1,
                ).revision
        except CreditCurrentUnavailable:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(correct, ("10.00", "10.00" if same else "11.00")))
    assert sorted(map(str, results)) == (["2", "2"] if same else ["2", "conflict"])
    with store.transaction(OWNER_A) as unit:
        assert len(unit.history(root)) == 2


def pair_across_deactivation(
    store, admin, own, other, lock, lock_params, locktype, *, child_only=False
):
    pending = Queue()

    def write():
        try:
            with store._workspace._engine.begin() as connection:
                set_owner(connection, OWNER_A)
                pending.put(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
                if child_only:
                    connection.execute(text(CHILD), own)
                else:
                    pair(connection, own)
            return "committed"
        except DBAPIError as error:
            return error.orig.diag.message_primary

    with ThreadPoolExecutor(max_workers=1) as pool:
        with admin.begin() as blocker:
            blocker_pid = blocker.execute(text("SELECT pg_backend_pid()")).scalar_one()
            blocker.execute(text(lock), lock_params)
            future = pool.submit(write)
            pid = pending.get(timeout=5)
            deadline = monotonic() + 3
            while monotonic() < deadline:
                with admin.connect() as observer:
                    waiting = observer.execute(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid "
                            "AND locktype=:kind AND NOT granted) "
                            "AND :blocker=ANY(pg_blocking_pids(:pid))"
                        ),
                        dict(pid=pid, kind=locktype, blocker=blocker_pid),
                    ).scalar_one()
                if waiting:
                    break
                assert not future.done(), "Write ended before the expected lock wait"
                sleep(0.01)
            else:
                pytest.fail("Current write did not reach the expected lock wait")
            with store._workspace._engine.begin() as control:
                set_owner(control, OWNER_B)
                pair(control, other)
            blocker.execute(
                text("UPDATE app.owners SET is_active=false WHERE id=:owner"), dict(owner=OWNER_A)
            )
        return future.result(timeout=10)


@pytest.mark.parametrize("target", ["parent", "child"])
@pytest.mark.parametrize("locktype", ["advisory", "transactionid"])
def test_both_boundaries_recheck_owner_after_actual_lock_wait(currents, locktype, target):
    store, sources, accounts, admin = currents
    stream, account = binding(sources, accounts)
    other_stream, other_account = binding(sources, accounts, OWNER_B)
    own = parameters(stream, account)
    other = parameters(other_stream, other_account, owner=OWNER_B)
    if locktype == "advisory":
        lock = (
            "SELECT pg_advisory_xact_lock("
            "hashtextextended('credit-accounts/v1:' || CAST(:owner AS text),0))"
        )
        lock_params = dict(owner=OWNER_A)
    else:
        lock = (
            "SELECT id FROM app.credit_billing_accounts WHERE owner_id=:owner AND id=:id FOR UPDATE"
        )
        lock_params = dict(owner=OWNER_A, id=account)
    if target == "child":
        with admin.begin() as connection:
            pair(connection, own)
    outcome = pair_across_deactivation(
        store, admin, own, other, lock, lock_params, locktype, child_only=target == "child"
    )
    with admin.connect() as connection:
        assert connection.execute(
            text(f"SELECT count(*) FROM {OBSERVATIONS} WHERE owner_id=:owner"),
            dict(owner=OWNER_A),
        ).scalar_one() == (1 if target == "child" else 0)
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM {OBSERVATIONS} WHERE owner_id=:owner"),
                dict(owner=OWNER_B),
            ).scalar_one()
            == 1
        )
    assert outcome == "Credit statement operation is unavailable"


def test_child_rechecks_owner_after_parent_admission(currents):
    store, sources, accounts, admin = currents
    stream, account = binding(sources, accounts)
    params = parameters(stream, account)
    with pytest.raises(DBAPIError, match="Credit statement operation is unavailable"):
        with store._workspace._engine.begin() as connection:
            set_owner(connection, OWNER_A)
            connection.execute(text(PARENT), params)
            with admin.begin() as other:
                other.execute(
                    text("UPDATE app.owners SET is_active=false WHERE id=:owner"),
                    dict(owner=OWNER_A),
                )
            connection.execute(text(CHILD), params)
    with admin.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {OBSERVATIONS}")).scalar_one() == 0


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
@pytest.mark.parametrize("target", ["parent", "child"])
def test_sql_isolation_guard_applies_to_both_tables(currents, isolation, target):
    _, sources, accounts, admin = currents
    stream, account = binding(sources, accounts)
    params = parameters(stream, account)
    with admin.connect().execution_options(isolation_level=isolation) as connection:
        with (
            pytest.raises(DBAPIError, match="Credit statement operation is unavailable"),
            connection.begin(),
        ):
            if target == "child":
                connection.execute(text(PARENT), params)
            connection.execute(text("SET LOCAL ROLE trading_runtime"))
            set_owner(connection, OWNER_A)
            connection.execute(text(PARENT if target == "parent" else CHILD), params)


def test_runtime_grants_and_forced_owner_policies(currents):
    _, _, _, admin = currents
    with admin.connect() as connection:
        for table in ("credit_evidence_observations", "credit_current_values"):
            row = connection.execute(
                text(
                    "SELECT c.relrowsecurity,c.relforcerowsecurity,r.rolname "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "JOIN pg_roles r ON r.oid=c.relowner WHERE n.nspname='app' AND c.relname=:table"
                ),
                dict(table=table),
            ).one()
            assert tuple(row) == (True, True, "trading_migrator")
            for role in ("trading_auth",):
                assert not connection.execute(
                    text("SELECT has_table_privilege(:role,:table,'SELECT')"),
                    dict(role=role, table="app." + table),
                ).scalar_one()
            for privilege in ("UPDATE", "DELETE", "TRUNCATE", "TRIGGER"):
                assert not connection.execute(
                    text("SELECT has_table_privilege('trading_runtime',:table,:privilege)"),
                    dict(table="app." + table, privilege=privilege),
                ).scalar_one()
        assert not connection.execute(
            text(
                "SELECT has_column_privilege('trading_runtime',"
                "'app.credit_evidence_observations','created_at','INSERT')"
            )
        ).scalar_one()


@pytest.mark.parametrize("context", [None, "", "malformed", str(DISABLED), str(UNKNOWN)])
def test_direct_sql_requires_active_matching_context(currents, context):
    store, sources, accounts, _ = currents
    stream, account = binding(sources, accounts)
    with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
        if context is not None:
            connection.execute(
                text("SELECT set_config('app.owner_id',:owner,true)"), dict(owner=context)
            )
        pair(connection, parameters(stream, account))


def test_archived_target_rejects_new_evidence_and_exact_retry_but_retains_reads(currents):
    store, sources, accounts, _ = currents
    stream, account = binding(sources, accounts)
    root, values = uuid4(), current_values()
    with store.transaction(OWNER_A) as unit:
        saved = unit.record(root, stream, 1, values)
    with accounts.transaction(OWNER_A) as unit:
        unit.archive(account, expected_revision=1)
    with store.transaction(OWNER_A) as unit:
        assert unit.get(root, at_revision=1) == saved
        for target in (root, uuid4()):
            with pytest.raises(CreditCurrentUnavailable):
                unit.record(target, stream, 1, values)


def test_evidence_holds_account_row_until_commit_then_archive_retains_history(currents):
    store, sources, accounts, _ = currents
    stream, account = binding(sources, accounts)

    def archive():
        with (
            pytest.raises(DBAPIError, match="lock timeout"),
            accounts._workspace._engine.begin() as connection,
        ):
            set_owner(connection, OWNER_A)
            connection.execute(text("SET LOCAL lock_timeout='100ms'"))
            connection.execute(
                text(
                    "UPDATE app.credit_billing_accounts SET archived_at=statement_timestamp() "
                    "WHERE id=:id"
                ),
                dict(id=account),
            )

    root = uuid4()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.transaction(OWNER_A) as unit:
            saved = unit.record(root, stream, 1, current_values())
            pool.submit(archive).result(timeout=10)
    with accounts.transaction(OWNER_A) as unit:
        unit.archive(account, expected_revision=1)
    with store.transaction(OWNER_A) as unit:
        assert unit.history(root) == (saved,)


def seed_statement_observations(admin, params):
    with admin.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {OBSERVATIONS} "
                "(owner_id,id,revision,previous_revision,source_id,mapping_revision,account_id,"
                "kind,contract_version,reason) SELECT :owner,md5('statement-'||n::text)::uuid,"
                "1,NULL,:source,1,:account,'statement',1,'initial' FROM generate_series(1,999) n"
            ),
            params,
        )
        connection.execute(
            text(
                f"INSERT INTO {statement_sql.VALUES} (owner_id,observation_id,revision,"
                + ",".join(statement_sql.VALUE_COLUMNS)
                + ") SELECT :owner,md5('statement-'||n::text)::uuid,1,"
                + ",".join(":" + name for name in statement_sql.VALUE_COLUMNS)
                + " FROM generate_series(1,999) n"
            ),
            params,
        )


def test_direct_sql_quota_serializes_two_last_slot_admissions(currents):
    store, sources, accounts, admin = currents
    stream, account = binding(sources, accounts)
    params = statement_sql.parameters(stream, account)
    seed_statement_observations(admin, params)
    pending = Queue()

    def insert(kind, root):
        try:
            with store._workspace._engine.begin() as connection:
                set_owner(connection, OWNER_A)
                pending.put(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
                if kind == "statement":
                    statement_sql.pair(
                        connection, statement_sql.parameters(stream, account, root=root)
                    )
                else:
                    pair(connection, parameters(stream, account, root=root))
            return kind, root
        except DBAPIError as error:
            assert error.orig.diag.message_primary == "Credit statement operation is unavailable"
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        with admin.begin() as blocker:
            blocker_pid = blocker.execute(text("SELECT pg_backend_pid()")).scalar_one()
            blocker.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended('credit-accounts/v1:' || CAST(:owner AS text),0))"
                ),
                dict(owner=OWNER_A),
            )
            futures = [pool.submit(insert, kind, uuid4()) for kind in ("statement", "current")]
            pids = [pending.get(timeout=5) for _ in futures]
            deadline = monotonic() + 3
            while monotonic() < deadline:
                with admin.connect() as observer:
                    waiting = [
                        observer.execute(
                            text(
                                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid "
                                "AND locktype='advisory' AND NOT granted) "
                                "AND :blocker=ANY(pg_blocking_pids(:pid))"
                            ),
                            dict(pid=pid, blocker=blocker_pid),
                        ).scalar_one()
                        for pid in pids
                    ]
                if all(waiting):
                    break
                assert not any(future.done() for future in futures)
                sleep(0.01)
            else:
                pytest.fail("Both direct inserts must wait on the owner lock")
        results = [future.result(timeout=10) for future in futures]
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    with admin.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {OBSERVATIONS}")).scalar_one() == 1000
        statement_count = connection.execute(
            text(f"SELECT count(*) FROM {statement_sql.VALUES}")
        ).scalar_one()
        current_count = connection.execute(text(f"SELECT count(*) FROM {VALUES}")).scalar_one()
        assert statement_count + current_count == 1000
        assert current_count == (winners[0][0] == "current")
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(CreditCurrentUnavailable):
            unit.record(uuid4(), stream, 1, current_values())
    other_stream, other_account = binding(sources, accounts, OWNER_B)
    with store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_B)
        pair(connection, parameters(other_stream, other_account, owner=OWNER_B))
    with admin.connect() as connection:
        for table in (OBSERVATIONS, VALUES):
            assert (
                connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE owner_id=:owner"), dict(owner=OWNER_B)
                ).scalar_one()
                == 1
            )


def test_archive_committed_during_account_wait_rejects_direct_current_pair(currents):
    store, sources, accounts, admin = currents
    stream, account = binding(sources, accounts)
    pending = Queue()

    def write():
        try:
            with store._workspace._engine.begin() as connection:
                set_owner(connection, OWNER_A)
                pending.put(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
                pair(connection, parameters(stream, account))
            return "committed"
        except DBAPIError as error:
            return error.orig.diag.message_primary

    with ThreadPoolExecutor(max_workers=1) as pool:
        with admin.begin() as blocker:
            blocker_pid = blocker.execute(text("SELECT pg_backend_pid()")).scalar_one()
            blocker.execute(
                text(
                    "UPDATE app.credit_billing_accounts SET archived_at=statement_timestamp() "
                    "WHERE owner_id=:owner AND id=:id"
                ),
                dict(owner=OWNER_A, id=account),
            )
            future = pool.submit(write)
            pid = pending.get(timeout=5)
            deadline = monotonic() + 3
            while monotonic() < deadline:
                with admin.connect() as observer:
                    waiting = observer.execute(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid "
                            "AND locktype='transactionid' AND NOT granted) "
                            "AND :blocker=ANY(pg_blocking_pids(:pid))"
                        ),
                        dict(pid=pid, blocker=blocker_pid),
                    ).scalar_one()
                if waiting:
                    break
                assert not future.done()
                sleep(0.01)
            else:
                pytest.fail("Current write did not wait on archival")
        assert future.result(timeout=10) == "Credit statement operation is unavailable"
    with admin.connect() as connection:
        for table in (OBSERVATIONS, VALUES):
            assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0


def test_typed_children_discriminator_nulls_and_root_kind_survive_trusted_restore(currents):
    store, sources, accounts, admin = currents
    stream, account = binding(sources, accounts)
    current = parameters(stream, account)
    statement = statement_sql.parameters(stream, account)
    with admin.begin() as connection:
        # Structural deferred ordering is allowed for bootstrap; both pairs must finish.
        connection.execute(text(CHILD), current)
        connection.execute(text(PARENT), current)
        statement_sql.pair(connection, statement)
    for parent, child in ((current, statement), (statement, current)):
        with pytest.raises(DBAPIError), admin.begin() as connection:
            if parent["kind"] == "current":
                connection.execute(text(statement_sql.CHILD), child | {"id": parent["id"]})
            else:
                connection.execute(text(CHILD), child | {"id": parent["id"]})
    for statement_kind, current_kind in (
        (None, None),
        ("statement", "current"),
        ("statement", None),
    ):
        raw = PARENT.replace("NULL,'current'", ":statement_kind,:current_kind")
        with pytest.raises(DBAPIError), admin.begin() as connection:
            p = parameters(stream, account) | dict(
                statement_kind=statement_kind, current_kind=current_kind
            )
            connection.execute(text(raw), p)
            connection.execute(text(CHILD), p)
    with pytest.raises(DBAPIError), admin.begin() as connection:
        statement_sql.pair(
            connection, statement_sql.parameters(stream, account, root=current["id"], revision=2)
        )
    with pytest.raises(DBAPIError), admin.begin() as connection:
        pair(connection, parameters(stream, account, root=statement["id"], revision=2))
    with store.transaction(OWNER_A) as unit:
        assert unit.get(statement["id"], at_revision=1) is None
        with pytest.raises(CreditCurrentUnavailable):
            unit.record(statement["id"], stream, 1, current_values())
    with store.transaction(OWNER_A) as unit:
        statements = CreditStatementTransaction(unit._unit)
        assert statements.get(current["id"], at_revision=1) is None
        with pytest.raises(statement_sql.CreditStatementUnavailable):
            statements.record(current["id"], stream, 1, statement_sql.statement_values())


def test_runtime_child_first_is_not_bootstrap_restore(currents):
    store, sources, accounts, admin = currents
    stream, account = binding(sources, accounts)
    with pytest.raises(DBAPIError, match="Credit statement operation is unavailable"):
        with store._workspace._engine.begin() as connection:
            set_owner(connection, OWNER_A)
            connection.execute(text(CHILD), parameters(stream, account))
    with admin.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {OBSERVATIONS}")).scalar_one() == 0


@pytest.mark.parametrize(
    "instant",
    [
        "2026-10-15T00:00:00Z",
        "2026-10-15T00:00:00+00:00",
        "2026-10-15T00:00:00.000000-14:00",
        "2026-10-15T23:59:59.123456+14:00",
    ],
)
def test_instant_spelling_round_trips_and_equal_utc_retries_conflict(currents, instant):
    store, sources, accounts, _ = currents
    stream, account = binding(sources, accounts)
    root = uuid4()
    values = current_values(as_of_instant=FinancialInstant(instant))
    with store.transaction(OWNER_A) as unit:
        saved = unit.record(root, stream, 1, values)
        assert saved.values.as_of_instant.source == instant
        assert unit.record(root, stream, 1, values) == saved
        alternative = instant.replace("Z", "+00:00") if instant.endswith("Z") else None
        if alternative:
            with pytest.raises(CreditCurrentUnavailable):
                unit.record(
                    root, stream, 1, replace(values, as_of_instant=FinancialInstant(alternative))
                )


def test_repeatable_read_stale_snapshot_cannot_add_the_1001st_mixed_record(currents):
    store, sources, accounts, admin = currents
    stream, account = binding(sources, accounts)
    seed_statement_observations(admin, statement_sql.parameters(stream, account))
    with store._workspace._engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as stale:
        with pytest.raises(DBAPIError, match="Credit statement operation is unavailable"):
            with stale.begin():
                set_owner(stale, OWNER_A)
                assert (
                    stale.execute(text(f"SELECT count(*) FROM {OBSERVATIONS}")).scalar_one() == 999
                )
                with store._workspace._engine.begin() as admitted:
                    set_owner(admitted, OWNER_A)
                    pair(admitted, parameters(stream, account))
                pair(stale, parameters(stream, account))
    with admin.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {OBSERVATIONS}")).scalar_one() == 1000
        assert connection.execute(text(f"SELECT count(*) FROM {VALUES}")).scalar_one() == 1


@pytest.mark.parametrize(
    "source,day,valid",
    [
        ("0001-01-01T00:00:00Z", "0001-01-01", True),
        ("9999-12-31T23:59:59.999999Z", "9999-12-31", True),
        ("2026-10-15T00:00:00+14:00", "2026-10-15", True),
        ("2026-10-15T23:59:59-14:00", "2026-10-15", True),
        ("2026-10-15T00:00:00.10+00:00", "2026-10-15", True),
        (None, "2026-10-15", True),
        ("2026-10-15T00:00:00Z", "2026-10-14", False),
        ("2026-02-29T00:00:00Z", "2026-02-28", False),
        ("2026-10-15T24:00:00Z", "2026-10-15", False),
        ("2026-10-15T00:60:00Z", "2026-10-15", False),
        ("2026-10-15T00:00:60Z", "2026-10-15", False),
        ("2026-10-15T00:00:00-00:00", "2026-10-15", False),
        ("2026-10-15T00:00:00+14:01", "2026-10-15", False),
        ("2026-10-15T00:00:00.1234567Z", "2026-10-15", False),
        ("2026-10-15T00:00:00", "2026-10-15", False),
        ("0001-01-01T00:00:00+14:00", "0001-01-01", False),
        ("9999-12-31T23:59:59-14:00", "9999-12-31", False),
    ],
)
def test_sql_and_python_source_local_instant_acceptance_agree(currents, source, day, valid):
    _, _, _, admin = currents
    from trading_api.finance import FinancialValueError

    def parse():
        return current_values(
            as_of_date=FinancialDate(day),
            as_of_instant=FinancialInstant(source) if source is not None else None,
        )

    if valid:
        assert parse()
    else:
        with pytest.raises(FinancialValueError):
            parse()
    with admin.connect() as connection:
        assert (
            connection.execute(
                text("SELECT app.valid_snapshot_instant(:source,CAST(:day AS date))"),
                dict(source=source, day=day),
            ).scalar_one()
            is valid
        )


def test_direct_sql_missing_owner_filter_cannot_read_or_insert_foreign_current_evidence(currents):
    store, sources, accounts, admin = currents
    own_stream, own_account = binding(sources, accounts)
    foreign_stream, foreign_account = binding(sources, accounts, OWNER_B)
    own = parameters(own_stream, own_account)
    foreign = parameters(foreign_stream, foreign_account, owner=OWNER_B)
    with admin.begin() as connection:
        pair(connection, own)
        pair(connection, foreign)
    with store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        for table in (OBSERVATIONS, VALUES):
            assert connection.execute(text(f"SELECT owner_id FROM {table}")).scalars().all() == [
                OWNER_A
            ]
    with pytest.raises(DBAPIError, match="Credit statement operation is unavailable"):
        with store._workspace._engine.begin() as connection:
            set_owner(connection, OWNER_A)
            pair(connection, foreign | {"id": uuid4()})
    with admin.connect() as connection:
        for table in (OBSERVATIONS, VALUES):
            assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 2


def test_runtime_cannot_supply_current_child_discriminator(currents):
    store, sources, accounts, _ = currents
    stream, account = binding(sources, accounts)
    params = parameters(stream, account)
    with pytest.raises(DBAPIError):
        with store._workspace._engine.begin() as connection:
            set_owner(connection, OWNER_A)
            connection.execute(text(PARENT), params)
            connection.execute(
                text(
                    CHILD.replace(
                        "(owner_id,observation_id,revision,",
                        "(owner_id,observation_id,revision,kind,",
                    ).replace(
                        "VALUES (:owner,:id,:revision,", "VALUES (:owner,:id,:revision,'current',"
                    )
                ),
                params,
            )
