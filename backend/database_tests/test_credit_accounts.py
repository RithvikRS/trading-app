"""Owned credit identities, immutable SQL boundaries and serializable admission."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier
from time import monotonic, sleep
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_ownership import DISABLED, OWNER_A, OWNER_B, UNKNOWN, set_owner
from trading_db import migrate
from trading_db.accounts import AccountDatabase
from trading_db.connections import DatabaseFailure, engine_for
from trading_db.credit_accounts import (
    CreditAccountDatabase,
    CreditAccountDefinition,
    CreditAccountUnavailable,
)
from trading_db.workspace import OwnerAccessDenied

TABLE = "app.credit_billing_accounts"
INSERT = (
    "INSERT INTO app.credit_billing_accounts (owner_id,id,issuer,billing_currency,label) "
    "VALUES (:owner,:id,'hdfc','INR','Synthetic billing')"
)


@pytest.fixture
def credit_accounts(database):
    url, project = database
    migrate.apply(url(), project)
    admin = engine_for(url("bootstrap"), migration=True)
    with admin.begin() as connection:
        for owner, active in ((OWNER_A, True), (OWNER_B, True), (DISABLED, False)):
            connection.execute(
                text("INSERT INTO app.owners (id,is_active) VALUES (:id,:active)"),
                dict(id=owner, active=active),
            )
    store = CreditAccountDatabase(url("runtime"), project)
    try:
        yield store, admin
    finally:
        store.close()
        admin.dispose()


def create(store, owner=OWNER_A):
    with store.transaction(owner) as unit:
        return unit.create(CreditAccountDefinition(label="Synthetic billing"))


def test_identical_labels_are_distinct_billing_accounts_and_paging_is_stable(
    credit_accounts, database
):
    store, _ = credit_accounts
    created = [create(store) for _ in range(5)]
    assert len({account.id for account in created}) == 5
    with store.transaction(OWNER_A) as unit:
        seen, after = [], None
        while rows := unit.list(limit=2, after=after):
            seen.extend(rows)
            after = rows[-1].id
        assert [account.id for account in seen] == sorted(account.id for account in created)
        assert unit.list(after=UUID(int=(1 << 128) - 1)) == ()
        for account in seen:
            assert unit.get(account.id) == account
            assert account.revision == 1 and account.archived_at is None
            assert account.created_at == account.updated_at
    url, project = database
    assets = AccountDatabase(url("runtime"), project)
    try:
        with assets.transaction(OWNER_A) as unit:
            assert unit.list() == ()
            assert unit.sources() == ()
    finally:
        assets.close()
    store.close()
    with store.transaction(OWNER_A) as unit:
        assert len(unit.list()) == 5


def test_archive_is_revision_checked_and_preserves_identity(credit_accounts):
    store, _ = credit_accounts
    account = create(store)
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(CreditAccountUnavailable):
            unit.archive(account.id, expected_revision=2)
        archived = unit.archive(account.id, expected_revision=1)
        assert archived.id == account.id and archived.definition == account.definition
        assert archived.created_at == account.created_at
        assert archived.archived_at == archived.updated_at >= archived.created_at
        assert archived.revision == 2
        for expected in (1, 2):
            with pytest.raises(CreditAccountUnavailable):
                unit.archive(account.id, expected_revision=expected)
        assert unit.get(account.id) == archived and unit.list() == (archived,)
    with pytest.raises(DatabaseFailure, match="ended"):
        unit.get(account.id)


def test_direct_sql_cannot_clear_or_repeat_archival(credit_accounts):
    store, _ = credit_accounts
    account = create(store)
    with store.transaction(OWNER_A) as unit:
        archived = unit.archive(account.id, expected_revision=1)
    for value in ("NULL", "statement_timestamp()", "statement_timestamp()+interval '1 day'"):
        with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
            set_owner(connection, OWNER_A)
            connection.execute(text(f"UPDATE {TABLE} SET archived_at={value}"))
    with store.transaction(OWNER_A) as unit:
        assert unit.get(account.id) == archived


def test_unknown_and_foreign_records_have_identical_read_write_results(credit_accounts):
    store, _ = credit_accounts
    own, foreign = create(store), create(store, OWNER_B)
    with store.transaction(OWNER_A) as unit:
        assert unit.list() == (own,)
        for account_id in (foreign.id, uuid4()):
            assert unit.get(account_id) is None
            with pytest.raises(CreditAccountUnavailable) as error:
                unit.archive(account_id, expected_revision=1)
            assert str(account_id) not in str(error.value)
    with store.transaction(OWNER_B) as unit:
        assert unit.list() == (foreign,) and unit.get(own.id) is None


@pytest.mark.parametrize("owner", [DISABLED, UNKNOWN, None, str(OWNER_A)])
def test_invalid_owner_cannot_enter_credit_transaction(credit_accounts, owner):
    store, _ = credit_accounts
    with pytest.raises(OwnerAccessDenied), store.transaction(owner):
        pytest.fail("Invalid owner entered transaction")


@pytest.mark.parametrize("context", [None, "", "invalid", str(DISABLED), str(UNKNOWN)])
def test_missing_disabled_or_invalid_context_cannot_read_or_create(credit_accounts, context):
    store, _ = credit_accounts
    create(store)
    with store._workspace._engine.begin() as connection:
        if context is not None:
            set_owner(connection, context)
        assert connection.execute(text(f"SELECT * FROM {TABLE}")).all() == []
        with pytest.raises(DBAPIError):
            connection.execute(text(INSERT), dict(owner=OWNER_A, id=uuid4()))


def test_owner_change_rolls_back_and_does_not_leak_through_connection_reuse(credit_accounts):
    store, _ = credit_accounts
    create(store)
    with pytest.raises(RuntimeError), store.transaction(OWNER_B) as unit:
        unit.create(CreditAccountDefinition(label="Rolled back"))
        raise RuntimeError("Synthetic interruption")
    with store.transaction(OWNER_B) as unit:
        assert unit.list() == ()
    with store.transaction(OWNER_A) as unit:
        assert len(unit.list()) == 1


def test_forced_owner_policies_and_narrow_privileges(credit_accounts, database):
    store, admin = credit_accounts
    create(store)
    with admin.connect() as connection:
        assert connection.execute(
            text(
                "SELECT relrowsecurity AND relforcerowsecurity AND "
                "pg_get_userbyid(relowner)='trading_migrator' FROM pg_class "
                "WHERE oid='app.credit_billing_accounts'::regclass"
            )
        ).scalar_one()
        for role in ("trading_auth",):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "TRIGGER"):
                assert not connection.execute(
                    text("SELECT has_table_privilege(:role,:table,:privilege)"),
                    dict(role=role, table=TABLE, privilege=privilege),
                ).scalar_one()
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.table_privileges "
                    "WHERE table_schema='app' AND table_name='credit_billing_accounts' "
                    "AND grantee='PUBLIC'"
                )
            ).scalar_one()
            == 0
        )
        for privilege in ("DELETE", "TRUNCATE", "TRIGGER"):
            assert not connection.execute(
                text("SELECT has_table_privilege('trading_runtime',:table,:privilege)"),
                dict(table=TABLE, privilege=privilege),
            ).scalar_one()
        for field in (
            "owner_id",
            "id",
            "issuer",
            "billing_currency",
            "label",
            "revision",
            "created_at",
            "updated_at",
        ):
            assert not connection.execute(
                text("SELECT has_column_privilege('trading_runtime',:table,:field,'UPDATE')"),
                dict(table=TABLE, field=field),
            ).scalar_one()
        for field in ("revision", "created_at", "updated_at", "archived_at"):
            assert not connection.execute(
                text("SELECT has_column_privilege('trading_runtime',:table,:field,'INSERT')"),
                dict(table=TABLE, field=field),
            ).scalar_one()
    url, _ = database
    for role in ("auth", "migrator"):
        engine = engine_for(url(role))
        try:
            with engine.begin() as connection:
                set_owner(connection, OWNER_A)
                if role == "auth":
                    with pytest.raises(DBAPIError):
                        connection.execute(text(f"SELECT * FROM {TABLE}"))
                else:
                    assert connection.execute(text(f"SELECT * FROM {TABLE}")).all() == []
        finally:
            engine.dispose()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE app.credit_billing_accounts SET owner_id=:other",
        "UPDATE app.credit_billing_accounts SET id=:other",
        "UPDATE app.credit_billing_accounts SET label='Replacement'",
        "UPDATE app.credit_billing_accounts SET issuer='sbi'",
        "UPDATE app.credit_billing_accounts SET billing_currency='USD'",
        "UPDATE app.credit_billing_accounts SET revision=2",
        "UPDATE app.credit_billing_accounts SET created_at=statement_timestamp()",
        "UPDATE app.credit_billing_accounts SET updated_at=statement_timestamp()",
        "UPDATE app.credit_billing_accounts SET archived_at=NULL",
        "UPDATE app.credit_billing_accounts SET archived_at=statement_timestamp()+interval '1 day'",
        "DELETE FROM app.credit_billing_accounts",
        "TRUNCATE app.credit_billing_accounts",
    ],
)
def test_direct_sql_cannot_rewrite_identity_or_bypass_archive_rules(credit_accounts, statement):
    store, _ = credit_accounts
    account = create(store)
    with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        connection.execute(text(statement), dict(other=OWNER_B))
    with store.transaction(OWNER_A) as unit:
        assert unit.get(account.id) == account


@pytest.mark.parametrize(
    "fields,values",
    [
        ("owner_id,id,issuer,billing_currency,label", ":other,:id,'hdfc','INR','Synthetic'"),
        ("owner_id,id,issuer,billing_currency,label", ":owner,:id,'sbi','INR','Synthetic'"),
        ("owner_id,id,issuer,billing_currency,label", ":owner,:id,'hdfc','USD','Synthetic'"),
        ("owner_id,id,issuer,billing_currency,label", ":owner,:id,'hdfc','INR','Card 0000'"),
        (
            "owner_id,id,issuer,billing_currency,label,revision",
            ":owner,:id,'hdfc','INR','Synthetic',1",
        ),
        (
            "owner_id,id,issuer,billing_currency,label,created_at",
            ":owner,:id,'hdfc','INR','Synthetic',statement_timestamp()",
        ),
        (
            "owner_id,id,issuer,billing_currency,label,archived_at",
            ":owner,:id,'hdfc','INR','Synthetic',NULL",
        ),
    ],
)
def test_direct_insert_rejects_foreign_owner_unsafe_values_or_server_fields(
    credit_accounts, fields, values
):
    store, _ = credit_accounts
    with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        connection.execute(
            text(f"INSERT INTO {TABLE} ({fields}) VALUES ({values})"),
            dict(owner=OWNER_A, other=OWNER_B, id=uuid4()),
        )


def test_concurrent_archive_has_one_winner(credit_accounts):
    store, _ = credit_accounts
    account = create(store)
    barrier = Barrier(2)

    def archive():
        barrier.wait(timeout=10)
        try:
            with store.transaction(OWNER_A) as unit:
                return unit.archive(account.id, expected_revision=1).revision
        except CreditAccountUnavailable:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: archive(), range(2)))
    assert sorted(map(str, results)) == ["2", "conflict"]


def test_direct_insert_budget_serializes_concurrent_admission(credit_accounts):
    store, admin = credit_accounts
    with admin.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO app.credit_billing_accounts "
                "(owner_id,id,issuer,billing_currency,label) "
                "SELECT :owner,md5('synthetic-credit-'||n::text)::uuid,"
                "'hdfc','INR','Synthetic billing' "
                "FROM generate_series(1,999) AS n"
            ),
            dict(owner=OWNER_A),
        )
    barrier = Barrier(2)

    def insert():
        barrier.wait(timeout=10)
        try:
            with store._workspace._engine.begin() as connection:
                set_owner(connection, OWNER_A)
                connection.execute(text(INSERT), dict(owner=OWNER_A, id=uuid4()))
            return "created"
        except DBAPIError:
            return "full"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: insert(), range(2))) == ["created", "full"]
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(CreditAccountUnavailable):
            unit.create(CreditAccountDefinition(label="Exceeds budget"))
    assert create(store, OWNER_B).revision == 1


def test_stale_repeatable_read_cannot_overrun_credit_admission_budget(credit_accounts):
    store, admin = credit_accounts
    with admin.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO app.credit_billing_accounts "
                "(owner_id,id,issuer,billing_currency,label) "
                "SELECT :owner,md5('synthetic-stale-credit-'||n::text)::uuid,"
                "'hdfc','INR','Synthetic billing' FROM generate_series(1,999) AS n"
            ),
            dict(owner=OWNER_A),
        )
    rejected = False
    with store._workspace._engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as stale:
        with stale.begin() as transaction:
            set_owner(stale, OWNER_A)
            assert stale.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 999
            with store._workspace._engine.begin() as current:
                set_owner(current, OWNER_A)
                current.execute(text(INSERT), dict(owner=OWNER_A, id=uuid4()))
            assert stale.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 999
            try:
                stale.execute(text(INSERT), dict(owner=OWNER_A, id=uuid4()))
            except DBAPIError as error:
                assert "Credit account operation is unavailable" in str(error.orig)
                transaction.rollback()
                rejected = True
    with admin.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 1000
    assert rejected


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
@pytest.mark.parametrize("operation", ["insert", "archive"])
def test_runtime_writes_require_read_committed_isolation(credit_accounts, isolation, operation):
    store, _ = credit_accounts
    account = create(store)
    with store._workspace._engine.connect().execution_options(
        isolation_level=isolation
    ) as connection:
        with pytest.raises(DBAPIError, match="Credit account operation is unavailable"):
            with connection.begin():
                set_owner(connection, OWNER_A)
                if operation == "insert":
                    connection.execute(text(INSERT), dict(owner=OWNER_A, id=uuid4()))
                else:
                    connection.execute(
                        text(f"UPDATE {TABLE} SET archived_at=statement_timestamp() WHERE id=:id"),
                        dict(id=account.id),
                    )
    with store.transaction(OWNER_A) as unit:
        assert unit.list() == (account,)


def write_across_owner_deactivation(
    store,
    admin,
    statement,
    parameters,
    control_parameters,
    lock_statement,
    lock_parameters,
    locktype,
):
    """Observe the exact blocked backend before deactivating its owner."""
    pending = Queue()

    def write():
        try:
            with store._workspace._engine.begin() as connection:
                set_owner(connection, OWNER_A)
                pending.put(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
                connection.execute(text(statement), parameters)
            return "committed"
        except DBAPIError as error:
            return error.orig.diag.message_primary

    with ThreadPoolExecutor(max_workers=1) as pool:
        with admin.begin() as blocker:
            blocker_pid = blocker.execute(text("SELECT pg_backend_pid()")).scalar_one()
            blocker.execute(text(lock_statement), lock_parameters)
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
                assert not future.done(), "Runtime write ended before the expected lock wait"
                sleep(0.01)
            else:
                pytest.fail("Runtime write did not reach the expected lock wait")
            # Another active owner can perform the same operation while A waits.
            with store._workspace._engine.begin() as control:
                set_owner(control, OWNER_B)
                control.execute(text(statement), control_parameters)
            blocker.execute(
                text("UPDATE app.owners SET is_active=false WHERE id=:owner"),
                dict(owner=OWNER_A),
            )
        return future.result(timeout=10)


@pytest.mark.parametrize("operation", ["insert", "archive"])
def test_runtime_credit_write_rechecks_owner_after_lock_wait(credit_accounts, operation):
    store, admin = credit_accounts
    if operation == "insert":
        own_id, other_id = uuid4(), uuid4()
        statement = INSERT
        lock_statement = (
            "SELECT pg_advisory_xact_lock("
            "hashtextextended('credit-accounts/v1:' || CAST(:owner AS text),0))"
        )
        lock_parameters, locktype = dict(owner=OWNER_A), "advisory"
    else:
        own_id, other_id = create(store).id, create(store, OWNER_B).id
        statement = (
            f"UPDATE {TABLE} SET archived_at=statement_timestamp() WHERE owner_id=:owner AND id=:id"
        )
        # Keep the target row unchanged: only owners.is_active changes at release.
        lock_statement = f"SELECT id FROM {TABLE} WHERE owner_id=:owner AND id=:id FOR UPDATE"
        lock_parameters = dict(owner=OWNER_A, id=own_id)
        locktype = "transactionid"
    outcome = write_across_owner_deactivation(
        store,
        admin,
        statement,
        dict(owner=OWNER_A, id=own_id),
        dict(owner=OWNER_B, id=other_id),
        lock_statement,
        lock_parameters,
        locktype,
    )
    with admin.connect() as connection:
        own = connection.execute(
            text(f"SELECT revision,archived_at FROM {TABLE} WHERE owner_id=:owner AND id=:id"),
            dict(owner=OWNER_A, id=own_id),
        ).one_or_none()
        other = connection.execute(
            text(f"SELECT revision,archived_at FROM {TABLE} WHERE owner_id=:owner AND id=:id"),
            dict(owner=OWNER_B, id=other_id),
        ).one()
        if operation == "insert":
            assert own is None, "Deactivated owner committed a new credit identity"
            assert tuple(other) == (1, None)
        else:
            assert tuple(own) == (1, None), "Deactivated owner committed archival"
            assert other.revision == 2 and other.archived_at is not None
    assert outcome == "Credit account operation is unavailable"
