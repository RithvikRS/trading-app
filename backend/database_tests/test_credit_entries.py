"""Credit entry history, structural SQL boundaries and owner-write races."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from queue import Queue
from threading import Barrier
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests import test_credit_current as current_sql
from database_tests import test_credit_statements as statement_sql
from database_tests.test_credit_accounts import create
from database_tests.test_credit_accounts import credit_accounts as credit_accounts
from database_tests.test_credit_sources import credit_sources as credit_sources
from database_tests.test_credit_sources import source
from database_tests.test_ownership import DISABLED, OWNER_A, OWNER_B, UNKNOWN, set_owner
from tests.test_credit_entries import entry_values
from trading_api.finance import FinancialDate, FinancialValue
from trading_db.credit_entries import (
    CreditEntryDatabase,
    CreditEntryUnavailable,
    new_entry_id,
)
from trading_db.credit_statements import CreditStatementTransaction
from trading_db.workspace import OwnerAccessDenied

OBSERVATIONS = "app.credit_evidence_observations"
VALUES = "app.credit_entry_values"
PARENT = (
    f"INSERT INTO {OBSERVATIONS} "
    " (owner_id,id,revision,previous_revision,source_id,mapping_revision,account_id,"
    "kind,statement_child_kind,current_child_kind,entry_child_kind,contract_version,reason) "
    "VALUES (:owner,:id,:revision,:previous,:source,:mapping,:account,"
    ":kind,NULL,NULL,'entry',:version,:reason)"
)
VALUE_COLUMNS = (
    "role",
    "treatment",
    "transaction_date",
    "posting_date",
    "billing_source",
    "billing_amount",
    "billing_missing",
    "original_source",
    "original_amount",
    "original_missing",
    "original_currency",
)
CHILD = (
    f"INSERT INTO {VALUES} (owner_id,observation_id,revision,"
    + ",".join(VALUE_COLUMNS)
    + ") VALUES (:owner,:id,:revision,"
    + ",".join(":" + name for name in VALUE_COLUMNS)
    + ")"
)


@pytest.fixture
def entries(credit_sources, database):
    sources, accounts, admin = credit_sources
    url, project = database
    store = CreditEntryDatabase(url("runtime"), project)
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
    values = values or entry_values()
    result = dict(
        owner=owner,
        id=root or uuid4(),
        revision=revision,
        previous=revision - 1 if revision > 1 else None,
        source=stream,
        mapping=mapping,
        account=account,
        kind="entry",
        version=1,
        reason="initial" if revision == 1 else "correction",
    )
    result.update(
        role=values.role,
        treatment=values.treatment,
        transaction_date=values.transaction_date.value if values.transaction_date else None,
        posting_date=values.posting_date.value if values.posting_date else None,
    )
    for prefix, value in (("billing", values.billing_amount), ("original", values.original_amount)):
        result.update(
            {
                prefix + "_source": value.source if value else None,
                prefix + "_amount": value.value if value else None,
                prefix + "_missing": value.missing_reason if value else None,
            }
        )
    result["original_currency"] = (
        values.original_amount.currency if values.original_amount else None
    )
    return result


def pair(connection, params):
    connection.execute(text(PARENT), params)
    connection.execute(text(CHILD), params)


def test_exact_history_retries_and_unsupported_correction_remain_listable(entries):
    store, sources, accounts, admin = entries
    stream, account = binding(sources, accounts)
    root, values = new_entry_id(), entry_values(role="pending_debit", posting_date=None)
    changed = replace(
        values,
        role="posted_credit",
        treatment="unsupported",
        billing_amount=FinancialValue("cash", "-0.00", currency="INR"),
        transaction_date=None,
        posting_date=FinancialDate("0001-01-01"),
        original_amount=None,
    )
    with admin.connect() as connection:
        movements = connection.execute(
            text("SELECT count(*) FROM app.financial_events")
        ).scalar_one()
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
        assert unit.get(root, at_revision=2).values.billing_amount.source == "-0.00"
        for conflicting in (
            changed,
            replace(values, billing_amount=FinancialValue("cash", "123.4", currency="INR")),
            replace(values, original_amount=None),
            replace(values, original_amount=FinancialValue("cash", "1.2", currency="USD")),
            replace(values, original_amount=FinancialValue("cash", "1.20", currency="INR")),
            replace(values, treatment="ambiguous"),
            replace(values, transaction_date=None),
        ):
            with pytest.raises(CreditEntryUnavailable):
                unit.record(root, stream, 1, conflicting)
    with store.transaction(OWNER_A) as unit:
        assert unit.history(root) == (corrected, original)
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM app.financial_events")).scalar_one()
            == movements
        )


def test_root_pages_keep_identical_reports_separate_and_unknown_foreign_ids_absent(entries):
    store, sources, accounts, _ = entries
    stream, account = binding(sources, accounts)
    other_stream, other_account = binding(sources, accounts, OWNER_B)
    ids = [new_entry_id() for _ in range(4)]
    with store.transaction(OWNER_A) as unit:
        for root in ids:
            unit.record(root, stream, 1, entry_values())
        first = unit.list(account, limit=2)
        second = unit.list(account, limit=2, after=first[-1].id)
        assert [item.id for item in (*first, *second)] == sorted(ids)
        assert unit.list(other_account) == ()
        for unknown in (uuid4(), other_stream):
            assert unit.get(unknown, at_revision=1) is None and unit.history(unknown) == ()
            with pytest.raises(CreditEntryUnavailable):
                unit.record(uuid4(), unknown, 1, entry_values())
    with store.transaction(OWNER_B) as unit:
        assert unit.list(account) == ()
        for root in ids:
            assert unit.history(root) == () and unit.get(root, at_revision=1) is None
        unit.record(uuid4(), other_stream, 1, entry_values())


def test_remap_unlink_archive_do_not_reinterpret_history_or_authorize_retry(entries):
    store, sources, accounts, _ = entries
    stream, account = binding(sources, accounts)
    root, values = uuid4(), entry_values()
    with store.transaction(OWNER_A) as unit:
        original = unit.record(root, stream, 1, values)
    with sources.transaction(OWNER_A) as unit:
        unit.map(stream, None, expected_revision=1)
        unit.map(stream, account, expected_revision=2)
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(CreditEntryUnavailable):
            unit.record(root, stream, 1, values)
        corrected = unit.record(root, stream, 3, values, expected_revision=1)
        assert corrected.mapping_revision == 3
        assert unit.get(root, at_revision=1) == original
    replacement = create(accounts)
    with sources.transaction(OWNER_A) as unit:
        unit.map(stream, replacement.id, expected_revision=3)
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(CreditEntryUnavailable):
            unit.record(root, stream, 4, values, expected_revision=2)
        assert unit.list(account) == (corrected,) and unit.list(replacement.id) == ()
    with accounts.transaction(OWNER_A) as unit:
        unit.archive(account, expected_revision=1)
    with store.transaction(OWNER_A) as unit:
        assert unit.history(root) == (corrected, original)


@pytest.mark.parametrize("owner", [DISABLED, UNKNOWN, None, str(OWNER_A)])
def test_invalid_owner_is_denied(entries, owner):
    store, _, _, _ = entries
    with pytest.raises(OwnerAccessDenied), store.transaction(owner):
        pytest.fail("Owner entered")


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
@pytest.mark.parametrize("table", [OBSERVATIONS, VALUES])
def test_runtime_cannot_mutate_retained_evidence(entries, table, operation):
    store, sources, accounts, _ = entries
    stream, _ = binding(sources, accounts)
    with store.transaction(OWNER_A) as unit:
        unit.record(uuid4(), stream, 1, entry_values())
    query = (
        f"UPDATE {table} SET revision=revision"
        if operation == "UPDATE"
        else (f"DELETE FROM {table}" if operation == "DELETE" else f"TRUNCATE {table}")
    )
    with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        connection.execute(text(query))


@pytest.mark.parametrize("target", ["parent", "child"])
def test_orphan_rows_cannot_commit_even_with_bootstrap_privileges(entries, target):
    _, sources, accounts, admin = entries
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
        {"transaction_date": "infinity"},
        {"posting_date": "-infinity"},
        {"transaction_date": "10000-01-01"},
        {"posting_date": "0001-01-01 BC"},
        {"billing_source": "1.001", "billing_amount": "1.001"},
        {"billing_amount": "999.00"},
        {"billing_source": "NaN", "billing_amount": "NaN"},
        {"billing_source": "1000000000000000000", "billing_amount": "1000000000000000000"},
        {"billing_source": "01.00", "billing_amount": "1.00"},
        {"billing_missing": "not_supplied"},
        {"billing_source": None, "billing_amount": None},
        {"billing_source": "-1.00", "billing_amount": "-1.00"},
        {"original_currency": None},
        {"original_currency": "EUR"},
        {"original_source": None},
        {"original_amount": None},
        {"original_missing": "not_supplied"},
        {"original_source": "-1.00", "original_amount": "-1.00"},
        {"original_source": "1.001", "original_amount": "1.001"},
        {"original_source": "1e2", "original_amount": "100"},
        {"original_source": "1000000000000000000", "original_amount": "1000000000000000000"},
        {"original_source": "01.00", "original_amount": "1.00"},
        {"original_source": None, "original_amount": None, "original_missing": None},
        {"role": "unknown"},
        {"treatment": "unknown"},
        {"role": "unresolved", "treatment": "movement"},
        {"role": "pending_debit"},
        {"role": "pending_credit"},
        {"kind": "statement"},
        {"kind": "current"},
        {"version": 2},
        {"previous": 1},
        {"reason": "correction"},
    ],
)
def test_direct_sql_cannot_bypass_value_date_or_parent_structure(entries, updates):
    _, sources, accounts, admin = entries
    stream, account = binding(sources, accounts)
    with pytest.raises(DBAPIError), admin.begin() as connection:
        pair(connection, parameters(stream, account) | updates)


def test_structural_mapping_and_root_identity_are_enforced_during_restore(entries):
    store, sources, accounts, admin = entries
    stream, account = binding(sources, accounts)
    foreign_stream, foreign_account = binding(sources, accounts, OWNER_B)
    another_stream, another_account = binding(sources, accounts)
    root = uuid4()
    with store.transaction(OWNER_A) as unit:
        unit.record(root, stream, 1, entry_values())
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
def test_bootstrap_cannot_rewrite_immutable_rows_or_duplicate_children(entries, operation):
    store, sources, accounts, admin = entries
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


def test_failed_child_and_outer_failure_leave_no_partial_record(entries):
    store, sources, accounts, admin = entries
    stream, account = binding(sources, accounts)
    invalid = parameters(stream, account) | {"billing_source": "-1", "billing_amount": -1}
    with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        pair(connection, invalid)
    with pytest.raises(RuntimeError), store.transaction(OWNER_A) as unit:
        unit.record(uuid4(), stream, 1, entry_values())
        raise RuntimeError("Synthetic rollback")
    with admin.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {OBSERVATIONS}")).scalar_one() == 0
        assert connection.execute(text(f"SELECT count(*) FROM {VALUES}")).scalar_one() == 0


@pytest.mark.parametrize("same", [False, True])
def test_concurrent_correction_has_one_revision_and_exact_retry(same, entries):
    store, sources, accounts, _ = entries
    stream, _ = binding(sources, accounts)
    root, values = uuid4(), entry_values()
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
                        billing_amount=FinancialValue("cash", amount, currency="INR"),
                    ),
                    expected_revision=1,
                ).revision
        except CreditEntryUnavailable:
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
                pytest.fail("Entry write did not reach the expected lock wait")
            with store._workspace._engine.begin() as control:
                set_owner(control, OWNER_B)
                pair(control, other)
            blocker.execute(
                text("UPDATE app.owners SET is_active=false WHERE id=:owner"), dict(owner=OWNER_A)
            )
        return future.result(timeout=10)


@pytest.mark.parametrize("target", ["parent", "child"])
@pytest.mark.parametrize("locktype", ["advisory", "transactionid"])
def test_both_boundaries_recheck_owner_after_actual_lock_wait(entries, locktype, target):
    store, sources, accounts, admin = entries
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


def test_child_rechecks_owner_after_parent_admission(entries):
    store, sources, accounts, admin = entries
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
def test_sql_isolation_guard_applies_to_both_tables(entries, isolation, target):
    _, sources, accounts, admin = entries
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


def test_runtime_grants_and_forced_owner_policies(entries):
    _, _, _, admin = entries
    with admin.connect() as connection:
        for table in ("credit_evidence_observations", "credit_entry_values"):
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
def test_direct_sql_requires_active_matching_context(entries, context):
    store, sources, accounts, _ = entries
    stream, account = binding(sources, accounts)
    with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
        if context is not None:
            connection.execute(
                text("SELECT set_config('app.owner_id',:owner,true)"), dict(owner=context)
            )
        pair(connection, parameters(stream, account))


def test_archived_target_rejects_new_evidence_and_exact_retry_but_retains_reads(entries):
    store, sources, accounts, _ = entries
    stream, account = binding(sources, accounts)
    root, values = uuid4(), entry_values()
    with store.transaction(OWNER_A) as unit:
        saved = unit.record(root, stream, 1, values)
    with accounts.transaction(OWNER_A) as unit:
        unit.archive(account, expected_revision=1)
    with store.transaction(OWNER_A) as unit:
        assert unit.get(root, at_revision=1) == saved
        for target in (root, uuid4()):
            with pytest.raises(CreditEntryUnavailable):
                unit.record(target, stream, 1, values)


def test_evidence_holds_account_row_until_commit_then_archive_retains_history(entries):
    store, sources, accounts, _ = entries
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
            saved = unit.record(root, stream, 1, entry_values())
            pool.submit(archive).result(timeout=10)
    with accounts.transaction(OWNER_A) as unit:
        unit.archive(account, expected_revision=1)
    with store.transaction(OWNER_A) as unit:
        assert unit.history(root) == (saved,)


@pytest.mark.parametrize("other_kind", ["statement", "current"])
def test_direct_sql_quota_serializes_two_last_slot_admissions(entries, other_kind):
    store, sources, accounts, admin = entries
    stream, account = binding(sources, accounts)
    current_sql.seed_statement_observations(admin, statement_sql.parameters(stream, account))
    pending = Queue()
    legacy = statement_sql if other_kind == "statement" else current_sql

    def insert(kind, root):
        try:
            with store._workspace._engine.begin() as connection:
                set_owner(connection, OWNER_A)
                pending.put(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
                if kind == "entry":
                    pair(connection, parameters(stream, account, root=root))
                else:
                    legacy.pair(connection, legacy.parameters(stream, account, root=root))
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
            futures = [pool.submit(insert, kind, uuid4()) for kind in (other_kind, "entry")]
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
        counts = [
            connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in (statement_sql.VALUES, current_sql.VALUES, VALUES)
        ]
        assert sum(counts) == 1000 and counts[-1] == (winners[0][0] == "entry")
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(CreditEntryUnavailable):
            unit.record(uuid4(), stream, 1, entry_values())
        if winners[0][0] == "entry":
            assert unit.record(winners[0][1], stream, 1, entry_values()).revision == 1
        else:
            # The retained legacy target must also remain replayable at the shared quota.
            from trading_db.credit_current import CreditCurrentTransaction
            from trading_db.credit_statements import CreditStatementTransaction

            target = (
                CreditStatementTransaction(unit._unit)
                if other_kind == "statement"
                else CreditCurrentTransaction(unit._unit)
            )
            values = (
                statement_sql.statement_values()
                if other_kind == "statement"
                else current_sql.current_values()
            )
            assert target.record(winners[0][1], stream, 1, values).revision == 1
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


def test_archive_committed_during_account_wait_rejects_direct_entry_pair(entries):
    store, sources, accounts, admin = entries
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
                pytest.fail("Entry write did not wait on archival")
        assert future.result(timeout=10) == "Credit statement operation is unavailable"
    with admin.connect() as connection:
        for table in (OBSERVATIONS, VALUES):
            assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0


def test_three_typed_children_root_kinds_and_null_discriminators_survive_restore(entries):
    store, sources, accounts, admin = entries
    stream, account = binding(sources, accounts)
    own = parameters(stream, account)
    older = [
        (module, module.parameters(stream, account)) for module in (statement_sql, current_sql)
    ]
    with admin.begin() as connection:
        connection.execute(text(CHILD), own)
        connection.execute(text(PARENT), own)
        for module, params in older:
            module.pair(connection, params)
    for module, params in older:
        for query, supplied in (
            (module.CHILD, params | {"id": own["id"]}),
            (CHILD, own | {"id": params["id"]}),
        ):
            with pytest.raises(DBAPIError), admin.begin() as connection:
                connection.execute(text(query), supplied)
        with pytest.raises(DBAPIError), admin.begin() as connection:
            module.pair(connection, module.parameters(stream, account, root=own["id"], revision=2))
        with pytest.raises(DBAPIError), admin.begin() as connection:
            pair(connection, parameters(stream, account, root=params["id"], revision=2))
        with store.transaction(OWNER_A) as unit:
            assert unit.get(params["id"], at_revision=1) is None
            with pytest.raises(CreditEntryUnavailable):
                unit.record(params["id"], stream, 1, entry_values())
    from trading_db.credit_current import CreditCurrentTransaction, CreditCurrentUnavailable

    for cls, error, values in (
        (
            CreditStatementTransaction,
            statement_sql.CreditStatementUnavailable,
            statement_sql.statement_values(),
        ),
        (CreditCurrentTransaction, CreditCurrentUnavailable, current_sql.current_values()),
    ):
        with store.transaction(OWNER_A) as unit:
            legacy = cls(unit._unit)
            assert legacy.get(own["id"], at_revision=1) is None
            with pytest.raises(error):
                legacy.record(own["id"], stream, 1, values)
    for kinds in (
        (None, None, None),
        ("statement", None, "entry"),
        (None, "current", "entry"),
        (None, None, "current"),
        ("statement", None, None),
    ):
        raw = PARENT.replace("NULL,NULL,'entry'", ":statement_kind,:current_kind,:entry_kind")
        with pytest.raises(DBAPIError), admin.begin() as connection:
            params = parameters(stream, account) | dict(
                zip(("statement_kind", "current_kind", "entry_kind"), kinds, strict=True)
            )
            connection.execute(text(raw), params)
            connection.execute(text(CHILD), params)


def test_runtime_child_first_is_not_bootstrap_restore(entries):
    store, sources, accounts, admin = entries
    stream, account = binding(sources, accounts)
    with pytest.raises(DBAPIError, match="Credit statement operation is unavailable"):
        with store._workspace._engine.begin() as connection:
            set_owner(connection, OWNER_A)
            connection.execute(text(CHILD), parameters(stream, account))
    with admin.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {OBSERVATIONS}")).scalar_one() == 0


def test_repeatable_read_stale_snapshot_cannot_add_the_1001st_mixed_record(entries):
    store, sources, accounts, admin = entries
    stream, account = binding(sources, accounts)
    current_sql.seed_statement_observations(admin, statement_sql.parameters(stream, account))
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


def test_direct_sql_missing_owner_filter_cannot_read_or_insert_foreign_entry_evidence(entries):
    store, sources, accounts, admin = entries
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


def test_runtime_cannot_supply_entry_child_discriminator(entries):
    store, sources, accounts, _ = entries
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
                        "VALUES (:owner,:id,:revision,", "VALUES (:owner,:id,:revision,'entry',"
                    )
                ),
                params,
            )


@pytest.mark.parametrize(
    "original",
    [
        None,
        FinancialValue("cash", None, currency="USD", missing_reason="not_supplied"),
        FinancialValue("cash", None, currency="INR", missing_reason="not_supplied"),
        FinancialValue("cash", "-0.00", currency="USD"),
        FinancialValue("cash", "0.00", currency="INR"),
    ],
)
def test_original_absence_missing_currency_and_spelling_survive_sql(entries, original):
    store, sources, accounts, admin = entries
    stream, account = binding(sources, accounts)
    root = uuid4()
    value = entry_values(original_amount=original, transaction_date=None, posting_date=None)
    with store.transaction(OWNER_A) as unit:
        saved = unit.record(root, stream, 1, value)
        assert unit.record(root, stream, 1, value) == saved
        assert saved.values.original_amount == original
        for alternative in (
            None,
            FinancialValue("cash", None, currency="USD", missing_reason="not_supplied"),
        ):
            if alternative != original:
                with pytest.raises(CreditEntryUnavailable):
                    unit.record(root, stream, 1, replace(value, original_amount=alternative))
    with admin.connect() as connection:
        row = connection.execute(
            text(
                "SELECT original_source,original_amount,original_missing,original_currency "
                f"FROM {VALUES}"
            )
        ).one()
        assert tuple(row) == (
            (None, None, None, None)
            if original is None
            else (original.source, original.value, original.missing_reason, original.currency)
        )


@pytest.mark.parametrize(
    "role", ["posted_debit", "posted_credit", "pending_debit", "pending_credit", "unresolved"]
)
@pytest.mark.parametrize("treatment", ["movement", "ambiguous", "unsupported"])
def test_sql_role_treatment_matrix_matches_value_contract(entries, role, treatment):
    _, sources, accounts, admin = entries
    stream, account = binding(sources, accounts)
    params = parameters(stream, account) | dict(
        role=role, treatment=treatment, posting_date=None, transaction_date="9999-12-31"
    )
    if role == "unresolved" and treatment == "movement":
        with pytest.raises(DBAPIError), admin.begin() as connection:
            pair(connection, params)
    else:
        with admin.begin() as connection:
            pair(connection, params)


@pytest.mark.parametrize("mapping_first", [True, False])
def test_shared_owner_lock_orders_remap_and_entry_without_rebinding_history(entries, mapping_first):
    store, sources, accounts, admin = entries
    stream, account = binding(sources, accounts)
    other_stream, other_account = binding(sources, accounts, OWNER_B)
    destination = create(accounts).id
    params = parameters(stream, account)
    mapping_sql = text(
        "INSERT INTO app.credit_source_account_mappings "
        "(owner_id,source_id,revision,previous_revision,account_id,reason) "
        "VALUES (:owner,:source,2,1,:account,'correction')"
    )
    mapping = dict(owner=OWNER_A, source=stream, account=destination)
    pending = Queue()

    def waiting_write():
        try:
            with store._workspace._engine.begin() as connection:
                set_owner(connection, OWNER_A)
                pending.put(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
                if mapping_first:
                    pair(connection, params)
                else:
                    connection.execute(mapping_sql, mapping)
            return "committed"
        except DBAPIError as error:
            return error.orig.diag.message_primary

    with ThreadPoolExecutor(max_workers=1) as pool:
        with store._workspace._engine.begin() as blocker:
            set_owner(blocker, OWNER_A)
            blocker_pid = blocker.execute(text("SELECT pg_backend_pid()")).scalar_one()
            if mapping_first:
                blocker.execute(mapping_sql, mapping)
            else:
                pair(blocker, params)
            future = pool.submit(waiting_write)
            pid = pending.get(timeout=5)
            deadline = monotonic() + 3
            while monotonic() < deadline:
                with admin.connect() as observer:
                    waiting = observer.execute(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks "
                            "WHERE pid=:pid AND locktype='advisory' AND NOT granted) "
                            "AND :blocker=ANY(pg_blocking_pids(:pid))"
                        ),
                        dict(pid=pid, blocker=blocker_pid),
                    ).scalar_one()
                if waiting:
                    break
                assert not future.done()
                sleep(0.01)
            else:
                pytest.fail("The second owner write did not reach the shared lock")
            # Blocker + worker occupy the entry pool; the control uses its own runtime pool.
            with sources._workspace._engine.begin() as control:
                set_owner(control, OWNER_B)
                pair(control, parameters(other_stream, other_account, owner=OWNER_B))
        assert future.result(timeout=10) == (
            "Credit statement operation is unavailable" if mapping_first else "committed"
        )
    with admin.connect() as connection:
        assert connection.execute(
            text(f"SELECT count(*) FROM {OBSERVATIONS} WHERE owner_id=:owner"), dict(owner=OWNER_A)
        ).scalar_one() == (0 if mapping_first else 1)
    with sources.transaction(OWNER_A) as unit:
        assert unit.resolve(stream).account_id == destination
    with store.transaction(OWNER_A) as unit:
        assert unit.list(destination) == ()
        if not mapping_first:
            retained = unit.get(params["id"], at_revision=1)
            assert retained.account_id == account and retained.mapping_revision == 1
            assert unit.list(account) == (retained,)
            with pytest.raises(CreditEntryUnavailable):
                unit.record(params["id"], stream, 1, entry_values())


@pytest.mark.parametrize("boundary", ["parent", "child", "constraint"])
def test_interrupted_record_rolls_back_savepoint_and_keeps_unit_usable(
    entries, monkeypatch, boundary
):
    store, sources, accounts, admin = entries
    stream, account = binding(sources, accounts)
    prefixes = {
        "parent": "INSERT INTO app.credit_evidence_observations",
        "child": "INSERT INTO app.credit_entry_values",
        "constraint": "SET CONSTRAINTS app.credit_entry_required IMMEDIATE",
    }
    root = uuid4()
    with store.transaction(OWNER_A) as unit:
        execute = unit._execute

        def interrupted(sql, **parameters):
            result = execute(sql, **parameters)
            if sql.startswith(prefixes[boundary]):
                raise RuntimeError("Synthetic interruption")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(unit, "_execute", interrupted)
            with pytest.raises(RuntimeError, match="Synthetic interruption"):
                unit.record(root, stream, 1, entry_values())
        assert unit.list(account) == () and unit.history(root) == ()
        saved = unit.record(root, stream, 1, entry_values())
    with admin.connect() as connection:
        for table in (OBSERVATIONS, VALUES):
            assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 1
    from trading_db.connections import DatabaseFailure

    for call in (
        lambda: unit.get(root, at_revision=1),
        lambda: unit.history(root),
        lambda: unit.list(account),
        lambda: unit.record(root, stream, 1, entry_values()),
    ):
        with pytest.raises(DatabaseFailure):
            call()
    with store.transaction(OWNER_A) as unit:
        assert unit.get(root, at_revision=1) == saved
