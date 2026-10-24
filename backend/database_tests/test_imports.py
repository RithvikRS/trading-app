"""Immutable evidence, current review context, owner denial and exact SQL storage."""

import warnings
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_accounts import definition, seed
from database_tests.test_ownership import DISABLED, OWNER_A, OWNER_B, UNKNOWN, set_owner
from trading_db import migrate
from trading_db.connections import DatabaseFailure, engine_for
from trading_db.import_contracts import (
    EVENT_KINDS,
    BatchDefinition,
    CandidateDefinition,
    ObservationDefinition,
    StagedValue,
)
from trading_db.imports import ImportDatabase, ImportUnavailable
from trading_db.instruments import IdentifierDefinition, InstrumentDefinition, InstrumentTransaction
from trading_db.workspace import OwnerAccessDenied

TABLES = (
    "source_observations",
    "import_batches",
    "staged_rows",
    "staged_values",
    "review_decisions",
)


def observation(digest="a"):
    return ObservationDefinition(
        digest=digest * 64,
        coverage="partial_activity",
        period_start="2026-10-01",
        period_end="2026-10-24",
    )


def candidate(occurrence=1, **changes):
    changes.setdefault(
        "posting_state", "posted" if changes.get("kind", "cash_movement") in EVENT_KINDS else None
    )
    return CandidateDefinition(
        **(
            dict(
                occurrence=occurrence,
                kind="cash_movement",
                booking_date="2026-10-24",
                values=(StagedValue(role="net_cash", source="-12.30", currency="INR"),),
            )
            | changes
        )
    )


def batch(*rows, version="1"):
    return BatchDefinition(
        normalizer="synthetic", normalizer_version=version, rows=rows or (candidate(),)
    )


@pytest.fixture
def imports(accounts, database):
    url, project = database
    store = ImportDatabase(url("runtime"), project)
    try:
        yield store, *accounts
    finally:
        store.close()


def setup(store, accounts, owner=OWNER_A, *rows):
    account, source = seed(accounts, owner)
    with store.transaction(owner) as unit:
        evidence = unit.observation(source.id, observation())
        staged = unit.stage(evidence.id, batch(*rows), expected_revision=0)
        row = unit.rows(staged.id)[0]
    return account, source, evidence, staged, row


def test_exact_replay_preserves_identical_occurrences_and_original_values(imports):
    store, accounts, admin = imports
    _, source, evidence, staged, row = setup(store, accounts, OWNER_A, candidate(), candidate(2))
    with store.transaction(OWNER_A) as unit:
        assert unit.observation(source.id, observation()).id == evidence.id
        assert (
            unit.stage(evidence.id, batch(candidate(), candidate(2)), expected_revision=0).id
            == staged.id
        )
        assert len(unit.rows(staged.id)) == 2
        assert len(unit.rows(staged.id, limit=1, after=1)) == 1
        assert unit.get_row(row.id).definition.values[0].source == "-12.30"
        assert len(unit.observations(source.id)) == 1
        assert unit.get_batch(staged.id).definition == staged.definition
        with pytest.raises(ImportUnavailable):
            unit.observation(
                source.id, observation().model_copy(update={"coverage": "complete_activity"})
            )
        with pytest.raises(ImportUnavailable):
            unit.stage(evidence.id, batch(candidate(3)), expected_revision=1)
    with admin.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM app.account_positions")).scalar_one() == 0
        )
        assert connection.execute(text("SELECT count(*) FROM app.instruments")).scalar_one() == 0


def test_review_changes_keep_history_and_mapping_changes_require_review_again(imports):
    store, accounts, _ = imports
    account, source, _, staged, row = setup(store, accounts)
    with store.transaction(OWNER_A) as unit:
        assert unit.decide(row.id, "include", expected_revision=0).revision == 1
        assert unit.get_row(row.id).status == "included"
        unit.decide(row.id, "exclude", expected_revision=1)
        assert unit.get_row(row.id).status == "excluded"
        unit.decide(row.id, "reopen", expected_revision=2)
        assert unit.get_row(row.id).status == "reviewable"
        unit.decide(row.id, "include", expected_revision=3)
        with pytest.raises(ImportUnavailable):
            unit.decide(row.id, "exclude", expected_revision=1)
        assert [value.revision for value in unit.history(row.id, limit=2)] == [4, 3]
        assert [value.revision for value in unit.history(row.id, before=3)] == [2, 1]
    with accounts.transaction(OWNER_A) as unit:
        other = unit.create(definition())
        unit.map(source.id, other.id, expected_revision=1)
    with store.transaction(OWNER_A) as unit:
        assert unit.rows(staged.id)[0].issue == "stale_mapping"
        unit.decide(row.id, "include", expected_revision=4)
        assert unit.get_row(row.id).status == "included"
    with accounts.transaction(OWNER_A) as unit:
        unit.archive(other.id, expected_revision=1)
    with store.transaction(OWNER_A) as unit:
        assert unit.get_row(row.id).issue == "unresolved_account"
        with pytest.raises(ImportUnavailable):
            unit.decide(row.id, "include", expected_revision=5)
        assert unit._accounts.get(account.id) is not None


