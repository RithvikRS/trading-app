"""Source-bound atomic economics, explicit pending state and owner isolation."""

import hashlib
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from decimal import Decimal
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_accounts import definition
from database_tests.test_imports import batch, candidate, observation
from database_tests.test_ownership import DISABLED, OWNER_A, OWNER_B, UNKNOWN, set_owner
from trading_db import migrate
from trading_db.account_keys import ReferenceKeys
from trading_db.accounts import AccountDatabase
from trading_db.connections import DatabaseFailure, engine_for
from trading_db.events import EventDatabase, EventTransaction, EventUnavailable
from trading_db.import_contracts import StagedValue
from trading_db.imports import ImportDatabase, ImportTransaction, ImportUnavailable, canonical
from trading_db.instruments import (
    IdentifierDefinition,
    InstrumentDefinition,
    InstrumentTransaction,
    ListingDefinition,
    SchemeDefinition,
)
from trading_db.workspace import OwnerAccessDenied

TABLES = ("financial_events", "event_components", "quantity_movements", "cash_movements")


@pytest.fixture
def events(accounts, database):
    url, project = database
    store = EventDatabase(url("runtime"), project)
    try:
        yield store, *accounts
    finally:
        store.close()


def seed(accounts, owner=OWNER_A, kind="buy", states=("posted",), **changes):
    security = kind in ("buy", "sell", "subscription", "redemption", "dividend")
    fund = kind in ("subscription", "redemption")
    currency = "USD" if security and not fund else "INR"
    with accounts.transaction(owner) as unit:
        account = unit.create(
            definition("mutual_fund", "fund_registrar")
            if fund
            else definition("brokerage", "indmoney", "US", ("USD", "INR"))
            if security
            else definition()
        )
        source = unit.source(
            "cas" if fund else "indmoney_us" if security else "hdfc_statement", "FAKE-EVENT"
        )
        unit.map(source.id, account.id, expected_revision=0)
        position = reference = None
        if security:
            securities = InstrumentTransaction(unit._unit)
            scheme = securities.scheme(SchemeDefinition(name="Synthetic scheme")) if fund else None
            instrument = securities.create(
                InstrumentDefinition(
                    name="Synthetic security",
                    isin="ZZ0000000016",
                    asset_class="mutual_fund" if fund else "equity",
                    **(
                        dict(
                            fund_scheme_id=scheme.id,
                            fund_plan="regular",
                            fund_option="growth",
                            fund_currency="INR",
                        )
                        if fund
                        else {}
                    ),
                )
            )
            listing = (
                securities.listing(
                    instrument.id,
                    ListingDefinition(venue="XNYS", symbol="FAKE", quote_currency="USD"),
                )
                if not fund
                else None
            )
            reference = securities.identifier(
                IdentifierDefinition(
                    namespace="indmoney_funds" if fund else "indmoney_us", value="FAKE"
                )
            )
            securities.map(
                reference.id,
                instrument.id,
                expected_revision=0,
                listing_id=listing.id if listing else None,
            )
            position = securities.position(
                account.id, instrument.id, "folio" if fund else "custody"
            )
        quantity = "-0.123456789012" if kind in ("sell", "redemption") else "0.123456789012"
        net = "12.30" if kind in ("sell", "redemption", "dividend") else "-12.30"
        values = (StagedValue(role="net_cash", source=net, currency=currency),)
        if security:
            values += (
                StagedValue(
                    role="fee", source=None, currency=currency, missing_reason="not_supplied"
                ),
                StagedValue(role="withholding", source="0.00000000", currency=currency),
            )
        if kind == "dividend":
            values += (StagedValue(role="gross_cash", source="14.30", currency=currency),)
        elif security:
            values += (StagedValue(role="quantity", source=quantity),)
        staging = ImportTransaction(unit._unit)
        evidence = staging.observation(source.id, observation())
        normalized = staging.stage(
            evidence.id,
            batch(
                *(
                    candidate(
                        index,
                        kind=kind,
                        posting_state=state,
                        trade_date="2026-10-21" if security else None,
                        settlement_date="2026-10-23" if security else None,
                        instrument_identifier_id=reference.id if reference else None,
                        **(dict(values=values) | changes),
                    )
                    for index, state in enumerate(states, 1)
                )
            ),
            expected_revision=0,
        )
        rows = staging.rows(normalized.id)
        for row in rows:
            staging.decide(row.id, "include", expected_revision=0)
        return account, source, position, rows


