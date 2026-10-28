"""NAV source positions preserve identity, owner limits, migration and encrypted history."""

import copy
import json
from decimal import Decimal
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_instruments import instruments as instruments
from database_tests.test_instruments import security
from database_tests.test_markets import markets as markets
from database_tests.test_markets import quote, raw_observation
from database_tests.test_ownership import OWNER_A, OWNER_B, set_owner
from database_tests.test_preferences import sql
from tests.test_markets import definition
from trading_db import migrate, recovery
from trading_db.connections import DatabaseFailure, engine_for
from trading_db.instruments import SchemeDefinition
from trading_db.local import disposable
from trading_db.markets import MarketDatabase, MarketUnavailable

PREDECESSOR = "0024_bank_account_setup"


def nav(markets, owner=OWNER_A):
    _, identities, _, _ = markets
    with identities.transaction(owner) as unit:
        scheme = unit.scheme(SchemeDefinition(name="Synthetic source-position fund"))
        fund = unit.create(
            security(
                1,
                "mutual_fund",
                fund_scheme_id=scheme.id,
                fund_plan="direct",
                fund_option="growth",
                fund_currency="INR",
            )
        )
    return definition(
        kind="nav",
        instrument_id=fund.id,
        currency="INR",
        base_currency=None,
        quote_currency=None,
        basis="nav",
        namespace="amfi_nav_report",
        contract_version=2,
        occurrence=25000,
    )


def constraints(admin):
    return dict(
        sql(
            admin,
            "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='app.market_observations'::regclass ORDER BY conname",
        )
    )


def security_state(admin):
    return sql(
        admin,
        "SELECT relname,relrowsecurity,relforcerowsecurity,"
        "has_table_privilege('trading_runtime',oid,'UPDATE'),"
        "has_table_privilege('trading_runtime',oid,'DELETE'),"
        "has_table_privilege('trading_auth',oid,'SELECT') "
        "FROM pg_class WHERE relnamespace='app'::regnamespace AND relname IN "
        "('market_observations','market_selections') ORDER BY relname",
    )


@pytest.mark.parametrize("role", ["runtime", "bootstrap"])
def test_sql_accepts_only_versioned_source_domains_with_existing_targets(markets, database, role):
    valid_nav = nav(markets)
    valid_quote = quote(markets)
    sources = [
        valid_nav.model_copy(update={"contract_version": 1, "occurrence": 1000}),
        valid_nav.model_copy(
            update={"contract_version": 1, "occurrence": 1000, "namespace": "manual_evidence"}
        ),
        valid_quote,
        valid_quote.model_copy(update={"namespace": "exchange_quote_report"}),
        definition(),
        definition(namespace="fx_rate_report"),
    ] + [valid_nav.model_copy(update={"occurrence": value}) for value in (1, 1000, 1001, 25000)]
    url, _ = database
    engine = engine_for(url(role), migration=role == "bootstrap")
    try:
        with engine.begin() as connection:
            if role == "runtime":
                set_owner(connection, OWNER_A)
            for index, source in enumerate(sources):
                raw_observation(connection, source, digest=f"{index + 1:064x}")
            bad = [
                (valid_nav, {"occurrence": 0}),
                (valid_nav, {"occurrence": 25001}),
                (valid_nav, {"contract_version": 1, "occurrence": 1001}),
                (valid_nav, {"contract_version": 0}),
                (valid_nav, {"contract_version": 3}),
                (valid_nav, {"namespace": "manual_evidence", "occurrence": 1}),
                (valid_quote, {"contract_version": 2}),
                (valid_quote, {"contract_version": 2, "namespace": "exchange_quote_report"}),
                (definition(), {"contract_version": 2}),
                (definition(namespace="fx_rate_report"), {"contract_version": 2}),
            ]
            for source, changes in bad:
                with pytest.raises(DBAPIError):
                    with connection.begin_nested():
                        raw_observation(connection, source, digest="f" * 64, **changes)
        with markets[0].transaction(OWNER_A) as unit:
            assert unit.list(valid_nav.target())
        assert sql(markets[3], "SELECT count(*) FROM app.market_observations")[0][0] == len(sources)
    finally:
        engine.dispose()


def test_original_positions_replay_and_contract_version_cannot_split_identity(markets, database):
    store, _, _, admin = markets
    valid = nav(markets)
    with store.transaction(OWNER_A) as unit:
        high = unit.record(valid)
        assert unit.record(valid) == high
        assert high.definition.source == "83.123456789012"
        assert high.definition.reported().value == Decimal("83.123456789012")
        for first_version, second_version, digest in ((1, 2, "b"), (2, 1, "c")):
            first = valid.model_copy(
                update={"occurrence": 1, "contract_version": first_version, "digest": digest * 64}
            )
            original = unit.record(first)
            assert unit.record(first) == original
            with pytest.raises(MarketUnavailable):
                unit.record(first.model_copy(update={"contract_version": second_version}))
        assert len(unit.list(valid.target())) == 3
        chosen = unit.select(high.id, expected_revision=0)
        assert unit.resolve(chosen.id).observation == high
    with store.transaction(OWNER_B) as unit:
        assert unit.get(high.id) is None and unit.selection(chosen.id) is None
    url, _ = database
    runtime = engine_for(url("runtime"))
    try:
        with pytest.raises(DBAPIError):
            with runtime.begin() as connection:
                set_owner(connection, OWNER_A)
                raw_observation(
                    connection, valid, digest="b" * 64, occurrence=1, contract_version=2
                )
        assert sql(admin, "SELECT count(*) FROM app.market_observations")[0][0] == 3
    finally:
        runtime.dispose()