def test_reprocessing_and_revised_evidence_supersede_old_reviews(imports):
    store, accounts, _ = imports
    _, source, evidence, staged, row = setup(store, accounts)
    with store.transaction(OWNER_A) as unit:
        unit.decide(row.id, "include", expected_revision=0)
        revised = unit.stage(evidence.id, batch(candidate(2), version="2"), expected_revision=1)
        assert unit.get_row(row.id).status == "superseded"
        assert unit.get_batch(staged.id) is not None
        with pytest.raises(ImportUnavailable):
            unit.decide(row.id, "include", expected_revision=1)
        current = unit.rows(revised.id)[0]
        unit.decide(current.id, "include", expected_revision=0)
        replacement = unit.observation(source.id, observation("b"), previous_id=evidence.id)
        assert unit.get_row(current.id).status == "superseded"
        with pytest.raises(ImportUnavailable):
            unit.observation(source.id, observation("c"), previous_id=evidence.id)
        with pytest.raises(ImportUnavailable):
            unit.stage(evidence.id, batch(version="3"), expected_revision=2)
        assert unit.stage(replacement.id, batch(), expected_revision=0).revision == 1


@pytest.mark.parametrize(
    "row,issue",
    [
        (candidate(values=()), "not_supplied"),
        (candidate(kind="unsupported"), "unsupported"),
        (candidate(blocked_reason="conflicting_evidence"), "conflicting_evidence"),
        (
            candidate(
                values=(
                    StagedValue(
                        role="net_cash", source=None, currency="INR", missing_reason="not_supplied"
                    ),
                )
            ),
            "not_supplied",
        ),
        (
            candidate(values=(StagedValue(role="net_cash", source="1", currency="USD"),)),
            "unsupported_currency",
        ),
    ],
)
def test_unsupported_or_missing_data_can_be_inspected_and_excluded_but_not_included(
    imports, row, issue
):
    store, accounts, _ = imports
    _, _, _, _, record = setup(store, accounts, OWNER_A, row)
    with store.transaction(OWNER_A) as unit:
        assert unit.get_row(record.id).issue == issue
        with pytest.raises(ImportUnavailable):
            unit.decide(record.id, "include", expected_revision=0)
        unit.decide(record.id, "exclude", expected_revision=0)
        assert unit.get_row(record.id).status == "excluded"
        with pytest.raises(ImportUnavailable):
            unit.decide(record.id, "include", expected_revision=1)