@pytest.mark.parametrize(
    "kind",
    (
        "buy",
        "sell",
        "subscription",
        "redemption",
        "dividend",
        "cash_movement",
        "fee",
        "withholding",
    ),
)
def test_exact_movements_preserve_dates_and_pending_is_never_booked(events, kind):
    store, accounts, _ = events
    account, _, position, rows = seed(accounts, kind=kind, states=("posted", "pending"))
    with store.transaction(OWNER_A) as unit:
        saved = [
            unit.record(
                row.id, expected_review_revision=1, position_id=position.id if position else None
            )
            for row in rows
        ]
        for state in ("posted", "pending"):
            cash = unit.movements(account.id, kind="cash", posting_state=state)
            assert len(cash) == 1 and cash[0].event.posting_state == state
            expected = "12.30" if kind in ("sell", "redemption", "dividend") else "-12.30"
            assert cash[0].amount == Decimal(expected)
            if position:
                quantities = unit.movements(position.id, kind="quantity", posting_state=state)
                assert len(quantities) == (0 if kind == "dividend" else 1)
                if quantities:
                    sign = "-" if kind in ("sell", "redemption") else ""
                    assert quantities[0].amount == Decimal(sign + "0.123456789012")
                    assert quantities[0].currency is None
                components = {c.role: c for c in cash[0].event.components}
                assert components["fee"].source is None
                assert components["withholding"].source == "0.00000000"
                assert cash[0].event.trade_date.isoformat() == "2026-10-21"
                assert cash[0].event.settlement_date.isoformat() == "2026-10-23"
        first = unit.list(account.id, limit=1)[0]
        assert len(unit.list(account.id, after=first.id)) == 1
        assert unit.get(saved[0].id) == saved[0]
        assert unit.by_source(rows[0].id) == saved[0]
        assert "12.30" not in repr(saved[0])


def test_replay_review_lock_and_historical_records_survive_archive(events):
    store, accounts, _ = events
    account, source, position, rows = seed(accounts)
    with store.transaction(OWNER_A) as unit:
        saved = unit.record(rows[0].id, expected_review_revision=1, position_id=position.id)
        assert (
            unit.record(rows[0].id, expected_review_revision=1, position_id=position.id).id
            == saved.id
        )
        for args in (
            dict(expected_review_revision=2, position_id=position.id),
            dict(expected_review_revision=1),
        ):
            with pytest.raises(EventUnavailable):
                unit.record(rows[0].id, **args)
        for action in ("reopen", "exclude", "include"):
            with pytest.raises(ImportUnavailable):
                unit._imports.decide(rows[0].id, action, expected_revision=1)
    with accounts.transaction(OWNER_A) as unit:
        unit.archive(account.id, expected_revision=1)
        staging = ImportTransaction(unit._unit)
        evidence = staging.get_observation(staging.get_batch(rows[0].batch_id).observation_id)
        staging.observation(source.id, observation("b"), previous_id=evidence.id)
    with store.transaction(OWNER_A) as unit:
        assert unit.record(rows[0].id, expected_review_revision=1, position_id=position.id) == saved
        assert len(unit.movements(account.id, kind="cash", posting_state="posted")) == 1


def test_stale_reviews_wrong_positions_and_currency_cannot_create_movements(events):
    store, accounts, admin = events
    account, source, position, rows = seed(accounts, states=("posted", "posted"))
    with store.transaction(OWNER_A) as unit:
        for kwargs in (
            dict(position_id=uuid4(), expected_review_revision=1),
            dict(position_id=position.id, expected_review_revision=2),
            dict(expected_review_revision=1),
        ):
            with pytest.raises(EventUnavailable):
                unit.record(rows[0].id, **kwargs)
        unit._imports.decide(rows[0].id, "exclude", expected_revision=1)
        with pytest.raises(EventUnavailable):
            unit.record(rows[0].id, expected_review_revision=2, position_id=position.id)
    with accounts.transaction(OWNER_A) as unit:
        other = unit.create(account.definition)
        unit.map(source.id, other.id, expected_revision=1)
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(EventUnavailable):
            unit.record(rows[1].id, expected_review_revision=1, position_id=position.id)
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM app.financial_events")).scalar_one() == 0
        )