def test_high_position_keeps_service_and_sql_owner_record_quotas(markets, database, monkeypatch):
    store, _, _, admin = markets
    valid = nav(markets)
    with store.transaction(OWNER_A) as unit:
        monkeypatch.setattr("trading_db.markets.MAX_RECORDS", 1)
        first = unit.record(valid)
        assert unit.record(valid) == first
        with pytest.raises(MarketUnavailable):
            unit.record(valid.model_copy(update={"digest": "b" * 64}))
    # Bootstrap fills the existing quota with legacy observations. The runtime
    # trigger must reject the high-position record even if service code is bypassed.
    with admin.begin() as connection:
        for occurrence in range(1, 1000):
            raw_observation(connection, valid, occurrence=occurrence, contract_version=1)
    url, _ = database
    runtime = engine_for(url("runtime"))
    try:
        with pytest.raises(DBAPIError, match="Market evidence limit reached"):
            with runtime.begin() as connection:
                set_owner(connection, OWNER_A)
                raw_observation(connection, valid, digest="b" * 64)
        assert sql(admin, "SELECT count(*) FROM app.market_observations")[0][0] == 1000
    finally:
        runtime.dispose()


def test_upgrade_is_atomic_repeatable_and_legacy_history_can_round_trip(
    markets, database, monkeypatch
):
    store, _, _, admin = markets
    valid = nav(markets).model_copy(update={"contract_version": 1, "occurrence": 1000})
    with store.transaction(OWNER_A) as unit:
        original = unit.record(valid)
        selected = unit.select(original.id, expected_revision=0)
    url, project = database
    migrate.apply(url(), project, direction="downgrade", target=PREDECESSOR)
    old = constraints(admin)
    assert "market_observations_occurrence_check" in old
    assert "market_observations_contract_version_check" in old
    assert "market_source_occurrence_contract" not in old
    before_security = security_state(admin)
    assert all(row[1:] == (True, True, False, False, False) for row in before_security)
    from alembic.operations import Operations

    original_execute = Operations.execute

    def interrupted(self, statement, *args, **kwargs):
        result = original_execute(self, statement, *args, **kwargs)
        if "ADD CONSTRAINT market_source_occurrence_contract" in str(statement):
            raise RuntimeError("Synthetic migration interruption.")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Operations, "execute", interrupted)
        with pytest.raises(RuntimeError, match="Synthetic"):
            migrate.apply(url(), project)
    assert migrate.revision(url(), project) == PREDECESSOR
    assert constraints(admin) == old and security_state(admin) == before_security
    with store.transaction(OWNER_A) as unit:
        assert unit.get(original.id) == original
        assert unit.resolve(selected.id).observation == original
    migrate.apply(url(), project)
    migrate.apply(url(), project)
    current = constraints(admin)
    assert "market_source_occurrence_contract" in current
    assert "25000" in current["market_source_occurrence_contract"]
    assert "market_observations_occurrence_check" not in current
    assert "market_observations_contract_version_check" not in current
    assert security_state(admin) == before_security
    migrate.apply(url(), project, direction="downgrade", target=PREDECESSOR)
    assert constraints(admin) == old
    migrate.apply(url(), project)
    with store.transaction(OWNER_A) as unit:
        assert unit.record(valid) == original
        assert unit.selection_history(selected.id) == (selected,)


@pytest.mark.parametrize(
    "occurrence,state,owner",
    [(value, "unselected", OWNER_A) for value in (1, 1000, 1001, 25000)]
    + [(1, "cleared", OWNER_A), (1, "superseded", OWNER_A), (1, "unselected", OWNER_B)],
)
def test_every_retained_v2_prevents_downgrade_atomically(
    markets, database, occurrence, state, owner
):
    store, _, _, admin = markets
    valid = nav(markets, owner).model_copy(update={"occurrence": occurrence})
    with store.transaction(owner) as unit:
        original = unit.record(valid)
        if state == "cleared":
            chosen = unit.select(original.id, expected_revision=0)
            unit.clear(chosen.id, expected_revision=1)
        if state == "superseded":
            unit.record(
                valid.model_copy(
                    update={"contract_version": 1, "digest": "b" * 64, "previous_id": original.id}
                )
            )
    before_constraints, before_security = constraints(admin), security_state(admin)
    before_rows = sql(admin, "SELECT * FROM app.market_observations ORDER BY id")
    before_choices = sql(admin, "SELECT * FROM app.market_selections ORDER BY id,revision")
    url, project = database
    with pytest.raises(DBAPIError, match="forward migration"):
        migrate.apply(url(), project, direction="downgrade", target=PREDECESSOR)
    assert migrate.revision(url(), project) == recovery.HEAD
    assert constraints(admin) == before_constraints and security_state(admin) == before_security
    assert sql(admin, "SELECT * FROM app.market_observations ORDER BY id") == before_rows
    assert sql(admin, "SELECT * FROM app.market_selections ORDER BY id,revision") == before_choices
    with store.transaction(owner) as unit:
        assert unit.get(original.id) == original and unit.record(valid) == original
        assert unit.record(
            valid.model_copy(update={"digest": "c" * 64})
        ).definition == valid.model_copy(update={"digest": "c" * 64})