def test_security_review_binds_exact_mapping_revision_and_compatible_account(imports):
    store, accounts, _ = imports
    with accounts.transaction(OWNER_A) as unit:
        account = unit.create(definition("brokerage", "indmoney", "US", ("USD",)))
        source = unit.source("indmoney_us", "FAKE-BROKER")
        unit.map(source.id, account.id, expected_revision=0)
        securities = InstrumentTransaction(unit._unit)
        first = securities.create(
            InstrumentDefinition(asset_class="equity", isin="ZZ0000000016", name="Synthetic")
        )
        second = securities.create(
            InstrumentDefinition(asset_class="equity", isin="ZZ0000000024", name="Synthetic")
        )
        reference = securities.identifier(
            IdentifierDefinition(namespace="indmoney_us", value="FAKE")
        )
        securities.map(reference.id, first.id, expected_revision=0)
    purchase = candidate(
        kind="buy",
        instrument_identifier_id=reference.id,
        trade_date="2026-10-24",
        values=(
            StagedValue(role="quantity", source="0.123456789012"),
            StagedValue(role="net_cash", source="-12.30", currency="USD"),
        ),
    )
    with store.transaction(OWNER_A) as unit:
        evidence = unit.observation(source.id, observation())
        staged = unit.stage(evidence.id, batch(purchase), expected_revision=0)
        row = unit.rows(staged.id)[0]
        assert row.status == "reviewable"
        assert unit.decide(row.id, "include", expected_revision=0).instrument_mapping_revision == 1
    with accounts.transaction(OWNER_A) as unit:
        InstrumentTransaction(unit._unit).map(reference.id, second.id, expected_revision=1)
    with store.transaction(OWNER_A) as unit:
        assert unit.get_row(row.id).issue == "stale_mapping"
        assert unit.decide(row.id, "include", expected_revision=1).instrument_mapping_revision == 2
        assert unit.get_row(row.id).status == "included"
    with accounts.transaction(OWNER_A) as unit:
        bank = unit.create(definition())
        bank_source = unit.source("hdfc_statement", "FAKE-BANK")
        unit.map(bank_source.id, bank.id, expected_revision=0)
    with store.transaction(OWNER_A) as unit:
        evidence = unit.observation(bank_source.id, observation())
        staged = unit.stage(evidence.id, batch(purchase), expected_revision=0)
        with pytest.raises(ImportUnavailable):
            unit.decide(unit.rows(staged.id)[0].id, "include", expected_revision=0)


def test_owner_isolation_covers_evidence_rows_values_decisions_and_parents(imports):
    store, accounts, _ = imports
    own = setup(store, accounts)
    foreign = setup(store, accounts, OWNER_B)
    with store.transaction(OWNER_A) as unit:
        assert unit.get_row(foreign[4].id) == unit.get_row(uuid4()) is None
        assert unit.get_observation(foreign[2].id) is None
        assert unit.get_batch(foreign[3].id) is None
        assert unit.rows(foreign[3].id) == unit.history(foreign[4].id) == ()
        for action in (
            lambda: unit.observation(foreign[1].id, observation("b")),
            lambda: unit.observation(own[1].id, observation("b"), previous_id=foreign[2].id),
            lambda: unit.stage(foreign[2].id, batch(version="2"), expected_revision=1),
            lambda: unit.decide(foreign[4].id, "include", expected_revision=0),
        ):
            with pytest.raises(ImportUnavailable):
                action()


@pytest.mark.parametrize("owner", [None, DISABLED, UNKNOWN])
def test_invalid_owner_cannot_enter(imports, owner):
    store, _, _ = imports
    with pytest.raises(OwnerAccessDenied), store.transaction(owner):
        pytest.fail("Invalid owner entered import service")


@pytest.mark.parametrize(
    "role,source,amount,currency,missing",
    [
        ("net_cash", "1.001", "1.001", "INR", None),
        ("net_cash", "1.001", "1.00", "INR", None),
        ("quantity", "0.0000000000001", "0.0000000000001", None, None),
        ("fee", "1.000000001", "1.000000001", "USD", None),
        ("net_cash", "1", "NaN", "INR", None),
        ("net_cash", "1", "Infinity", "INR", None),
        ("net_cash", "1", "2", "INR", None),
        ("net_cash", None, None, "INR", None),
        ("net_cash", None, "0", "INR", "not_supplied"),
        ("net_cash", "1e2", "100", "INR", None),
        ("net_cash", "1000000000000000000", "1000000000000000000", "INR", None),
        ("quantity", "1", "1", "INR", None),
        ("unit_price", "0", "0", "USD", None),
    ],
)
def test_direct_sql_cannot_bypass_value_precision_missing_or_context(
    imports, role, source, amount, currency, missing
):
    store, accounts, _ = imports
    evidence = setup(store, accounts)[2]
    batch_id, row_id = uuid4(), uuid4()
    with store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        connection.execute(
            text(
                "INSERT INTO app.import_batches (owner_id,id,observation_id,revision,"
                "previous_revision,normalizer,normalizer_version,normalized_digest,"
                "row_count) VALUES (:owner,:batch,:observation,2,1,'synthetic','sql-test',"
                ":digest,1)"
            ),
            dict(owner=OWNER_A, batch=batch_id, observation=evidence.id, digest="c" * 64),
        )
        connection.execute(
            text(
                "INSERT INTO app.staged_rows (owner_id,id,batch_id,occurrence,kind,"
                "value_count) VALUES (:owner,:row,:batch,1,'unsupported',1)"
            ),
            dict(owner=OWNER_A, row=row_id, batch=batch_id),
        )
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    "INSERT INTO app.staged_values (owner_id,row_id,role,source,amount,"
                    "currency,missing_reason) VALUES (:owner,:row,:role,:source,CAST(:amount "
                    "AS numeric),:currency,:missing)"
                ),
                dict(
                    owner=OWNER_A,
                    row=row_id,
                    role=role,
                    source=source,
                    amount=amount,
                    currency=currency,
                    missing=missing,
                ),
            )