def test_cross_currency_and_snapshot_are_not_simple_events(events):
    store, accounts, _ = events
    _, _, position, rows = seed(
        accounts,
        values=(
            StagedValue(role="quantity", source="1"),
            StagedValue(role="net_cash", source="-10", currency="INR"),
            StagedValue(role="fee", source="1", currency="USD"),
        ),
    )
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(EventUnavailable):
            unit.record(rows[0].id, expected_review_revision=1, position_id=position.id)
        source = unit._imports.get_batch(rows[0].batch_id)
        revised = unit._imports.stage(
            source.observation_id,
            batch(
                candidate(
                    kind="cash_snapshot",
                    as_of_date="2026-10-24",
                ),
                version="2",
            ),
            expected_revision=1,
        )
        row = unit._imports.rows(revised.id)[0]
        unit._imports.decide(row.id, "include", expected_revision=0)
        with pytest.raises(EventUnavailable):
            unit.record(row.id, expected_review_revision=1)


def test_concurrent_replay_and_interrupted_last_write_are_atomic(events, monkeypatch):
    store, accounts, _ = events
    account, _, position, rows = seed(accounts, states=("posted", "pending"))
    gate = Barrier(2)

    def record():
        gate.wait()
        with store.transaction(OWNER_A) as unit:
            return unit.record(rows[0].id, expected_review_revision=1, position_id=position.id).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(lambda _: record(), range(2)))) == 1
    with store.transaction(OWNER_A) as unit:
        original = unit._execute

        def fail(sql, **params):
            result = original(sql, **params)
            if "INSERT INTO app.cash_movements" in sql:
                raise RuntimeError("Synthetic interrupted event")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(unit, "_execute", fail)
            with pytest.raises(RuntimeError):
                unit.record(rows[1].id, expected_review_revision=1, position_id=position.id)
        assert unit.by_source(rows[1].id) is None
        assert len(unit.list(account.id)) == 1
        assert unit.movements(account.id, kind="cash", posting_state="pending") == ()
        unit.record(rows[1].id, expected_review_revision=1, position_id=position.id)


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_cash",
        "wrong_cash",
        "wrong_source_text",
        "wrong_date",
        "extra_quantity",
        "wrong_state",
        "nonfinite_cash",
        "overprecise_cash",
        "cross_owner_component",
    ),
)
def test_direct_sql_integrity_rejects_incomplete_or_changed_events(events, mutation, monkeypatch):
    store, accounts, _ = events
    account, _, _, rows = seed(accounts, kind="cash_movement")
    with pytest.raises(EventUnavailable):
        with store.transaction(OWNER_A) as unit:
            original = unit._execute

            def corrupt(sql, **params):
                if "INSERT INTO app.cash_movements" in sql:
                    if mutation == "missing_cash":
                        return None
                    if mutation == "wrong_cash":
                        params["amount"] = Decimal("-99")
                    if mutation == "nonfinite_cash":
                        params["amount"] = Decimal("NaN")
                    if mutation == "overprecise_cash":
                        params["amount"] = Decimal("-12.301")
                if (
                    "INSERT INTO app.event_components" in sql
                    and mutation == "cross_owner_component"
                ):
                    params["owner"] = OWNER_B
                if "INSERT INTO app.event_components" in sql and mutation == "wrong_source_text":
                    params["source"] = "-12.3"  # Same numeric value; different source spelling.
                if "INSERT INTO app.financial_events" in sql:
                    if mutation == "wrong_date":
                        params["booking"] = "2026-10-23"
                    if mutation == "wrong_state":
                        params["state"] = "pending"
                result = original(sql, **params)
                if "INSERT INTO app.cash_movements" in sql and mutation == "extra_quantity":
                    # A legitimate owned position still cannot add quantity to bank cash activity.
                    securities = InstrumentTransaction(unit._accounts._unit)
                    asset = securities.create(
                        InstrumentDefinition(
                            name="Synthetic", asset_class="equity", isin="ZZ0000000016"
                        )
                    )
                    broker = unit._accounts.create(definition("brokerage", "indmoney"))
                    pos = securities.position(broker.id, asset.id, "demat")
                    original(
                        "INSERT INTO app.quantity_movements (owner_id,event_id,revision,"
                        "position_id,amount) VALUES (:owner,:event,1,:position,1)",
                        event=params["event"],
                        position=pos.id,
                    )
                return result

            monkeypatch.setattr(unit, "_execute", corrupt)
            unit.record(rows[0].id, expected_review_revision=1)
    with store.transaction(OWNER_A) as unit:
        assert unit.list(account.id) == ()