def test_encrypted_restore_preserves_positions_history_and_rejects_partial_import(
    markets, database
):
    store, _, _, _ = markets
    a = nav(markets).model_copy(update={"occurrence": 1})
    b = nav(markets, OWNER_B)
    with store.transaction(OWNER_A) as unit:
        original = unit.record(a)
        selection = unit.select(original.id, expected_revision=0)
    # Historical selection is committed before a later correction supersedes it.
    with store.transaction(OWNER_A) as unit:
        corrected = unit.record(
            a.model_copy(
                update={"contract_version": 1, "digest": "b" * 64, "previous_id": original.id}
            )
        )
        unit.select(corrected.id, expected_revision=1, reason="correction")
        unit.clear(selection.id, expected_revision=2)
        later = unit.record(a.model_copy(update={"occurrence": 1001}))
        history = unit.selection_history(selection.id)
    with store.transaction(OWNER_B) as unit:
        other = unit.record(b)
        other_choice = unit.select(other.id, expected_revision=0)
    url, project = database
    key = Fernet.generate_key()
    encrypted = recovery.export_snapshot(url("bootstrap"), project, key)
    assert a.source.encode() not in encrypted
    payload = json.loads(Fernet(key).decrypt(encrypted))
    assert payload["format"] == 21 and payload["revision"] == recovery.HEAD
    payload["rows"]["market_observations"].reverse()
    with disposable() as target:
        migrate.apply(target.url("migrator"), target.project)
        admin = engine_for(target.url("bootstrap"), migration=True)
        restored = MarketDatabase(target.url("runtime"), target.project)
        try:
            for changes in (
                {"contract_version": "2"},
                {"occurrence": "25000"},
                {"contract_version": True},
                {"occurrence": False},
                {"contract_version": 1, "occurrence": 1001},
                {"contract_version": 2, "namespace": "manual_evidence"},
                {"amount": "999"},
                {"instrument_id": str(uuid4())},
            ):
                damaged = copy.deepcopy(payload)
                damaged["rows"]["market_observations"][-1].update(changes)
                with pytest.raises(DatabaseFailure):
                    recovery.restore_snapshot(
                        target.url("bootstrap"),
                        target.project,
                        Fernet(key).encrypt(json.dumps(damaged).encode()),
                        key,
                    )
                for table in recovery.COLUMNS:
                    assert sql(admin, f"SELECT count(*) FROM app.{table}")[0][0] == 0
            for field, value in (
                ("format", 20),
                ("revision", PREDECESSOR),
                ("migration_digest", "old"),
            ):
                damaged = copy.deepcopy(payload)
                damaged[field] = value
                with pytest.raises(DatabaseFailure):
                    recovery.restore_snapshot(
                        target.url("bootstrap"),
                        target.project,
                        Fernet(key).encrypt(json.dumps(damaged).encode()),
                        key,
                    )
            counts = recovery.restore_snapshot(
                target.url("bootstrap"),
                target.project,
                Fernet(key).encrypt(json.dumps(payload).encode()),
                key,
            )
            assert counts["market_observations"] == 4 and counts["market_selections"] == 4
            assert counts["auth_sessions"] == 0
            with restored.transaction(OWNER_A) as unit:
                for observed in (original, corrected, later):
                    assert unit.get(observed.id) == observed
                    assert unit.record(observed.definition) == observed
                assert unit.selection_history(selection.id) == history
                assert unit.resolve(selection.id).state == "unselected"
                assert unit.get(other.id) is None
                with pytest.raises(MarketUnavailable):
                    unit.record(a.model_copy(update={"contract_version": 1}))
            with restored.transaction(OWNER_B) as unit:
                assert unit.resolve(other_choice.id).observation == other
                assert unit.get(original.id) is None
            with pytest.raises(DBAPIError, match="forward migration"):
                migrate.apply(
                    target.url("migrator"),
                    target.project,
                    direction="downgrade",
                    target=PREDECESSOR,
                )
            assert migrate.revision(target.url("migrator"), target.project) == recovery.HEAD
            assert all(row[2] for row in security_state(admin))
        finally:
            restored.close()
            admin.dispose()