def test_sql_review_cannot_use_stale_context_skip_revision_or_reference_foreign_parent(imports):
    store, accounts, _ = imports
    own = setup(store, accounts)
    foreign = setup(store, accounts, OWNER_B)
    with store.transaction(OWNER_A) as unit:
        unit.decide(own[4].id, "include", expected_revision=0)
    with accounts.transaction(OWNER_A) as unit:
        replacement = unit.create(definition())
        unit.map(own[1].id, replacement.id, expected_revision=1)
    for source_id, rev, previous, mapping in (
        (own[1].id, 2, 1, 1),
        (own[1].id, 3, 1, 2),
        (foreign[1].id, 2, 1, 1),
    ):
        with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
            set_owner(connection, OWNER_A)
            connection.execute(
                text(
                    "INSERT INTO app.review_decisions (owner_id,row_id,revision,"
                    "previous_revision,action,reason,source_id,account_mapping_revision) "
                    "VALUES (:owner,:row,:revision,:previous,'include','reviewed',:source,"
                    ":mapping)"
                ),
                dict(
                    owner=OWNER_A,
                    row=own[4].id,
                    revision=rev,
                    previous=previous,
                    source=source_id,
                    mapping=mapping,
                ),
            )
    with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_A)
        connection.execute(
            text(
                "INSERT INTO app.staged_values (owner_id,row_id,role,source,amount,currency) "
                "VALUES (:owner,:row,'fee','0',0,'INR')"
            ),
            dict(owner=OWNER_A, row=foreign[4].id),
        )
    with store.transaction(OWNER_A) as unit:
        assert len(unit.history(own[4].id)) == 1


def test_irrelevant_components_are_blocked_in_python_and_sql(imports):
    store, accounts, _ = imports
    invalid = candidate(
        values=(
            StagedValue(role="net_cash", source="1", currency="INR"),
            StagedValue(role="quantity", source="1"),
        )
    )
    row = setup(store, accounts, OWNER_A, invalid)[4]
    with store.transaction(OWNER_A) as unit:
        assert unit.get_row(row.id).issue == "unsupported_component"
        assert (
            unit._execute("SELECT app.import_row_issue(:owner,:id)", id=row.id).scalar_one()
            == "unsupported_component"
        )
        with pytest.raises(ImportUnavailable):
            unit.decide(row.id, "include", expected_revision=0)


def test_completed_batches_cannot_gain_rows_or_values_and_runtime_cannot_edit_history(imports):
    store, accounts, admin = imports
    _, _, _, staged, row = setup(store, accounts)
    statements = [
        "INSERT INTO app.staged_values (owner_id,row_id,role,source,amount,currency) VALUES "
        "(:owner,:row,'fee','0',0,'INR')",
        "INSERT INTO app.staged_rows (owner_id,id,batch_id,occurrence,kind,value_count) "
        "VALUES (:owner,:new,:batch,2,'unsupported',0)",
        "UPDATE app.staged_values SET amount=0",
        "DELETE FROM app.staged_rows",
        "TRUNCATE app.review_decisions",
    ]
    for statement in statements:
        with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
            set_owner(connection, OWNER_A)
            connection.execute(
                text(statement), dict(owner=OWNER_A, row=row.id, batch=staged.id, new=uuid4())
            )
    with admin.connect() as connection:
        for table in TABLES:
            assert connection.execute(
                text(
                    "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE "
                    "oid=CAST(:table AS regclass)"
                ),
                dict(table="app." + table),
            ).scalar_one()
            assert not connection.execute(
                text("SELECT has_table_privilege('trading_auth',:table,'SELECT')"),
                dict(table="app." + table),
            ).scalar_one()
            for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
                assert not connection.execute(
                    text("SELECT has_table_privilege('trading_runtime',:table,:privilege)"),
                    dict(table="app." + table, privilege=privilege),
                ).scalar_one()
    with store._workspace._engine.begin() as connection:
        for table in TABLES:
            assert connection.execute(text(f"SELECT * FROM app.{table}")).all() == []