def test_owner_context_grants_bounds_and_pool_cleanup(events, database, monkeypatch):
    store, accounts, _ = events
    account, _, position, rows = seed(accounts)
    _, _, foreign_position, foreign_rows = seed(accounts, OWNER_B)
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(EventUnavailable):
            unit.record(rows[0].id, expected_review_revision=1, position_id=foreign_position.id)
        with pytest.raises(EventUnavailable):
            unit.record(
                foreign_rows[0].id, expected_review_revision=1, position_id=foreign_position.id
            )
        event = unit.record(rows[0].id, expected_review_revision=1, position_id=position.id)
        with pytest.raises(DatabaseFailure):
            unit.list(account.id, limit=101)
        with pytest.raises(EventUnavailable):
            unit.movements(account.id, kind="cash", posting_state="all")
    with store.transaction(OWNER_B) as unit:
        assert unit.get(event.id) is unit.by_source(rows[0].id) is None
        assert unit.list(account.id) == ()
    for owner in (UNKNOWN, DISABLED):
        with pytest.raises(OwnerAccessDenied):
            with store.transaction(owner):
                pass
    with pytest.raises(DatabaseFailure, match="ended"):
        unit.get(event.id)
    url, _ = database
    for role in ("runtime", "auth"):
        engine = engine_for(url(role))
        try:
            for table in TABLES:
                for command in (
                    ("UPDATE", "DELETE", "TRUNCATE") if role == "runtime" else ("SELECT",)
                ):
                    statement = {
                        "UPDATE": f"UPDATE app.{table} SET owner_id=:owner",
                        "DELETE": f"DELETE FROM app.{table}",
                        "TRUNCATE": f"TRUNCATE app.{table}",
                        "SELECT": f"SELECT * FROM app.{table}",
                    }[command]
                    with pytest.raises(DBAPIError), engine.begin() as connection:
                        if role == "runtime":
                            set_owner(connection, OWNER_A)
                        connection.execute(text(statement), dict(owner=OWNER_A))
        finally:
            engine.dispose()
    monkeypatch.setattr("trading_db.events.MAX_RECORDS", 0)
    with store.transaction(OWNER_B) as unit:
        with pytest.raises(EventUnavailable):
            unit.record(
                foreign_rows[0].id, expected_review_revision=1, position_id=foreign_position.id
            )
    with store._workspace._engine.connect() as connection:
        assert connection.execute(text("SELECT app.current_owner_id()")).scalar_one() is None
        for table in TABLES:
            assert connection.execute(text(f"SELECT count(*) FROM app.{table}")).scalar_one() == 0
    with store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        for table in TABLES:
            assert set(connection.execute(text(f"SELECT owner_id FROM app.{table}")).scalars()) == {
                OWNER_A
            }


