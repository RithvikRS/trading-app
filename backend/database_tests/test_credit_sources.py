"""Credit-source ownership, immutable mappings, runtime SQL guards and bounded races."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_credit_accounts import create, write_across_owner_deactivation
from database_tests.test_credit_accounts import credit_accounts as credit_accounts
from database_tests.test_ownership import DISABLED, OWNER_A, OWNER_B, UNKNOWN, set_owner
from trading_db.connections import DatabaseFailure
from trading_db.credit_sources import CreditSourceDatabase, CreditSourceUnavailable
from trading_db.workspace import OwnerAccessDenied

HANDLES = "app.credit_source_handles"
MAPPINGS = "app.credit_source_account_mappings"
SOURCE_INSERT = (
    "INSERT INTO app.credit_source_handles (owner_id,id,family) "
    "VALUES (:owner,:id,'hdfc_credit_statement')"
)
MAPPING_INSERT = (
    "INSERT INTO app.credit_source_account_mappings "
    "(owner_id,source_id,revision,previous_revision,account_id,reason) "
    "VALUES (:owner,:source,:revision,:previous,:account,:reason)"
)


@pytest.fixture
def credit_sources(credit_accounts, database):
    accounts, admin = credit_accounts
    url, project = database
    store = CreditSourceDatabase(url("runtime"), project)
    try:
        yield store, accounts, admin
    finally:
        store.close()


def source(store, owner=OWNER_A):
    with store.transaction(owner) as unit:
        return unit.create()


def mapping_parameters(source_id, account_id, revision=1):
    return dict(
        owner=OWNER_A,
        source=source_id,
        account=account_id,
        revision=revision,
        previous=revision - 1 if revision > 1 else None,
        reason="initial" if revision == 1 else "correction" if account_id else "unlinked",
    )


def test_sources_remain_distinct_with_stable_pages_and_no_asset_source_rows(credit_sources):
    store, accounts, _ = credit_sources
    rows = [source(store) for _ in range(5)]
    assert len({row.id for row in rows}) == 5
    with store.transaction(OWNER_A) as unit:
        found, after = [], None
        while items := unit.list(limit=2, after=after):
            found.extend(items)
            after = items[-1].id
        assert found == sorted(rows, key=lambda item: item.id)
        assert all(unit.get(row.id) == row and unit.mapping(row.id) is None for row in found)
        assert all(unit.resolve(row.id) is None for row in found)
    with pytest.raises(DatabaseFailure, match="ended"):
        unit.get(rows[0].id)
    with accounts._workspace.transaction(OWNER_A) as workspace:
        assert (
            workspace._connection.execute(
                text("SELECT count(*) FROM app.source_accounts")
            ).scalar_one()
            == 0
        )


def test_mapping_history_is_append_only_with_explicit_unlink_and_archived_resolution(
    credit_sources,
):
    store, accounts, _ = credit_sources
    first, second = create(accounts), create(accounts)
    item = source(store)
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(CreditSourceUnavailable):
            unit.map(item.id, None, expected_revision=0)
        initial = unit.map(item.id, first.id, expected_revision=0)
        assert unit.map(item.id, first.id, expected_revision=1) == initial
        with pytest.raises(CreditSourceUnavailable):
            unit.map(item.id, second.id, expected_revision=0)
        corrected = unit.map(item.id, second.id, expected_revision=1)
        unlinked = unit.map(item.id, None, expected_revision=2)
        assert unit.resolve(item.id) is None
        assert unit.map(item.id, None, expected_revision=3) == unlinked
        restored = unit.map(item.id, first.id, expected_revision=3)
        assert unit.resolve(item.id) == restored
        assert unit.history(item.id, limit=2) == (restored, unlinked)
        assert unit.history(item.id, before=3) == (corrected, initial)
        assert unit.history(item.id, before=1) == ()
    with accounts.transaction(OWNER_A) as unit:
        unit.archive(first.id, expected_revision=1)
    with store.transaction(OWNER_A) as unit:
        assert unit.resolve(item.id) is None and unit.mapping(item.id) == restored
        assert unit.history(item.id)[-1] == initial
        with pytest.raises(CreditSourceUnavailable):
            unit.map(item.id, first.id, expected_revision=4)
        unit.map(item.id, second.id, expected_revision=4)


def test_two_owner_unknown_foreign_and_rollback_boundaries(credit_sources):
    store, accounts, _ = credit_sources
    own, foreign = source(store), source(store, OWNER_B)
    account, other_account = create(accounts), create(accounts, OWNER_B)
    with store.transaction(OWNER_A) as unit:
        for item in (foreign.id, uuid4()):
            assert unit.get(item) is None and unit.mapping(item) is None
            assert unit.history(item) == () and unit.resolve(item) is None
            with pytest.raises(CreditSourceUnavailable):
                unit.map(item, account.id, expected_revision=0)
        for target in (other_account.id, uuid4()):
            with pytest.raises(CreditSourceUnavailable) as error:
                unit.map(own.id, target, expected_revision=0)
            assert str(target) not in str(error.value)
        initial = unit.map(own.id, account.id, expected_revision=0)
    with pytest.raises(RuntimeError), store.transaction(OWNER_A) as unit:
        unit.create()
        unit.map(own.id, None, expected_revision=1)
        raise RuntimeError("Synthetic interruption")
    with store.transaction(OWNER_A) as unit:
        assert unit.list() == (own,) and unit.mapping(own.id) == initial
    with store.transaction(OWNER_B) as unit:
        assert unit.list() == (foreign,) and unit.resolve(own.id) is None


@pytest.mark.parametrize("owner", [DISABLED, UNKNOWN, None, str(OWNER_A)])
def test_disabled_unknown_or_invalid_owner_cannot_enter(credit_sources, owner):
    store, _, _ = credit_sources
    with pytest.raises(OwnerAccessDenied), store.transaction(owner):
        pytest.fail("Invalid owner entered")


@pytest.mark.parametrize("context", [None, "", "invalid", str(DISABLED), str(UNKNOWN)])
def test_sql_missing_or_inactive_context_cannot_read_or_insert(credit_sources, context):
    store, _, _ = credit_sources
    source(store)
    with store._workspace._engine.begin() as connection:
        if context is not None:
            set_owner(connection, context)
        for table in (HANDLES, MAPPINGS):
            assert connection.execute(text(f"SELECT * FROM {table}")).all() == []
        with pytest.raises(DBAPIError):
            connection.execute(text(SOURCE_INSERT), dict(owner=OWNER_A, id=uuid4()))


def test_forced_policies_migrator_ownership_and_narrow_grants(credit_sources):
    _, _, admin = credit_sources
    with admin.connect() as connection:
        for table in (HANDLES, MAPPINGS):
            assert connection.execute(
                text(
                    "SELECT relrowsecurity AND relforcerowsecurity AND "
                    "pg_get_userbyid(relowner)='trading_migrator' FROM pg_class "
                    "WHERE oid=CAST(:table AS regclass)"
                ),
                dict(table=table),
            ).scalar_one()
            for role in ("trading_auth", "PUBLIC"):
                assert (
                    connection.execute(
                        text(
                            "SELECT count(*) FROM information_schema.table_privileges "
                            "WHERE table_schema='app' AND table_name=:table AND grantee=:role"
                        ),
                        dict(table=table.removeprefix("app."), role=role),
                    ).scalar_one()
                    == 0
                )
            for privilege in ("UPDATE", "DELETE", "TRUNCATE", "TRIGGER"):
                assert not connection.execute(
                    text("SELECT has_table_privilege('trading_runtime',:table,:privilege)"),
                    dict(table=table, privilege=privilege),
                ).scalar_one()
            assert not connection.execute(
                text("SELECT has_column_privilege('trading_runtime',:table,'created_at','INSERT')"),
                dict(table=table),
            ).scalar_one()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE app.credit_source_handles SET family='hdfc_statement'",
        "UPDATE app.credit_source_account_mappings SET account_id=NULL",
        "DELETE FROM app.credit_source_handles",
        "DELETE FROM app.credit_source_account_mappings",
        "TRUNCATE app.credit_source_handles CASCADE",
        "TRUNCATE app.credit_source_account_mappings",
    ],
)
def test_runtime_cannot_rewrite_or_delete_history(credit_sources, statement):
    store, accounts, _ = credit_sources
    item, account = source(store), create(accounts)
    with store.transaction(OWNER_A) as unit:
        initial = unit.map(item.id, account.id, expected_revision=0)
    with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        connection.execute(text(statement))
    with store.transaction(OWNER_A) as unit:
        assert unit.get(item.id) == item and unit.history(item.id) == (initial,)


def test_sql_rejects_foreign_or_archived_bindings_gaps_and_redundant_revisions(credit_sources):
    store, accounts, _ = credit_sources
    item, foreign = source(store), source(store, OWNER_B)
    account, archived, other = create(accounts), create(accounts), create(accounts, OWNER_B)
    with accounts.transaction(OWNER_A) as unit:
        unit.archive(archived.id, expected_revision=1)
    with store.transaction(OWNER_A) as unit:
        initial = unit.map(item.id, account.id, expected_revision=0)
    cases = [
        mapping_parameters(item.id, account.id, 2),
        mapping_parameters(item.id, other.id, 2),
        mapping_parameters(item.id, archived.id, 2),
        mapping_parameters(item.id, uuid4(), 2),
        mapping_parameters(item.id, account.id, 3),
        mapping_parameters(foreign.id, account.id),
        mapping_parameters(uuid4(), account.id),
        mapping_parameters(item.id, None, 2) | {"previous": None},
        mapping_parameters(item.id, None, 2) | {"owner": OWNER_B},
        mapping_parameters(item.id, None, 2) | {"reason": "initial"},
    ]
    for params in cases:
        with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
            set_owner(connection, OWNER_A)
            connection.execute(text(MAPPING_INSERT), params)
    with store.transaction(OWNER_A) as unit:
        assert unit.history(item.id) == (initial,)
    for changes in ("'hdfc_statement'", "'0000000000000000'", "NULL"):
        with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
            set_owner(connection, OWNER_A)
            connection.execute(
                text(SOURCE_INSERT.replace("'hdfc_credit_statement'", changes)),
                dict(owner=OWNER_A, id=uuid4()),
            )


def test_concurrent_correction_and_unlink_have_one_winner(credit_sources):
    store, accounts, _ = credit_sources
    item, first, second = source(store), create(accounts), create(accounts)
    with store.transaction(OWNER_A) as unit:
        initial = unit.map(item.id, first.id, expected_revision=0)
    barrier = Barrier(2)

    def mutate(target):
        barrier.wait(timeout=10)
        try:
            with store.transaction(OWNER_A) as unit:
                return unit.map(item.id, target, expected_revision=1).revision
        except CreditSourceUnavailable:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(map(str, pool.map(mutate, (second.id, None)))) == ["2", "conflict"]
    with store.transaction(OWNER_A) as unit:
        assert len(unit.history(item.id)) == 2 and unit.history(item.id)[-1] == initial


def test_mapping_locks_account_until_commit_and_later_archival_is_historical(credit_sources):
    store, accounts, _ = credit_sources
    item, account = source(store), create(accounts)

    def archive_while_locked():
        with pytest.raises(DBAPIError, match="lock timeout"):
            with accounts._workspace._engine.begin() as connection:
                set_owner(connection, OWNER_A)
                connection.execute(text("SET LOCAL lock_timeout='100ms'"))
                connection.execute(
                    text(
                        "UPDATE app.credit_billing_accounts SET archived_at=statement_timestamp() "
                        "WHERE id=:id"
                    ),
                    dict(id=account.id),
                )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.transaction(OWNER_A) as unit:
            initial = unit.map(item.id, account.id, expected_revision=0)
            pool.submit(archive_while_locked).result(timeout=10)
    with accounts.transaction(OWNER_A) as unit:
        unit.archive(account.id, expected_revision=1)
    with store.transaction(OWNER_A) as unit:
        assert unit.mapping(item.id) == initial and unit.resolve(item.id) is None


def seed_budget(store, accounts, admin, table):
    if table == HANDLES:
        with admin.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO app.credit_source_handles (owner_id,id,family) "
                    "SELECT :owner,md5('synthetic-source-'||n::text)::uuid,"
                    "'hdfc_credit_statement' FROM generate_series(1,999) n"
                ),
                dict(owner=OWNER_A),
            )
        return SOURCE_INSERT, [dict(owner=OWNER_A, id=uuid4()) for _ in range(2)]
    first, second = create(accounts), create(accounts)
    initial, left, right = source(store), source(store), source(store)
    with admin.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO app.credit_source_account_mappings "
                "(owner_id,source_id,revision,previous_revision,account_id,reason) "
                "SELECT :owner,:source,n,CASE WHEN n=1 THEN NULL ELSE n-1 END,"
                "CASE WHEN n%2=1 THEN CAST(:first AS uuid) ELSE CAST(:second AS uuid) END,"
                "CASE WHEN n=1 THEN 'initial' ELSE 'correction' END FROM generate_series(1,999) n"
            ),
            dict(owner=OWNER_A, source=initial.id, first=first.id, second=second.id),
        )
    return MAPPING_INSERT, [mapping_parameters(item.id, first.id) for item in (left, right)]


@pytest.mark.parametrize("table", [HANDLES, MAPPINGS])
def test_direct_sql_admission_has_exactly_one_final_slot(credit_sources, table):
    store, accounts, admin = credit_sources
    sql, candidates = seed_budget(store, accounts, admin, table)
    barrier = Barrier(2)

    def insert(parameters):
        barrier.wait(timeout=10)
        try:
            with store._workspace._engine.begin() as connection:
                set_owner(connection, OWNER_A)
                connection.execute(text(sql), parameters)
            return "created"
        except DBAPIError:
            return "full"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(insert, candidates)) == ["created", "full"]
    with admin.connect() as connection:
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE owner_id=:owner"), dict(owner=OWNER_A)
            ).scalar_one()
            == 1000
        )


@pytest.mark.parametrize("table", [HANDLES, MAPPINGS])
def test_stale_repeatable_read_cannot_admit_a_thousand_and_first_row(credit_sources, table):
    store, accounts, admin = credit_sources
    sql, candidates = seed_budget(store, accounts, admin, table)
    with store._workspace._engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as stale:
        with stale.begin() as transaction:
            set_owner(stale, OWNER_A)
            assert stale.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 999
            with store._workspace._engine.begin() as current:
                set_owner(current, OWNER_A)
                current.execute(text(sql), candidates[0])
            assert stale.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 999
            with pytest.raises(DBAPIError, match="Credit source operation is unavailable"):
                stale.execute(text(sql), candidates[1])
            transaction.rollback()
    with admin.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 1000


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
@pytest.mark.parametrize("operation", ["source", "mapping"])
def test_runtime_insert_requires_read_committed(credit_sources, isolation, operation):
    store, accounts, _ = credit_sources
    item, account = source(store), create(accounts)
    with store._workspace._engine.connect().execution_options(
        isolation_level=isolation
    ) as connection:
        with (
            pytest.raises(DBAPIError, match="Credit source operation is unavailable"),
            connection.begin(),
        ):
            set_owner(connection, OWNER_A)
            connection.execute(
                text(SOURCE_INSERT if operation == "source" else MAPPING_INSERT),
                dict(owner=OWNER_A, id=uuid4())
                if operation == "source"
                else mapping_parameters(item.id, account.id),
            )
    with store.transaction(OWNER_A) as unit:
        assert unit.list() == (item,) and unit.mapping(item.id) is None


@pytest.mark.parametrize("operation", ["source", "mapping_owner_lock", "mapping_account_lock"])
def test_runtime_source_write_rechecks_owner_after_lock_wait(credit_sources, operation):
    store, accounts, admin = credit_sources
    if operation == "source":
        statement, table = SOURCE_INSERT, HANDLES
        own = dict(owner=OWNER_A, id=uuid4())
        other = dict(owner=OWNER_B, id=uuid4())
    else:
        statement, table = MAPPING_INSERT, MAPPINGS
        own = mapping_parameters(source(store).id, create(accounts).id)
        other = mapping_parameters(source(store, OWNER_B).id, create(accounts, OWNER_B).id)
        other["owner"] = OWNER_B
    if operation == "mapping_account_lock":
        # A row lock alone must not refresh the outer INSERT/RLS snapshot.
        lock_statement = (
            "SELECT id FROM app.credit_billing_accounts WHERE owner_id=:owner AND id=:id FOR UPDATE"
        )
        lock_parameters, locktype = dict(owner=OWNER_A, id=own["account"]), "transactionid"
    else:
        lock_statement = (
            "SELECT pg_advisory_xact_lock("
            "hashtextextended('credit-accounts/v1:' || CAST(:owner AS text),0))"
        )
        lock_parameters, locktype = dict(owner=OWNER_A), "advisory"
    outcome = write_across_owner_deactivation(
        store,
        admin,
        statement,
        own,
        other,
        lock_statement,
        lock_parameters,
        locktype,
    )
    with admin.connect() as connection:
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE owner_id=:owner"),
                dict(owner=OWNER_A),
            ).scalar_one()
            == 0
        ), "Deactivated owner committed a credit source write"
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE owner_id=:owner"),
                dict(owner=OWNER_B),
            ).scalar_one()
            == 1
        )
    assert outcome == "Credit source operation is unavailable"
