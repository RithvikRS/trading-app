"""Market evidence cannot cross owners, directions, listings or fund variants."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_instruments import instruments as instruments
from database_tests.test_instruments import security, seed
from database_tests.test_ownership import DISABLED, OWNER_A, OWNER_B, UNKNOWN, set_owner
from tests.test_markets import definition
from trading_db import migrate, recovery
from trading_db.connections import DatabaseFailure, engine_for
from trading_db.instruments import SchemeDefinition
from trading_db.markets import MarketDatabase, MarketUnavailable
from trading_db.workspace import OwnerAccessDenied

TABLES = ("market_observations", "market_selections")


@pytest.fixture
def markets(instruments, database):
    url, project = database
    store = MarketDatabase(url("runtime"), project)
    try:
        yield store, *instruments
    finally:
        store.close()


def quote(markets, owner=OWNER_A):
    _, identities, accounts, _ = markets
    _, instrument, listing, _, _ = seed(identities, accounts, owner)
    return definition(
        kind="quote",
        instrument_id=instrument.id,
        listing_id=listing.id,
        currency="USD",
        base_currency=None,
        quote_currency=None,
        basis="close",
        adjustment="unadjusted",
    )


def raw_observation(connection, valid, owner=OWNER_A, **changes):
    values = dict(owner_id=owner, id=uuid4(), **valid.model_dump(), amount=valid.reported().value)
    values.update(changes)
    columns = ",".join(values)
    bindings = ",".join(":" + key for key in values)
    connection.execute(
        text(f"INSERT INTO app.market_observations ({columns}) VALUES ({bindings})"), values
    )
    return values["id"]


def test_exact_source_replay_and_changed_payload_conflict(markets):
    store, _, _, _ = markets
    valid = quote(markets)
    with store.transaction(OWNER_A) as unit:
        first = unit.record(valid)
        assert unit.record(valid) == first
        for change in (dict(source="84"), dict(observed_on="2026-10-23"), dict(basis="last")):
            with pytest.raises(MarketUnavailable):
                unit.record(valid.model_copy(update=change))
        alternate = unit.record(
            valid.model_copy(update={"namespace": "exchange_quote_report", "source": "84"})
        )
        assert alternate.id != first.id
        assert len(unit.list(valid.target())) == 2
        page = unit.list(valid.target(), limit=1)
        assert len(unit.list(valid.target(), after=page[0].id)) == 1
        selected = unit.select(first.id, expected_revision=0)
        assert unit.resolve(selected.id).observation == first
        assert len(unit.selections()) == 1
        # A second provider's price can differ; no snapshot-style quantity conflict.
        assert unit.resolve(selected.id).state == "selected"


def test_supersession_stales_choice_retries_preserve_history_and_clear(markets):
    store, _, _, _ = markets
    with store.transaction(OWNER_A) as unit:
        original = unit.record(definition(observed_at="2026-10-24T00:30:00.120+05:30"))
        first = unit.select(original.id, expected_revision=0)
    with store.transaction(OWNER_A) as unit:
        changed = unit.record(
            original.definition.model_copy(
                update={"digest": "b" * 64, "previous_id": original.id, "source": "84.000000000001"}
            )
        )
        assert unit.resolve(first.id).state == "stale"
        assert unit.resolve(first.id).observation is None
        assert unit.select(original.id, expected_revision=0) == first  # Exact historical retry.
        with pytest.raises(MarketUnavailable):
            unit.select(original.id, expected_revision=1, reason="replacement")
        second = unit.select(changed.id, expected_revision=1, reason="correction")
        assert unit.record(changed.definition) == changed
        with pytest.raises(MarketUnavailable):
            unit.record(changed.definition.model_copy(update={"digest": "c" * 64}))
        third = unit.clear(second.id, expected_revision=2)
        assert unit.clear(second.id, expected_revision=2) == third
        assert unit.resolve(first.id).state == "unselected"
        assert unit.resolve(first.id).observation is None
        assert unit.select(changed.id, expected_revision=1, reason="correction") == second
        with pytest.raises(MarketUnavailable):
            unit.select(changed.id, expected_revision=1, reason="replacement")
        assert unit.selection_history(first.id) == (third, second, first)
        assert unit.selection_history(first.id, before=3, limit=1) == (second,)
        assert unit.get(original.id) == original


@pytest.mark.parametrize("source,missing", [(None, "not_supplied"), ("0.00", None), ("-1", None)])
def test_unusable_reports_remain_evidence_and_never_select(markets, source, missing):
    store, _, _, _ = markets
    with store.transaction(OWNER_A) as unit:
        evidence = unit.record(definition(source=source, missing_reason=missing))
        assert evidence.definition.source == source
        with pytest.raises(MarketUnavailable):
            unit.select(evidence.id, expected_revision=0)
        assert unit.selections() == ()


def test_currency_direction_date_precision_and_adjustment_do_not_blend(markets):
    store, _, _, _ = markets
    valid = quote(markets)
    with store.transaction(OWNER_A) as unit:
        adjusted = unit.record(valid.model_copy(update={"adjustment": "split_adjusted"}))
        with pytest.raises(MarketUnavailable):
            unit.select(adjusted.id, expected_revision=0)
        for occurrence, changes in enumerate(
            ({}, {"base_currency": "INR", "quote_currency": "USD"}), 2
        ):
            fx = unit.record(definition(occurrence=occurrence, **changes))
            selected = unit.select(fx.id, expected_revision=0)
            assert unit.resolve(selected.id).observation.definition.observed_at is None
        assert len(unit.selections()) == 2


def test_nav_variants_and_quote_listings_cannot_be_reassigned(markets):
    store, identities, _, _ = markets
    valid = quote(markets)
    with identities.transaction(OWNER_A) as unit:
        scheme = unit.scheme(SchemeDefinition(name="Synthetic fund"))
        funds = [
            unit.create(
                security(
                    index,
                    "mutual_fund",
                    fund_scheme_id=scheme.id,
                    fund_plan=plan,
                    fund_option="growth",
                    fund_currency="INR",
                )
            )
            for index, plan in ((1, "direct"), (2, "regular"))
        ]
    with store.transaction(OWNER_A) as unit:
        for occurrence, fund in enumerate(funds, 1):
            observed = unit.record(
                definition(
                    kind="nav",
                    instrument_id=fund.id,
                    currency="INR",
                    base_currency=None,
                    quote_currency=None,
                    basis="nav",
                    occurrence=occurrence,
                    namespace="amfi_nav_report",
                )
            )
            unit.select(observed.id, expected_revision=0)
        assert len(unit.selections()) == 2
    for changes in (dict(instrument_id=funds[0].id), dict(currency="INR")):
        with pytest.raises(MarketUnavailable):
            with store.transaction(OWNER_A) as unit:
                unit.record(valid.model_copy(update=changes))


@pytest.mark.parametrize(
    "changes",
    [
        dict(source="1e2", amount=100),
        dict(source="1.0000000000001", amount=1),
        dict(source="01", amount=1),
        dict(source="1", amount=2),
        dict(source="1", amount=None),
        dict(source=None, amount=None, missing_reason=None),
        dict(source=None, amount=1),
        dict(currency="USD"),
        dict(base_currency=None),
        dict(base_currency="INR"),
        dict(observed_at="2026-10-24T00:00:00"),
        dict(observed_at="2026-10-25T00:00:00Z"),
        dict(contract_version=2),
        dict(normalizer_version=0),
        dict(occurrence=0),
        dict(namespace="amfi_nav_report"),
        dict(adjustment="unknown"),
        dict(basis="close"),
    ],
)
def test_direct_sql_rejects_invalid_evidence(markets, database, changes):
    url, _ = database
    engine = engine_for(url("runtime"))
    try:
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                set_owner(connection, OWNER_A)
                raw_observation(connection, definition(), **changes)
    finally:
        engine.dispose()


def test_owner_denial_and_runtime_privileges(markets, database):
    store, _, _, admin = markets
    url, _ = database
    with store.transaction(OWNER_A) as unit:
        observed = unit.record(definition())
        selected = unit.select(observed.id, expected_revision=0)
    with store.transaction(OWNER_B) as unit:
        assert unit.get(observed.id) is None and unit.get(uuid4()) is None
        assert unit.selection(selected.id) is None and unit.resolve(selected.id) is None
        with pytest.raises(MarketUnavailable):
            unit.select(observed.id, expected_revision=0)
        assert unit.record(definition()).id != observed.id
    for owner in (UNKNOWN, DISABLED):
        with pytest.raises(OwnerAccessDenied):
            with store.transaction(owner):
                pytest.fail("Inactive owner entered the service")
    runtime = engine_for(url("runtime"))
    auth = engine_for(url("auth"))
    try:
        for table in TABLES:
            for statement in (
                f"DELETE FROM app.{table}",
                f"UPDATE app.{table} SET id=id",
                f"UPDATE app.{table} SET owner_id=owner_id",
            ):
                with pytest.raises(DBAPIError):
                    with runtime.begin() as connection:
                        set_owner(connection, OWNER_A)
                        connection.execute(text(statement))
            with pytest.raises(DBAPIError):
                with auth.begin() as connection:
                    connection.execute(text(f"SELECT * FROM app.{table}"))
            with runtime.begin() as connection:
                assert (
                    connection.execute(text(f"SELECT count(*) FROM app.{table}")).scalar_one() == 0
                )
        with pytest.raises(DBAPIError):
            with runtime.begin() as connection:
                set_owner(connection, OWNER_B)
                raw_observation(connection, definition(occurrence=2), owner=OWNER_A)
        with pytest.raises(DBAPIError):
            with runtime.begin() as connection:
                set_owner(connection, OWNER_A)
                raw_observation(connection, definition(occurrence=2), created_at="2020-01-01")
        with admin.connect() as connection:
            policies = connection.execute(
                text(
                    "SELECT relrowsecurity,relforcerowsecurity FROM "
                    "pg_class WHERE relnamespace='app'::regnamespace AND relname IN "
                    "('market_observations','market_selections')"
                )
            ).all()
            assert policies == [(True, True), (True, True)]
    finally:
        runtime.dispose()
        auth.dispose()


def test_concurrent_replay_and_conflicting_selection_are_serialized(markets):
    store, _, _, _ = markets
    barrier = Barrier(2)

    def record():
        barrier.wait(timeout=10)
        with store.transaction(OWNER_A) as unit:
            return unit.record(definition())

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: record(), range(2)))
    assert results[0] == results[1]
    with store.transaction(OWNER_A) as unit:
        other = unit.record(definition(occurrence=2, source="84"))
    barrier = Barrier(2)

    def choose(observation):
        barrier.wait(timeout=10)
        try:
            with store.transaction(OWNER_A) as unit:
                return unit.select(observation.id, expected_revision=0)
        except MarketUnavailable:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        choices = list(executor.map(choose, (results[0], other)))
    assert sum(item is not None for item in choices) == 1


def test_correction_cycles_and_foreign_predecessors_cannot_restore(markets):
    _, _, _, admin = markets
    first, second = uuid4(), uuid4()
    with pytest.raises(DBAPIError):
        with admin.begin() as connection:
            raw_observation(connection, definition(), id=first, previous_id=second)
            raw_observation(connection, definition(occurrence=2), id=second, previous_id=first)
    with pytest.raises(DBAPIError):
        with admin.begin() as connection:
            raw_observation(connection, definition(), owner=OWNER_A, id=first)
            raw_observation(connection, definition(), owner=OWNER_B, previous_id=first)


def test_record_failure_rolls_back_and_budget_limits_are_bounded(markets, monkeypatch):
    store, _, _, _ = markets
    with pytest.raises(MarketUnavailable):
        with store.transaction(OWNER_A) as unit:
            unit.record(definition())
            unit.record(definition(source="84"))
    with store.transaction(OWNER_A) as unit:
        assert unit.list(definition().target()) == ()
        monkeypatch.setattr("trading_db.markets.MAX_RECORDS", 1)
        first = unit.record(definition())
        assert unit.record(definition()) == first
        with pytest.raises(MarketUnavailable):
            unit.record(definition(occurrence=2))
        for limit in (0, 101, True):
            with pytest.raises(DatabaseFailure):
                unit.list(definition().target(), limit=limit)


def test_empty_migration_round_trip_and_populated_downgrade_refusal(markets, database):
    store, _, _, admin = markets
    url, project = database
    migrate.apply(url(), project, target="0011_snapshots", direction="downgrade")
    migrate.apply(url(), project)
    migrate.apply(url(), project)
    with store.transaction(OWNER_A) as unit:
        saved = unit.record(definition())
    with pytest.raises(DBAPIError):
        migrate.apply(url(), project, target="0011_snapshots", direction="downgrade")
    with admin.connect() as connection:
        assert (
            connection.execute(
                text("SELECT version_num FROM app_meta.alembic_version")
            ).scalar_one()
            == recovery.HEAD
        )
    with store.transaction(OWNER_A) as unit:
        assert unit.get(saved.id) == saved


def test_direct_sql_selection_checks_owner_target_usability_and_history(markets, database):
    store, _, _, _ = markets
    with store.transaction(OWNER_A) as unit:
        good = unit.record(definition())
        unusable = unit.record(definition(source="0", occurrence=2))
        first = unit.select(good.id, expected_revision=0)
    url, _ = database
    runtime = engine_for(url("runtime"))
    base = dict(
        owner_id=OWNER_A,
        id=first.id,
        revision=2,
        previous_revision=1,
        observation_id=good.id,
        reason="replacement",
        **good.definition.target().model_dump(),
    )
    try:
        for changes in (
            dict(observation_id=unusable.id),
            dict(owner_id=OWNER_B),
            dict(base_currency="INR", quote_currency="USD"),
            dict(basis="spot"),
            dict(revision=3, previous_revision=2),
            dict(reason="correction"),
            dict(id=uuid4()),
            dict(observation_id=None),
            dict(created_at="2020-01-01"),
        ):
            values = base | changes
            with pytest.raises(DBAPIError):
                with runtime.begin() as connection:
                    set_owner(connection, values["owner_id"])
                    columns = ",".join(values)
                    bindings = ",".join(":" + key for key in values)
                    connection.execute(
                        text(f"INSERT INTO app.market_selections ({columns}) VALUES ({bindings})"),
                        values,
                    )
        with store.transaction(OWNER_A) as unit:
            assert unit.selection(first.id) == first
    finally:
        runtime.dispose()


def test_foreign_instrument_and_listing_are_unavailable(markets):
    store, _, _, _ = markets
    owned = quote(markets, OWNER_A)
    other = quote(markets, OWNER_B)
    for changes in (
        dict(instrument_id=other.instrument_id),
        dict(listing_id=other.listing_id),
        dict(instrument_id=uuid4()),
        dict(listing_id=uuid4()),
    ):
        with pytest.raises(MarketUnavailable):
            with store.transaction(OWNER_A) as unit:
                unit.record(owned.model_copy(update=changes))


def test_upgrade_failure_rolls_back_and_preserves_existing_accounts(markets, database, monkeypatch):
    from alembic.operations import Operations

    _, _, accounts, admin = markets
    url, project = database
    migrate.apply(url(), project, direction="downgrade", target="0011_snapshots")
    with accounts.transaction(OWNER_A) as unit:
        from database_tests.test_accounts import definition as account_definition

        saved = unit.create(account_definition())
    execute = Operations.execute

    def fail(self, sql, *args, **kwargs):
        result = execute(self, sql, *args, **kwargs)
        if "CREATE TABLE app.market_selections" in str(sql):
            raise RuntimeError("Synthetic migration interruption.")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Operations, "execute", fail)
        with pytest.raises(RuntimeError):
            migrate.apply(url(), project)
    assert migrate.revision(url(), project) == "0011_snapshots"
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT to_regclass('app.market_observations')")).scalar_one()
            is None
        )
    migrate.apply(url(), project)
    with accounts.transaction(OWNER_A) as unit:
        assert unit.get(saved.id) == saved