def test_upgrade_preserves_legacy_digest_and_never_infers_posted(database, monkeypatch):
    url, project = database
    migrate.apply(url(), project, target="0008_import_staging")
    admin = engine_for(url("bootstrap"), migration=True)
    accounts = AccountDatabase(url("runtime"), project, ReferenceKeys({1: b"a" * 32}, 1))
    observation_id, batch_id, row_id = uuid4(), uuid4(), uuid4()
    legacy = batch(candidate(posting_state=None))
    digest = hashlib.sha256(canonical(legacy, 1).encode()).hexdigest()
    try:
        with admin.begin() as connection:
            connection.execute(
                text("INSERT INTO app.owners (id,is_active) VALUES (:owner,true)"),
                dict(owner=OWNER_A),
            )
        with accounts.transaction(OWNER_A) as unit:
            account = unit.create(definition())
            source = unit.source("hdfc_statement", "FAKE-LEGACY")
            unit.map(source.id, account.id, expected_revision=0)
            unit._execute(
                "INSERT INTO app.source_observations (owner_id,id,source_id,digest,"
                "digest_algorithm,coverage) VALUES (:owner,:id,:source,:digest,'sha256_v1',"
                "'unknown')",
                id=observation_id,
                source=source.id,
                digest="a" * 64,
            )
            unit._execute(
                "INSERT INTO app.import_batches (owner_id,id,observation_id,revision,"
                "normalizer,normalizer_version,normalized_digest,row_count) VALUES (:owner,"
                ":id,:observation,1,'synthetic','1',:digest,1)",
                id=batch_id,
                observation=observation_id,
                digest=digest,
            )
            unit._execute(
                "INSERT INTO app.staged_rows (owner_id,id,batch_id,occurrence,kind,"
                "booking_date,value_count) VALUES (:owner,:id,:batch,1,'cash_movement',"
                "'2026-10-24',1)",
                id=row_id,
                batch=batch_id,
            )
            unit._execute(
                "INSERT INTO app.staged_values (owner_id,row_id,role,source,amount,currency) "
                "VALUES (:owner,:id,'net_cash','-12.30',-12.30,'INR')",
                id=row_id,
            )
            unit._execute(
                "INSERT INTO app.review_decisions (owner_id,row_id,revision,action,reason,"
                "source_id,account_mapping_revision) VALUES (:owner,:id,1,'include',"
                "'reviewed',:source,1)",
                id=row_id,
                source=source.id,
            )
        from alembic.operations import Operations

        original = Operations.execute

        def fail(self, sql, *args, **kwargs):
            result = original(self, sql, *args, **kwargs)
            if "CREATE TABLE app.event_components" in str(sql):
                raise RuntimeError("Synthetic migration interruption")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(Operations, "execute", fail)
            with pytest.raises(RuntimeError):
                migrate.apply(url(), project)
        assert migrate.revision(url(), project) == "0008_import_staging"
        migrate.apply(url(), project)
        migrate.apply(url(), project)
        migrate.apply(url(), project, direction="downgrade", target="0008_import_staging")
        migrate.apply(url(), project)
        store = ImportDatabase(url("runtime"), project)
        try:
            with store.transaction(OWNER_A) as unit:
                assert unit.get_batch(batch_id).definition == legacy
                assert unit.get_row(row_id).issue == "not_supplied"
                assert unit.stage(observation_id, legacy, expected_revision=1).id == batch_id
                with pytest.raises(ImportUnavailable), unit._write():
                    unit._execute(
                        "INSERT INTO app.import_batches (owner_id,id,observation_id,revision,"
                        "previous_revision,normalizer,normalizer_version,normalized_digest,"
                        "row_count,contract_version) VALUES (:owner,:id,:observation,2,1,"
                        "'synthetic','2',:digest,1,1)",
                        id=uuid4(),
                        observation=observation_id,
                        digest=digest,
                    )
                with pytest.raises(ImportUnavailable):
                    unit.decide(row_id, "include", expected_revision=1)
                with pytest.raises(ImportUnavailable):
                    unit.stage(observation_id, batch(candidate()), expected_revision=1)
                upgraded = unit.stage(
                    observation_id, batch(candidate(), version="2"), expected_revision=1
                )
                current = unit.rows(upgraded.id)[0]
                unit.decide(current.id, "include", expected_revision=0)
                EventTransaction(unit._accounts._unit).record(
                    current.id, expected_review_revision=1
                )
        finally:
            store.close()
        with admin.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT normalized_digest,contract_version FROM app.import_batches WHERE id=:id"
                ),
                dict(id=batch_id),
            ).one() == (digest, 1)
    finally:
        accounts.close()
        admin.dispose()


def test_posted_trade_does_not_invent_booking_date(events):
    store, accounts, _ = events
    account, _, position, rows = seed(accounts, booking_date=None)
    with store.transaction(OWNER_A) as unit:
        event = unit.record(rows[0].id, expected_review_revision=1, position_id=position.id)
        assert event.booking_date is None and event.trade_date is not None
        assert (
            unit.movements(account.id, kind="cash", posting_state="posted")[0].event.booking_date
            is None
        )


@pytest.mark.parametrize("change", ("review", "archive", "mapping"))
def test_direct_review_and_event_commit_share_the_owner_lock(events, change):
    store, accounts, _ = events
    account, source, _, rows = seed(accounts, kind="cash_movement")
    started = Event()
    statements = {
        "review": "INSERT INTO app.review_decisions (owner_id,row_id,revision,"
        "previous_revision,action,reason,source_id) VALUES (:owner,:row,2,1,"
        "'exclude','user_excluded',:source)",
        "archive": "UPDATE app.financial_accounts SET archived_at=statement_timestamp() "
        "WHERE owner_id=:owner AND id=:account",
        "mapping": "INSERT INTO app.source_account_mappings (owner_id,source_id,revision,"
        "previous_revision,account_id,reason) VALUES (:owner,:source,2,1,:account,'correction')",
    }

    def mutate():
        try:
            with store._workspace._engine.begin() as connection:
                set_owner(connection, OWNER_A)
                started.set()
                connection.execute(
                    text(statements[change]),
                    dict(owner=OWNER_A, row=rows[0].id, source=source.id, account=account.id),
                )
            return "changed"
        except DBAPIError:
            return "consumed"

    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.transaction(OWNER_A) as unit:
            unit.record(rows[0].id, expected_review_revision=1)
            future = pool.submit(mutate)
            assert started.wait(5)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.1)
        assert future.result(timeout=5) == ("consumed" if change == "review" else "changed")
