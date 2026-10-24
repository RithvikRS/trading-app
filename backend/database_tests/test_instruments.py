"""Database identity separation, source correction history and owner constraints."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_accounts import definition
from database_tests.test_ownership import DISABLED, OWNER_A, OWNER_B, UNKNOWN, set_owner
from trading_db import migrate
from trading_db.connections import DatabaseFailure, engine_for
from trading_db.instruments import (
    IdentifierDefinition,
    InstrumentDatabase,
    InstrumentDefinition,
    InstrumentUnavailable,
    ListingDefinition,
    SchemeDefinition,
)
from trading_db.workspace import OwnerAccessDenied

TABLES = (
    "fund_schemes",
    "instruments",
    "instrument_listings",
    "instrument_identifiers",
    "instrument_mappings",
    "account_positions",
)
# Fabricated, unassigned identifiers with valid check digits; no registry claim.
ISINS = (
    "ZZ0000000016",
    "ZZ0000000024",
    "ZZ0000000032",
    "ZZ0000000040",
    "ZZ0000000057",
    "ZZ0000000065",
)


def security(index=0, kind="equity", **fields):
    return InstrumentDefinition(
        name="Synthetic security", asset_class=kind, isin=ISINS[index], **fields
    )


@pytest.fixture
def instruments(accounts, database):
    url, project = database
    store = InstrumentDatabase(url("runtime"), project)
    try:
        yield store, *accounts
    finally:
        store.close()


def seed(store, accounts, owner=OWNER_A):
    with accounts.transaction(owner) as unit:
        account = unit.create(definition("brokerage", "indmoney", "US", ("USD",)))
    with store.transaction(owner) as unit:
        instrument = unit.create(security())
        listing = unit.listing(
            instrument.id, ListingDefinition(venue="XNYS", symbol="FAKE", quote_currency="USD")
        )
        reference = unit.identifier(
            IdentifierDefinition(namespace="indmoney_us", value="FAKE-SECURITY")
        )
        unit.map(reference.id, instrument.id, expected_revision=0, listing_id=listing.id)
        position = unit.position(account.id, instrument.id, "custody")
    return account, instrument, listing, reference, position


def test_same_name_or_ticker_does_not_merge_and_exact_replay_is_idempotent(instruments):
    store, accounts, _ = instruments
    _, first, listing, reference, _ = seed(store, accounts)
    with store.transaction(OWNER_A) as unit:
        second = unit.create(security(1))
        alternate = unit.listing(second.id, listing.definition)
        assert first.id != second.id and listing.id != alternate.id
        assert unit.create(security()).id == first.id
        assert unit.listing(first.id, listing.definition).id == listing.id
        assert unit.identifier(reference.definition).id == reference.id
        assert unit.by_isin(first.definition.isin).id == first.id
        with pytest.raises(InstrumentUnavailable):
            unit.create(security(kind="etf"))
        with pytest.raises(InstrumentUnavailable):
            unit.create(security().model_copy(update={"name": "Conflicting name"}))
        assert len(unit.list()) == 2
        first_page = unit.list(limit=1)
        assert len(unit.list(after=first_page[0].id)) == 1
        assert len(unit.listings(first.id)) == 1


def test_all_fund_variants_remain_distinct_and_amfi_options_cannot_collapse(instruments):
    store, _, _ = instruments
    with store.transaction(OWNER_A) as unit:
        scheme = unit.scheme(SchemeDefinition(name="Synthetic scheme"))
        assert unit.scheme(scheme.definition).id != scheme.id
        assert unit.get_scheme(scheme.id) == scheme
        assert len(unit.schemes(limit=1)) == 1
        assert len(unit.schemes(after=unit.schemes(limit=1)[0].id)) == 1
        variants = []
        for plan in ("direct", "regular"):
            for option in ("growth", "idcw_payout", "idcw_reinvestment"):
                variants.append(
                    unit.create(
                        security(
                            len(variants),
                            "mutual_fund",
                            fund_scheme_id=scheme.id,
                            fund_plan=plan,
                            fund_option=option,
                            fund_currency="INR",
                        )
                    )
                )
        assert len({item.id for item in variants}) == 6
        # Distribution cadence/share classes can differ under the same plan/option.
        # The actual security identifier, not the descriptive grouping, keeps them apart.
        another_payout = unit.create(
            variants[1].definition.model_copy(
                update={
                    "isin": "ZZ0000000073",
                    "name": "Synthetic Monthly Distribution",
                }
            )
        )
        assert another_payout.id != variants[1].id
        payout = unit.identifier(
            IdentifierDefinition(namespace="amfi_nav", value="00123", qualifier="idcw_payout")
        )
        reinvest = unit.identifier(
            IdentifierDefinition(namespace="amfi_nav", value="00123", qualifier="idcw_reinvestment")
        )
        assert payout.id != reinvest.id
        unit.map(payout.id, variants[1].id, expected_revision=0)
        unit.map(reinvest.id, variants[2].id, expected_revision=0)
        with pytest.raises(InstrumentUnavailable):
            unit.map(payout.id, variants[2].id, expected_revision=1)
        with pytest.raises(InstrumentUnavailable):
            unit.listing(
                variants[0].id, ListingDefinition(venue="XNSE", symbol="FAKE", quote_currency="INR")
            )


def test_position_identity_is_account_specific_and_does_not_count_listings_twice(instruments):
    store, accounts, _ = instruments
    first, security_record, listing, _, position = seed(store, accounts)
    with accounts.transaction(OWNER_A) as unit:
        employee = unit.create(definition("employee_stock", "ubs", "US", ("USD",)))
    with store.transaction(OWNER_A) as unit:
        employee_position = unit.position(employee.id, security_record.id, "custody")
        assert position.id != employee_position.id
        assert unit.position(first.id, security_record.id, "custody").id == position.id
        second_listing = unit.listing(
            security_record.id, listing.definition.model_copy(update={"venue": "XNAS"})
        )
        assert second_listing.id != listing.id
        assert len(unit.positions(first.id)) == 1
        assert len(unit.listings(security_record.id)) == 2
    with accounts.transaction(OWNER_A) as unit:
        unit.archive(first.id, expected_revision=1)
    with store.transaction(OWNER_A) as unit:
        second = unit.create(security(1))
        with pytest.raises(InstrumentUnavailable):
            unit.position(first.id, second.id, "custody")
        assert unit.positions(first.id)[0].id == position.id


def test_mapping_revisions_correct_unlink_and_reject_stale_or_wrong_listing(instruments):
    store, accounts, _ = instruments
    _, first, listing, reference, _ = seed(store, accounts)
    with store.transaction(OWNER_A) as unit:
        second = unit.create(security(1))
        with pytest.raises(InstrumentUnavailable):
            unit.map(reference.id, second.id, expected_revision=1, listing_id=listing.id)
        assert unit.map(reference.id, second.id, expected_revision=1).revision == 2
        assert unit.map(reference.id, second.id, expected_revision=2).revision == 2
        with pytest.raises(InstrumentUnavailable):
            unit.map(reference.id, first.id, expected_revision=1)
        assert unit.map(reference.id, None, expected_revision=2).reason == "unlinked"
        assert (
            unit.map(reference.id, first.id, expected_revision=3, listing_id=listing.id).revision
            == 4
        )
        assert [item.revision for item in unit.history(reference.id, limit=2)] == [4, 3]
        assert [item.revision for item in unit.history(reference.id, before=3)] == [2, 1]


def test_owner_isolation_includes_every_parent_and_lookup(instruments):
    store, accounts, _ = instruments
    own = seed(store, accounts)
    foreign = seed(store, accounts, OWNER_B)
    with store.transaction(OWNER_B) as unit:
        foreign_scheme = unit.scheme(SchemeDefinition(name="Synthetic foreign scheme"))
    with store.transaction(OWNER_A) as unit:
        assert unit.get_scheme(foreign_scheme.id) == unit.get_scheme(uuid4()) is None
        assert unit.schemes() == ()
        with pytest.raises(InstrumentUnavailable):
            unit.create(
                security(
                    1,
                    "mutual_fund",
                    fund_scheme_id=foreign_scheme.id,
                    fund_plan="direct",
                    fund_option="growth",
                    fund_currency="INR",
                )
            )
        assert unit.get(foreign[1].id) == unit.get(uuid4()) is None
        assert unit.listings(foreign[1].id) == ()
        assert unit.positions(foreign[0].id) == ()
        assert unit.mapping(foreign[3].id) == unit.mapping(uuid4()) is None
        assert unit.history(foreign[3].id) == ()
        assert unit.by_isin(ISINS[0]).id == own[1].id
        for reference_id, instrument_id, listing_id in (
            (own[3].id, foreign[1].id, None),
            (foreign[3].id, own[1].id, None),
            (own[3].id, own[1].id, foreign[2].id),
        ):
            with pytest.raises(InstrumentUnavailable):
                unit.map(reference_id, instrument_id, expected_revision=1, listing_id=listing_id)
        for account_id, instrument_id in ((own[0].id, foreign[1].id), (foreign[0].id, own[1].id)):
            with pytest.raises(InstrumentUnavailable):
                unit.position(account_id, instrument_id, "custody")


@pytest.mark.parametrize("owner", [DISABLED, UNKNOWN, None])
def test_unknown_owner_cannot_enter_instrument_service(instruments, owner):
    store, _, _ = instruments
    with pytest.raises(OwnerAccessDenied), store.transaction(owner):
        pytest.fail("Invalid owner entered transaction")


@pytest.mark.parametrize("context", [None, "", "invalid", str(DISABLED), str(UNKNOWN)])
def test_raw_queries_without_active_owner_reveal_no_records(instruments, context):
    store, accounts, _ = instruments
    seed(store, accounts)
    with store._workspace._engine.begin() as connection:
        if context is not None:
            set_owner(connection, context)
        for table in TABLES:
            assert connection.execute(text(f"SELECT * FROM app.{table}")).all() == []
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    "INSERT INTO app.fund_schemes (owner_id,id,name) "
                    "VALUES (:owner,:id,'Synthetic')"
                ),
                dict(owner=OWNER_A, id=uuid4()),
            )


@pytest.mark.parametrize("table", TABLES)
def test_all_tables_force_rls_deny_auth_and_disallow_update_delete(instruments, table):
    _, _, admin = instruments
    with admin.connect() as connection:
        assert connection.execute(
            text(
                "SELECT relrowsecurity AND relforcerowsecurity "
                "AND pg_get_userbyid(relowner)='trading_migrator' FROM pg_class "
                "WHERE oid=CAST(:table AS regclass)"
            ),
            dict(table="app." + table),
        ).scalar_one()
        for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not connection.execute(
                text("SELECT has_table_privilege('trading_runtime',:table,:privilege)"),
                dict(table="app." + table, privilege=privilege),
            ).scalar_one()
        assert not connection.execute(
            text("SELECT has_table_privilege('trading_auth',:table,'SELECT')"),
            dict(table="app." + table),
        ).scalar_one()
        assert not connection.execute(
            text("SELECT has_column_privilege('trading_runtime',:table,'created_at','INSERT')"),
            dict(table="app." + table),
        ).scalar_one()


@pytest.mark.parametrize(
    "isin", ["US0378331004", "us0378331005", "US0378331005\n", "", "US03783310055"]
)
def test_direct_sql_rejects_bad_isin_before_commit(instruments, isin):
    store, _, _ = instruments
    with store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    "INSERT INTO app.instruments (owner_id,id,asset_class,name,isin) "
                    "VALUES (:owner,:id,'equity','Synthetic',:isin)"
                ),
                dict(owner=OWNER_A, id=uuid4(), isin=isin),
            )


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO app.instrument_listings "
        "(owner_id,id,instrument_id,venue,symbol,series,quote_currency) "
        "VALUES (:own,:id,:foreign_instrument,'XNYS','FAKE','','USD')",
        "INSERT INTO app.account_positions (owner_id,id,account_id,instrument_id,holding_form) "
        "VALUES (:own,:id,:foreign_account,:instrument,'custody')",
        "INSERT INTO app.instrument_mappings "
        "(owner_id,identifier_id,revision,previous_revision,instrument_id,reason) "
        "VALUES (:own,:reference,3,1,:instrument,'correction')",
        "UPDATE app.instruments SET name='Replacement'",
        "DELETE FROM app.instrument_mappings",
        "UPDATE app.account_positions SET owner_id=:other",
        "TRUNCATE app.instruments",
    ],
)
def test_direct_sql_cannot_change_history_or_cross_owners(instruments, statement):
    store, accounts, _ = instruments
    own = seed(store, accounts)
    foreign = seed(store, accounts, OWNER_B)
    with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        connection.execute(
            text(statement),
            dict(
                own=OWNER_A,
                other=OWNER_B,
                id=uuid4(),
                instrument=own[1].id,
                reference=own[3].id,
                foreign_instrument=foreign[1].id,
                foreign_account=foreign[0].id,
            ),
        )


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO app.instruments (owner_id,id,asset_class,name,isin) "
        "VALUES (:owner,:id,'mutual_fund','Synthetic','ZZ0000000016')",
        "INSERT INTO app.instruments (owner_id,id,asset_class,name,isin,fund_plan) "
        "VALUES (:owner,:id,'equity','Synthetic','ZZ0000000016','direct')",
        "INSERT INTO app.instrument_identifiers (owner_id,id,namespace,value,qualifier) "
        "VALUES (:owner,:id,'amfi_nav','123','')",
        "INSERT INTO app.instrument_identifiers (owner_id,id,namespace,value,qualifier) "
        "VALUES (:owner,:id,'amfi_nav','FAKE','growth')",
    ],
)
def test_sql_rejects_incomplete_variants_and_unqualified_nav_identifiers(instruments, statement):
    store, _, _ = instruments
    with store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        with pytest.raises(DBAPIError):
            connection.execute(text(statement), dict(owner=OWNER_A, id=uuid4()))


def test_bank_accounts_and_incompatible_custody_cannot_create_security_positions(instruments):
    store, accounts, _ = instruments
    with accounts.transaction(OWNER_A) as unit:
        bank = unit.create(definition())
        brokerage = unit.create(definition("brokerage", "indmoney", "US", ("USD",)))
    with store.transaction(OWNER_A) as unit:
        stock = unit.create(security())
        for account, form in (
            (bank, "demat"),
            (bank, "custody"),
            (brokerage, "folio"),
            (brokerage, "demat"),
        ):
            with pytest.raises(InstrumentUnavailable):
                unit.position(account.id, stock.id, form)
        assert unit.positions(bank.id) == unit.positions(brokerage.id) == ()


def test_concurrent_create_and_mapping_correction_have_one_effective_result(instruments):
    store, _, _ = instruments
    barrier = Barrier(2)

    def create(_):
        barrier.wait(timeout=10)
        with store.transaction(OWNER_A) as unit:
            return unit.create(security()).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(create, range(2)))
    assert first == second
    with store.transaction(OWNER_A) as unit:
        other = unit.create(security(1)).id
        reference = unit.identifier(IdentifierDefinition(namespace="ubs", value="FAKE"))

    def map_once(instrument_id):
        barrier.wait(timeout=10)
        try:
            with store.transaction(OWNER_A) as unit:
                return unit.map(reference.id, instrument_id, expected_revision=0).revision
        except InstrumentUnavailable:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(map_once, (first, other)))
    assert outcomes.count(1) == outcomes.count("conflict") == 1


def test_rollbacks_limits_and_transaction_lifetime_preserve_earlier_records(
    instruments, monkeypatch
):
    store, _, _ = instruments
    with store.transaction(OWNER_A) as unit:
        first = unit.create(security())
    with pytest.raises(RuntimeError), store.transaction(OWNER_A) as unit:
        unit.create(security(1))
        raise RuntimeError("Synthetic cancellation")
    with pytest.raises(DatabaseFailure, match="ended"):
        unit.get(first.id)
    monkeypatch.setattr("trading_db.instruments.MAX_RECORDS", 1)
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(InstrumentUnavailable):
            unit.create(security(1))
        assert len(unit.list()) == 1
    with store._workspace._engine.begin() as connection:
        assert connection.execute(text("SELECT app.current_owner_id()")).scalar_one() is None
        assert connection.execute(text("SELECT * FROM app.instruments")).all() == []


def test_migration_preserves_accounts_and_rolls_back_failure_before_repeatable_upgrade(
    database, monkeypatch
):
    url, project = database
    migrate.apply(url(), project, target="0006_accounts_sources")
    admin = engine_for(url("bootstrap"), migration=True)
    try:
        with admin.begin() as connection:
            connection.execute(
                text("INSERT INTO app.owners (id,is_active) VALUES (:owner,true)"),
                dict(owner=OWNER_A),
            )
            connection.execute(
                text(
                    "INSERT INTO app.financial_accounts "
                    "(owner_id,id,kind,institution,market,label) "
                    "VALUES (:owner,:id,'bank','hdfc','IN','Synthetic')"
                ),
                dict(owner=OWNER_A, id=OWNER_A),
            )
            connection.execute(
                text("INSERT INTO app.account_currencies VALUES (:owner,:id,'INR')"),
                dict(owner=OWNER_A, id=OWNER_A),
            )
        from alembic.operations import Operations

        original = Operations.execute

        def fail(self, statement, *args, **kwargs):
            result = original(self, statement, *args, **kwargs)
            if "CREATE TABLE app.instrument_identifiers" in str(statement):
                raise RuntimeError("Synthetic migration failure")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(Operations, "execute", fail)
            with pytest.raises(RuntimeError):
                migrate.apply(url(), project)
        assert migrate.revision(url(), project) == "0006_accounts_sources"
        with admin.connect() as connection:
            assert (
                connection.execute(text("SELECT to_regclass('app.instruments')")).scalar_one()
                is None
            )
        for _ in range(2):
            migrate.apply(url(), project)
            migrate.apply(url(), project)
            with admin.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT label FROM app.financial_accounts")
                    ).scalar_one()
                    == "Synthetic"
                )
                assert (
                    connection.execute(text("SELECT count(*) FROM app.instruments")).scalar_one()
                    == 0
                )
            migrate.apply(url(), project, direction="downgrade", target="0006_accounts_sources")
    finally:
        admin.dispose()
