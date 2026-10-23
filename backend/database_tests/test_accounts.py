"""Real PostgreSQL account ownership, append-only mappings, concurrency and key rotation."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_ownership import DISABLED, OWNER_A, OWNER_B, UNKNOWN, set_owner
from trading_db import migrate
from trading_db.account_keys import ReferenceKeys, ReferenceUnavailable
from trading_db.accounts import AccountDatabase, AccountDefinition, AccountUnavailable
from trading_db.connections import DatabaseFailure, engine_for
from trading_db.workspace import OwnerAccessDenied

TABLES = ("financial_accounts", "account_currencies", "source_accounts", "source_account_mappings")


def definition(kind="bank", institution="hdfc", market="IN", currencies=("INR",)):
    return AccountDefinition(
        kind=kind,
        institution=institution,
        market=market,
        label="Synthetic account",
        currencies=currencies,
    )


@pytest.fixture
def accounts(database):
    url, project = database
    migrate.apply(url(), project)
    admin = engine_for(url("bootstrap"), migration=True)
    with admin.begin() as connection:
        for owner, active in ((OWNER_A, True), (OWNER_B, True), (DISABLED, False)):
            connection.execute(
                text("INSERT INTO app.owners (id,is_active) VALUES (:id,:active)"),
                dict(id=owner, active=active),
            )
    store = AccountDatabase(url("runtime"), project, ReferenceKeys({1: b"a" * 32}, 1))
    try:
        yield store, admin
    finally:
        store.close()
        admin.dispose()


def seed(store, owner=OWNER_A):
    with store.transaction(owner) as unit:
        account = unit.create(definition())
        source = unit.source("hdfc_statement", "FAKE-0001")
        unit.map(source.id, account.id, expected_revision=0)
    return account, source


def test_accounts_keep_institutions_markets_and_currencies_distinct(accounts):
    store, _ = accounts
    cases = [
        definition(),
        definition(institution="sbi"),
        definition("brokerage", "indmoney"),
        definition("brokerage", "indmoney", "US", ("USD", "INR")),
        definition("employee_stock", "ubs", "US", ("USD",)),
        definition("mutual_fund", "fund_registrar"),
    ]
    with store.transaction(OWNER_A) as unit:
        created = [unit.create(case) for case in cases]
        assert len({account.id for account in created}) == 6
        seen = []
        after = None
        while rows := unit.list(limit=2, after=after):
            seen.extend(rows)
            after = rows[-1].id
        assert {account.id for account in seen} == {account.id for account in created}
        for account in created:
            saved = unit.get(account.id)
            assert saved.definition.currencies == tuple(sorted(account.definition.currencies))
    store.close()
    with store.transaction(OWNER_A) as unit:
        assert len(unit.list()) == 6


def test_multiple_sources_mapping_corrections_unlink_and_archive_preserve_history(accounts):
    store, _ = accounts
    with store.transaction(OWNER_A) as unit:
        first, second = [unit.create(definition("mutual_fund", "fund_registrar")) for _ in range(2)]
        cas, advisor = [unit.source(name, "FAKE-001") for name in ("cas", "advisor")]
        assert cas.id != advisor.id
        unit.map(cas.id, first.id, expected_revision=0)
        unit.map(advisor.id, first.id, expected_revision=0)
        assert unit.map(cas.id, second.id, expected_revision=1).revision == 2
        assert unit.map(cas.id, second.id, expected_revision=2).revision == 2
        assert unit.map(cas.id, None, expected_revision=2).reason == "unlinked"
        assert unit.map(cas.id, first.id, expected_revision=3).revision == 4
        archived = unit.archive(first.id, expected_revision=1)
        assert archived.revision == 2 and archived.archived_at is not None
        assert unit.mapping(advisor.id).account_id == first.id
        assert [r.revision for r in unit.history(cas.id, limit=2)] == [4, 3]
        assert [r.revision for r in unit.history(cas.id, before=3)] == [2, 1]
        new = unit.source("cas", "FAKE-002")
        with pytest.raises(AccountUnavailable):
            unit.map(new.id, first.id, expected_revision=0)
        with pytest.raises(AccountUnavailable):
            unit.archive(first.id, expected_revision=2)
        assert unit.get(second.id).archived_at is None


def test_cross_owner_reads_and_writes_do_not_reveal_or_link_foreign_records(accounts):
    store, _ = accounts
    own, source = seed(store)
    other, foreign = seed(store, OWNER_B)
    with store.transaction(OWNER_A) as unit:
        assert unit.get(other.id) == unit.get(uuid4()) is None
        assert unit.mapping(foreign.id) == unit.mapping(uuid4()) is None
        assert unit.history(foreign.id) == ()
        assert len(unit.list()) == len(unit.sources()) == 1
        for source_id, account_id in ((source.id, other.id), (foreign.id, own.id)):
            with pytest.raises(AccountUnavailable) as failure:
                unit.map(source_id, account_id, expected_revision=1)
            assert str(other.id) not in str(failure.value)
        assert unit.mapping(source.id).account_id == own.id
    assert source.id != foreign.id


@pytest.mark.parametrize("owner", [DISABLED, UNKNOWN, None, str(OWNER_A)])
def test_unknown_disabled_and_missing_owner_rejected(accounts, owner):
    store, _ = accounts
    with pytest.raises(OwnerAccessDenied), store.transaction(owner):
        pytest.fail("Invalid owner entered transaction")


@pytest.mark.parametrize("context", [None, "", "invalid", str(DISABLED), str(UNKNOWN)])
def test_missing_owner_context_reads_nothing_and_cannot_insert(accounts, context):
    store, _ = accounts
    seed(store)
    with store._workspace._engine.begin() as connection:
        if context is not None:
            set_owner(connection, context)
        for table in TABLES:
            assert connection.execute(text(f"SELECT * FROM app.{table}")).all() == []
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    "INSERT INTO app.source_accounts "
                    "(owner_id,id,namespace,key_version,key_check,fingerprint,encrypted_reference) "
                    "VALUES (:owner,:id,'cas',1,:digest,:digest,:encrypted)"
                ),
                dict(owner=OWNER_A, id=uuid4(), digest="a" * 64, encrypted="a" * 40),
            )


def test_forced_policies_restricted_roles_and_column_grants(accounts, database):
    store, admin = accounts
    seed(store)
    url, project = database
    with admin.connect() as connection:
        for table in TABLES:
            assert connection.execute(
                text(
                    "SELECT relrowsecurity AND relforcerowsecurity "
                    "AND pg_get_userbyid(relowner)='trading_migrator' FROM pg_class "
                    "WHERE oid=CAST(:table AS regclass)"
                ),
                dict(table="app." + table),
            ).scalar_one()
            for role in ("trading_auth",):
                assert not connection.execute(
                    text("SELECT has_table_privilege(:role,:table,'SELECT')"),
                    dict(role=role, table="app." + table),
                ).scalar_one()
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM information_schema.table_privileges "
                        "WHERE table_schema='app' AND table_name=:table AND grantee='PUBLIC'"
                    ),
                    dict(table=table),
                ).scalar_one()
                == 0
            )
            for privilege in ("DELETE", "TRUNCATE", "TRIGGER"):
                assert not connection.execute(
                    text("SELECT has_table_privilege('trading_runtime',:table,:privilege)"),
                    dict(table="app." + table, privilege=privilege),
                ).scalar_one()
            assert not connection.execute(
                text("SELECT has_column_privilege('trading_runtime',:table,'owner_id','UPDATE')"),
                dict(table="app." + table),
            ).scalar_one()
    for role in ("auth", "migrator"):
        engine = engine_for(url(role))
        try:
            with engine.begin() as connection:
                set_owner(connection, OWNER_A)
                if role == "auth":
                    with pytest.raises(DBAPIError):
                        connection.execute(text("SELECT * FROM app.financial_accounts"))
                else:
                    assert (
                        connection.execute(text("SELECT * FROM app.financial_accounts")).all() == []
                    )
        finally:
            engine.dispose()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE app.financial_accounts SET owner_id=:other",
        "UPDATE app.financial_accounts SET label='Replacement'",
        "UPDATE app.source_accounts SET namespace='cas'",
        "UPDATE app.source_account_mappings SET account_id=:foreign",
        "DELETE FROM app.source_account_mappings",
        "TRUNCATE app.financial_accounts",
        "INSERT INTO app.account_currencies VALUES (:own,:foreign,'USD')",
        "INSERT INTO app.account_currencies VALUES (:other,:foreign,'USD')",
        "INSERT INTO app.account_currencies VALUES (:own,:account,'EUR')",
        "INSERT INTO app.source_account_mappings (owner_id,source_id,revision,previous_revision,"
        "account_id,reason) VALUES (:own,:source,2,1,:foreign,'correction')",
        "INSERT INTO app.source_account_mappings (owner_id,source_id,revision,previous_revision,"
        "account_id,reason) VALUES (:own,:source,3,1,:account,'correction')",
    ],
)
def test_raw_sql_cannot_bypass_ownership_immutability_or_native_currency(accounts, statement):
    store, _ = accounts
    account, source = seed(store)
    foreign, _ = seed(store, OWNER_B)
    with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        connection.execute(
            text(statement),
            dict(
                own=OWNER_A, other=OWNER_B, account=account.id, source=source.id, foreign=foreign.id
            ),
        )


def test_required_currency_and_mapping_chain_are_checked_at_commit(accounts):
    store, _ = accounts
    account, source = seed(store)
    for statement in (
        "INSERT INTO app.financial_accounts (owner_id,id,kind,institution,market,label) "
        "VALUES (:owner,:id,'bank','sbi','IN','Synthetic')",
        "INSERT INTO app.source_account_mappings (owner_id,source_id,revision,previous_revision,"
        "account_id,reason) VALUES (:owner,:source,3,2,:account,'correction')",
    ):
        with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
            set_owner(connection, OWNER_A)
            connection.execute(
                text(statement),
                dict(owner=OWNER_A, id=uuid4(), source=source.id, account=account.id),
            )


@pytest.mark.parametrize(
    "namespace", ["sbi_statement", "indmoney_india", "indmoney_us", "ubs_espp", "cas"]
)
def test_mapping_rejects_incompatible_account_namespace(accounts, namespace):
    store, _ = accounts
    account, _ = seed(store)
    with store.transaction(OWNER_A) as unit:
        source = unit.source(namespace, "FAKE-0002")
        with pytest.raises(AccountUnavailable):
            unit.map(source.id, account.id, expected_revision=0)
        assert unit.mapping(source.id) is None


def test_source_replay_rotation_missing_key_and_ciphertext_tampering(accounts, database):
    store, admin = accounts
    _, source = seed(store)
    url, project = database
    with store.transaction(OWNER_A) as unit:
        assert unit.source("hdfc_statement", "FAKE-0001").id == source.id
        unit.source("cas", "FAKE-FOLIO")
    for keys in (None, ReferenceKeys({1: b"x" * 32}, 1), ReferenceKeys({2: b"b" * 32}, 2)):
        broken = AccountDatabase(url("runtime"), project, keys)
        try:
            with broken.transaction(OWNER_A) as unit, pytest.raises(ReferenceUnavailable):
                unit.source("hdfc_statement", "FAKE-0001")
        finally:
            broken.close()
    rotating = AccountDatabase(
        url("runtime"), project, ReferenceKeys({1: b"a" * 32, 2: b"b" * 32}, 2)
    )
    try:
        with rotating.transaction(OWNER_A) as unit:
            assert unit.rotate_references() == 2
            assert unit.rotate_references() == 0
            replay = unit.source("hdfc_statement", "FAKE-0001")
            assert replay.id == source.id and replay.revision == 2
            assert unit.mapping(source.id).revision == 1
        with admin.begin() as connection:
            connection.execute(
                text("UPDATE app.source_accounts SET encrypted_reference=:value WHERE id=:id"),
                dict(value="a" * 80, id=source.id),
            )
        with rotating.transaction(OWNER_A) as unit, pytest.raises(ReferenceUnavailable):
            unit.source("hdfc_statement", "FAKE-0001")
    finally:
        rotating.close()


def test_digest_collision_cannot_silently_merge_different_references(accounts, monkeypatch):
    store, _ = accounts
    monkeypatch.setattr(ReferenceKeys, "fingerprint", lambda *args: "a" * 64)
    with store.transaction(OWNER_A) as unit:
        first = unit.source("cas", "FAKE-ONE")
        with pytest.raises(AccountUnavailable):
            unit.source("cas", "FAKE-TWO")
        assert unit.source("cas", "FAKE-ONE").id == first.id
        assert len(unit.sources()) == 1


def test_damaged_fingerprint_cannot_turn_an_existing_reference_into_a_new_source(accounts):
    store, admin = accounts
    _, source = seed(store)
    with admin.begin() as connection:
        connection.execute(
            text("UPDATE app.source_accounts SET fingerprint=:digest WHERE id=:id"),
            dict(digest="0" * 64, id=source.id),
        )
    with store.transaction(OWNER_A) as unit:
        for value in ("FAKE-0001", "FAKE-NEW"):
            with pytest.raises(ReferenceUnavailable):
                unit.source("hdfc_statement", value)
        assert len(unit.sources()) == 1


def test_rotation_failure_rolls_back_every_reference_and_concurrent_replay_is_safe(
    accounts, database, monkeypatch
):
    store, admin = accounts
    _, source = seed(store)
    with store.transaction(OWNER_A) as unit:
        unit.source("cas", "FAKE-FOLIO")
        first = unit.sources(limit=1)[0]
        assert len(unit.sources(after=first.id)) == 1
    url, project = database
    keys = ReferenceKeys({1: b"a" * 32, 2: b"b" * 32}, 2)
    rotating = AccountDatabase(url("runtime"), project, keys)
    try:
        with rotating.transaction(OWNER_A) as unit:
            original = unit._execute
            updates = 0

            def fail(sql, **parameters):
                nonlocal updates
                if sql.startswith("UPDATE app.source_accounts"):
                    updates += 1
                    if updates == 2:
                        raise RuntimeError("Synthetic rotation failure")
                return original(sql, **parameters)

            monkeypatch.setattr(unit, "_execute", fail)
            with pytest.raises(RuntimeError):
                unit.rotate_references()
            monkeypatch.setattr(unit, "_execute", original)
            assert [item.revision for item in unit.sources()] == [1, 1]
        with admin.connect() as connection:
            assert connection.execute(
                text("SELECT DISTINCT key_version FROM app.source_accounts")
            ).scalars().all() == [1]
        barrier = Barrier(2)

        def action(rotate):
            barrier.wait(timeout=10)
            with rotating.transaction(OWNER_A) as unit:
                return (
                    unit.rotate_references()
                    if rotate
                    else unit.source("hdfc_statement", "FAKE-0001").id
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            changed, replay = list(pool.map(action, (True, False)))
        assert changed == 2 and replay == source.id
        with rotating.transaction(OWNER_A) as unit:
            assert len(unit.sources()) == 2
            assert unit.rotate_references() == 0
    finally:
        rotating.close()


def test_record_limits_and_stale_archive_fail_without_partial_changes(accounts, monkeypatch):
    store, _ = accounts
    account, source = seed(store)
    monkeypatch.setattr("trading_db.accounts.MAX_RECORDS", 1)
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(AccountUnavailable):
            unit.create(definition())
        with pytest.raises(AccountUnavailable):
            unit.source("cas", "FAKE-NEW")
        with pytest.raises(AccountUnavailable):
            unit.map(source.id, None, expected_revision=1)
        with pytest.raises(AccountUnavailable):
            unit.archive(account.id, expected_revision=2)
        assert unit.get(account.id).archived_at is None
        assert unit.mapping(source.id).revision == 1


def test_concurrent_replay_and_stale_corrections_are_serialized(accounts):
    store, _ = accounts
    barrier = Barrier(2)

    def replay(_):
        barrier.wait(timeout=10)
        with store.transaction(OWNER_A) as unit:
            return unit.source("cas", "FAKE-SAME").id

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(replay, range(2)))
    assert first == second
    with store.transaction(OWNER_A) as unit:
        accounts_to_map = [
            unit.create(definition("mutual_fund", "fund_registrar")) for _ in range(2)
        ]

    def map_once(account):
        barrier.wait(timeout=10)
        try:
            with store.transaction(OWNER_A) as unit:
                return unit.map(first, account.id, expected_revision=0).revision
        except AccountUnavailable:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(map_once, accounts_to_map))
    assert results.count(1) == results.count("conflict") == 1


def test_rollback_savepoints_and_lifetime_do_not_leak_owner_or_partial_writes(
    accounts, monkeypatch
):
    store, _ = accounts
    account, source = seed(store)
    with pytest.raises(RuntimeError), store.transaction(OWNER_A) as unit:
        unit.create(definition(institution="sbi"))
        unit.map(source.id, None, expected_revision=1)
        raise RuntimeError("Synthetic cancellation")
    with pytest.raises(DatabaseFailure, match="ended"):
        unit.list()
    with store.transaction(OWNER_A) as unit:
        assert len(unit.list()) == 1
        assert unit.mapping(source.id).account_id == account.id
        original = unit._execute

        def fail(sql, **parameters):
            if sql.startswith("INSERT INTO app.account_currencies"):
                raise RuntimeError("Synthetic second-write failure")
            return original(sql, **parameters)

        monkeypatch.setattr(unit, "_execute", fail)
        with pytest.raises(RuntimeError):
            unit.create(definition(institution="sbi"))
        monkeypatch.setattr(unit, "_execute", original)
        assert len(unit.list()) == 1
    with store._workspace._engine.begin() as connection:
        assert connection.execute(text("SELECT app.current_owner_id()")).scalar_one() is None
        assert connection.execute(text("SELECT * FROM app.financial_accounts")).all() == []


def test_accounts_upgrade_is_repeatable_preserves_preferences_and_rolls_back_atomically(
    database, monkeypatch
):
    url, project = database
    migrate.apply(url(), project, target="0005_preference_revisions")
    admin = engine_for(url("bootstrap"), migration=True)
    try:
        with admin.begin() as connection:
            connection.execute(
                text("INSERT INTO app.owners (id,is_active) VALUES (:id,true)"), dict(id=OWNER_A)
            )
            connection.execute(
                text(
                    "INSERT INTO app.workspace_preferences (owner_id,theme,revision) "
                    "VALUES (:id,'dark',7)"
                ),
                dict(id=OWNER_A),
            )
        from alembic.operations import Operations

        original = Operations.execute

        def fail(self, statement, *args, **kwargs):
            result = original(self, statement, *args, **kwargs)
            if "CREATE TABLE app.source_accounts" in str(statement):
                raise RuntimeError("Synthetic migration failure")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(Operations, "execute", fail)
            with pytest.raises(RuntimeError):
                migrate.apply(url(), project)
        assert migrate.revision(url(), project) == "0005_preference_revisions"
        with admin.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT to_regclass('app.financial_accounts')")
                ).scalar_one()
                is None
            )
        for _ in range(2):
            migrate.apply(url(), project)
            migrate.apply(url(), project)
            with admin.connect() as connection:
                assert tuple(
                    connection.execute(
                        text("SELECT theme,revision FROM app.workspace_preferences")
                    ).one()
                ) == ("dark", 7)
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM app.financial_accounts")
                    ).scalar_one()
                    == 0
                )
            migrate.apply(url(), project, direction="downgrade", target="0005_preference_revisions")
    finally:
        admin.dispose()