def test_concurrent_decisions_have_one_winner_and_failed_stage_rolls_back(imports, monkeypatch):
    store, accounts, _ = imports
    _, _, evidence, _, row = setup(store, accounts)
    barrier = Barrier(2)

    def decide(action):
        barrier.wait(timeout=10)
        try:
            with store.transaction(OWNER_A) as unit:
                return unit.decide(row.id, action, expected_revision=0).revision
        except ImportUnavailable:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, ("include", "exclude")))
    assert results.count(1) == results.count("conflict") == 1
    with store.transaction(OWNER_A) as unit:
        original = unit._execute

        def fail(sql, **params):
            result = original(sql, **params)
            if "INSERT INTO app.staged_values" in sql:
                raise RuntimeError("Synthetic interrupted staging")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(unit, "_execute", fail)
            with pytest.raises(RuntimeError):
                unit.stage(evidence.id, batch(version="2"), expected_revision=1)
        assert unit.latest_batch(evidence.id).revision == 1
    with pytest.raises(DatabaseFailure, match="ended"):
        unit.get_row(row.id)
    monkeypatch.setattr("trading_db.imports.MAX_RECORDS", 1)
    with store.transaction(OWNER_A) as unit:
        with pytest.raises(ImportUnavailable):
            unit.stage(evidence.id, batch(version="2"), expected_revision=1)
    with store._workspace._engine.connect() as connection:
        assert connection.execute(text("SELECT app.current_owner_id()")).scalar_one() is None


def test_migration_failure_is_atomic_and_prior_instruments_survive(database, monkeypatch):
    url, project = database
    migrate.apply(url(), project, target="0007_instruments")
    baseline = engine_for(url("bootstrap"), migration=True)
    try:
        with baseline.begin() as connection:
            connection.execute(
                text("INSERT INTO app.owners (id,is_active) VALUES (:owner,true)"),
                dict(owner=OWNER_A),
            )
            connection.execute(
                text(
                    "INSERT INTO app.instruments (owner_id,id,asset_class,name,isin) "
                    "VALUES (:owner,:id,'equity','Synthetic preserved','ZZ0000000016')"
                ),
                dict(owner=OWNER_A, id=OWNER_A),
            )
    finally:
        baseline.dispose()
    from alembic.operations import Operations

    original = Operations.execute

    def fail(self, sql, *args, **kwargs):
        result = original(self, sql, *args, **kwargs)
        if "CREATE TABLE app.staged_values" in str(sql):
            raise RuntimeError("Synthetic migration interruption")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Operations, "execute", fail)
        with pytest.raises(RuntimeError):
            migrate.apply(url(), project)
    assert migrate.revision(url(), project) == "0007_instruments"
    admin = engine_for(url("bootstrap"), migration=True)
    try:
        with admin.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT to_regclass('app.source_observations')")
                ).scalar_one()
                is None
            )
            assert (
                connection.execute(text("SELECT to_regclass('app.instruments')")).scalar_one()
                is not None
            )
        migrate.apply(url(), project)
        migrate.apply(url(), project)
        migrate.apply(url(), project, direction="downgrade", target="0007_instruments")
        migrate.apply(url(), project)
        with admin.connect() as connection:
            assert connection.execute(text("SELECT name,isin FROM app.instruments")).one() == (
                "Synthetic preserved",
                "ZZ0000000016",
            )
    finally:
        admin.dispose()


def test_forged_models_are_revalidated_without_financial_serialization_warnings(imports):
    store, accounts, _ = imports
    evidence = setup(store, accounts)[2]
    forged = StagedValue.model_construct(role="net_cash", source=123.45, currency="INR")
    invalid = batch(candidate().model_copy(update={"values": (forged,)}), version="2")
    with store.transaction(OWNER_A) as unit, warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        with pytest.raises(ValidationError) as error:
            unit.stage(evidence.id, invalid, expected_revision=1)
        assert "123.45" not in str(error.value)
        assert captured == []
        assert unit.latest_batch(evidence.id).revision == 1
