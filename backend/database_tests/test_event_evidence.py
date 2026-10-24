"""Provider identity reuse is exact, owned, recoverable and independent of row similarity."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_events import seed
from database_tests.test_imports import batch, observation
from database_tests.test_ownership import DISABLED, OWNER_A, OWNER_B, UNKNOWN, set_owner
from trading_db import migrate, recovery
from trading_db.account_keys import ReferenceKeys
from trading_db.connections import DatabaseFailure, engine_for
from trading_db.event_evidence import EventEvidenceDatabase, EventEvidenceUnavailable
from trading_db.events import EventDatabase, EventUnavailable
from trading_db.imports import ImportDatabase, ImportTransaction, ImportUnavailable
from trading_db.provider_keys import ProviderKeys
from trading_db.workspace import OwnerAccessDenied

TABLES = ("event_provider_identities", "event_evidence_links")


@pytest.fixture
def evidence(accounts, database):
    url, project = database
    store = EventEvidenceDatabase(url("runtime"), project, ReferenceKeys({1: b"a" * 32}, 1))
    try:
        yield store, *accounts
    finally:
        store.close()


def extra(accounts, source, original, owner=OWNER_A, **changes):
    with accounts.transaction(owner) as unit:
        staging = ImportTransaction(unit._unit)
        observed = staging.observation(
            source.id, observation().model_copy(update={"digest": uuid4().hex * 2})
        )
        staged = staging.stage(
            observed.id, batch(original.model_copy(update=changes)), expected_revision=0
        )
        row = staging.rows(staged.id)[0]
        staging.decide(row.id, "include", expected_revision=0)
        return row


@pytest.mark.parametrize(
    "kind",
    [
        "cash_movement",
        "buy",
        "sell",
        "subscription",
        "redemption",
        "dividend",
        "fee",
        "withholding",
    ],
)
def test_same_provider_identity_links_evidence_without_duplicate_movements(evidence, kind):
    store, accounts, _ = evidence
    account, source, position, rows = seed(accounts, kind=kind, states=("posted", "posted"))
    kwargs = dict(
        expected_review_revision=1,
        position_id=position.id if position else None,
        provider_reference="FAKE-REFERENCE",
    )
    with store.transaction(OWNER_A) as unit:
        first = unit.record(rows[0].id, **kwargs)
        second = unit.record(rows[1].id, **kwargs)
        assert first.event == second.event and not first.reused and second.reused
        assert unit.record(rows[1].id, **kwargs) == second
        assert len(unit.list(first.event.id)) == 2
        assert "FAKE-REFERENCE" not in repr(first)
    with accounts.transaction(OWNER_A) as unit:
        assert (
            unit._execute(
                "SELECT count(*) FROM app.financial_events WHERE owner_id=:owner"
            ).scalar_one()
            == 1
        )
        assert (
            unit._execute(
                "SELECT count(*) FROM app.cash_movements WHERE owner_id=:owner"
            ).scalar_one()
            == 1
        )


def test_absent_or_different_reference_preserves_identical_legitimate_transactions(evidence):
    store, accounts, _ = evidence
    _, _, _, rows = seed(accounts, kind="cash_movement", states=("posted",) * 4)
    with store.transaction(OWNER_A) as unit:
        records = [
            unit.record(
                row.id,
                expected_review_revision=1,
                provider_reference=None if index < 2 else f"FAKE-{index}",
            )
            for index, row in enumerate(rows)
        ]
        assert len({record.event.id for record in records}) == 4


def test_numeric_meaning_matches_but_source_format_remains_evidence(evidence):
    store, accounts, _ = evidence
    _, source, _, rows = seed(accounts, kind="cash_movement")
    changed = extra(
        accounts,
        source,
        rows[0].definition,
        values=(rows[0].definition.values[0].model_copy(update={"source": "-12.3"}),),
    )
    with store.transaction(OWNER_A) as unit:
        first = unit.record(rows[0].id, expected_review_revision=1, provider_reference="FAKE")
        second = unit.record(changed.id, expected_review_revision=1, provider_reference="FAKE")
        assert first.event == second.event
        assert second.event.components[0].source == "-12.30"
    with accounts.transaction(OWNER_A) as unit:
        assert (
            ImportTransaction(unit._unit).get_row(changed.id).definition.values[0].source == "-12.3"
        )


@pytest.mark.parametrize("change", ["amount", "posting", "date", "missing_component"])
def test_changed_economics_conflicts_under_same_provider_identity(evidence, change):
    store, accounts, _ = evidence
    _, source, position, rows = seed(accounts)
    original = rows[0].definition
    changes = {
        "amount": dict(
            values=tuple(
                v.model_copy(update={"source": "-13.00"}) if v.role == "net_cash" else v
                for v in original.values
            )
        ),
        "posting": dict(posting_state="pending"),
        "date": dict(settlement_date="2026-10-24"),
        "missing_component": dict(values=tuple(v for v in original.values if v.role != "fee")),
    }[change]
    changed = extra(accounts, source, original, **changes)
    with store.transaction(OWNER_A) as unit:
        unit.record(
            rows[0].id,
            expected_review_revision=1,
            position_id=position.id,
            provider_reference="FAKE",
        )
    with pytest.raises(EventEvidenceUnavailable):
        with store.transaction(OWNER_A) as unit:
            unit.record(
                changed.id,
                expected_review_revision=1,
                position_id=position.id,
                provider_reference="FAKE",
            )
    with store.transaction(OWNER_A) as unit:
        assert unit.get(changed.id) is None


def test_linked_review_cannot_reopen_or_be_consumed_again(evidence, database):
    store, accounts, _ = evidence
    _, _, _, rows = seed(accounts, kind="cash_movement", states=("posted", "posted"))
    with store.transaction(OWNER_A) as unit:
        for row in rows:
            unit.record(row.id, expected_review_revision=1, provider_reference="FAKE")
    url, project = database
    imports, events = (
        ImportDatabase(url("runtime"), project),
        EventDatabase(url("runtime"), project),
    )
    try:
        with pytest.raises(ImportUnavailable):
            with imports.transaction(OWNER_A) as unit:
                unit.decide(rows[1].id, "reopen", expected_revision=1)
        with pytest.raises(EventUnavailable):
            with events.transaction(OWNER_A) as unit:
                unit.record(rows[1].id, expected_review_revision=1)
    finally:
        imports.close()
        events.close()


def test_owner_isolation_unknown_ids_and_reference_scope(evidence):
    store, accounts, _ = evidence
    owned = seed(accounts, kind="cash_movement")
    foreign = seed(accounts, owner=OWNER_B, kind="cash_movement")
    saved = []
    for owner, data in ((OWNER_A, owned), (OWNER_B, foreign)):
        with store.transaction(owner) as unit:
            saved.append(
                unit.record(
                    data[3][0].id, expected_review_revision=1, provider_reference="SAME-FAKE"
                )
            )
    assert saved[0].event.id != saved[1].event.id
    with store.transaction(OWNER_A) as unit:
        assert unit.get(foreign[3][0].id) is None
        assert unit.list(saved[1].event.id) == ()
        for row_id in (foreign[3][0].id, uuid4()):
            with pytest.raises(EventEvidenceUnavailable):
                unit.record(row_id, expected_review_revision=1, provider_reference="SAME-FAKE")
    for owner in (DISABLED, UNKNOWN):
        with pytest.raises(OwnerAccessDenied):
            with store.transaction(owner):
                pytest.fail("Inactive owner entered transaction")


def test_concurrent_same_identity_records_once_and_failure_rolls_back(evidence):
    store, accounts, _ = evidence
    _, _, _, rows = seed(accounts, kind="cash_movement", states=("posted",) * 3)

    def record(row):
        with store.transaction(OWNER_A) as unit:
            return unit.record(
                row.id, expected_review_revision=1, provider_reference="FAKE"
            ).event.id

    with ThreadPoolExecutor(2) as pool:
        assert len(set(pool.map(record, rows[:2]))) == 1
    with pytest.raises(RuntimeError):
        with store.transaction(OWNER_A) as unit:
            unit.record(rows[2].id, expected_review_revision=1, provider_reference="NEW-FAKE")
            raise RuntimeError("Synthetic interruption")
    with store.transaction(OWNER_A) as unit:
        assert unit.get(rows[2].id) is None
        assert not unit.record(
            rows[2].id, expected_review_revision=1, provider_reference="NEW-FAKE"
        ).reused


def test_key_rotation_preserves_matching_and_missing_keys_fail_closed(evidence, database):
    store, accounts, admin = evidence
    _, _, _, rows = seed(accounts, kind="cash_movement", states=("posted", "posted"))
    with store.transaction(OWNER_A) as unit:
        first = unit.record(rows[0].id, expected_review_revision=1, provider_reference="FAKE")
    url, project = database
    for keys in (None, ReferenceKeys({1: b"x" * 32}, 1), ReferenceKeys({2: b"b" * 32}, 2)):
        broken = EventEvidenceDatabase(url("runtime"), project, keys)
        try:
            with pytest.raises(EventEvidenceUnavailable):
                with broken.transaction(OWNER_A) as unit:
                    unit.record(rows[1].id, expected_review_revision=1, provider_reference="FAKE")
        finally:
            broken.close()
    rotating = EventEvidenceDatabase(
        url("runtime"), project, ReferenceKeys({1: b"a" * 32, 2: b"b" * 32}, 2)
    )
    try:
        with rotating.transaction(OWNER_A) as unit:
            assert unit.rotate_references() == 1
            assert unit.rotate_references() == 0
            assert (
                unit.record(rows[1].id, expected_review_revision=1, provider_reference="FAKE").event
                == first.event
            )
        with admin.connect() as connection:
            assert connection.execute(
                text("SELECT key_version,key_revision FROM app.event_provider_identities")
            ).one() == (2, 2)
    finally:
        rotating.close()


def test_policies_grants_direct_sql_tampering_and_migration_guard(evidence, database):
    store, accounts, admin = evidence
    _, _, _, rows = seed(accounts, kind="cash_movement", states=("posted", "posted"))
    with store.transaction(OWNER_A) as unit:
        first = unit.record(rows[0].id, expected_review_revision=1, provider_reference="FAKE")
    url, project = database
    runtime = engine_for(url("runtime"))
    try:
        for table in TABLES:
            with admin.connect() as connection:
                assert connection.execute(
                    text(
                        "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                        "WHERE oid=CAST(:table AS regclass)"
                    ),
                    dict(table="app." + table),
                ).scalar_one()
                assert not connection.execute(
                    text("SELECT has_table_privilege('trading_auth',:table,'SELECT')"),
                    dict(table="app." + table),
                ).scalar_one()
            with pytest.raises(DBAPIError):
                with runtime.begin() as connection:
                    set_owner(connection, OWNER_A)
                    connection.execute(text(f"DELETE FROM app.{table}"))
        base = dict(
            owner_id=OWNER_A,
            source_row_id=rows[1].id,
            review_revision=1,
            identity_id=first.identity_id,
            event_id=first.event.id,
            event_revision=1,
        )
        for changes in (
            dict(owner_id=OWNER_B),
            dict(identity_id=uuid4()),
            dict(event_id=uuid4()),
            dict(review_revision=2),
            dict(created_at="2020-01-01"),
        ):
            values = base | changes
            with pytest.raises(DBAPIError):
                with runtime.begin() as connection:
                    set_owner(connection, values["owner_id"])
                    connection.execute(
                        text(
                            f"INSERT INTO app.event_evidence_links ({','.join(values)}) "
                            f"VALUES ({','.join(':' + key for key in values)})"
                        ),
                        values,
                    )
        with pytest.raises(DBAPIError):
            migrate.apply(url(), project, direction="downgrade", target="0012_market_evidence")
        assert migrate.revision(url(), project) == recovery.HEAD
    finally:
        runtime.dispose()


def test_bounded_reads_and_budget(evidence, monkeypatch):
    store, accounts, _ = evidence
    _, _, _, rows = seed(accounts, kind="cash_movement", states=("posted", "posted"))
    with store.transaction(OWNER_A) as unit:
        first = unit.record(rows[0].id, expected_review_revision=1, provider_reference="FAKE")
        for limit in (0, 101, True):
            with pytest.raises(DatabaseFailure):
                unit.list(first.event.id, limit=limit)
        monkeypatch.setattr("trading_db.event_evidence.MAX_RECORDS", 1)
        with pytest.raises(EventEvidenceUnavailable):
            unit.record(rows[1].id, expected_review_revision=1, provider_reference="OTHER")


def test_correction_requires_explicit_history_and_historical_retry_stays_original(
    evidence, database
):
    store, accounts, _ = evidence
    _, source, _, rows = seed(accounts, kind="cash_movement")
    with store.transaction(OWNER_A) as unit:
        original = unit.record(rows[0].id, expected_review_revision=1, provider_reference="FAKE")
    updated = extra(
        accounts,
        source,
        rows[0].definition,
        values=(rows[0].definition.values[0].model_copy(update={"source": "-13.00"}),),
    )
    url, project = database
    events = EventDatabase(url("runtime"), project)
    try:
        with events.transaction(OWNER_A) as unit:
            changed = unit.correct(
                original.event.id,
                updated.id,
                expected_revision=1,
                expected_review_revision=1,
                reason="source_correction",
            )
        duplicate = extra(accounts, source, updated.definition)
        with store.transaction(OWNER_A) as unit:
            corroboration = unit.record(
                duplicate.id, expected_review_revision=1, provider_reference="FAKE"
            )
            assert corroboration.event == changed and corroboration.reused
            assert (
                unit.record(rows[0].id, expected_review_revision=1, provider_reference="FAKE")
                == original
            )
            for changes in (
                dict(provider_reference="OTHER"),
                dict(provider_reference=None),
                dict(expected_review_revision=2),
            ):
                with pytest.raises(EventEvidenceUnavailable):
                    unit.record(
                        rows[0].id,
                        **(dict(expected_review_revision=1, provider_reference="FAKE") | changes),
                    )
        cancellation = extra(
            accounts,
            source,
            rows[0].definition,
            kind="cancellation",
            posting_state=None,
            values=(),
            booking_date="2026-10-24",
        )
        with events.transaction(OWNER_A) as unit:
            unit.correct(
                original.event.id,
                cancellation.id,
                expected_revision=2,
                expected_review_revision=1,
                reason="cancellation",
            )
        later = extra(accounts, source, updated.definition)
        with pytest.raises(EventEvidenceUnavailable):
            with store.transaction(OWNER_A) as unit:
                unit.record(later.id, expected_review_revision=1, provider_reference="FAKE")
    finally:
        events.close()


def test_equal_references_from_different_source_accounts_stay_distinct(evidence):
    store, accounts, _ = evidence
    account, _, _, rows = seed(accounts, kind="cash_movement")
    with accounts.transaction(OWNER_A) as unit:
        source = unit.source("hdfc_statement", "FAKE-OTHER-SOURCE")
        unit.map(source.id, account.id, expected_revision=0)
    duplicate = extra(accounts, source, rows[0].definition)
    with store.transaction(OWNER_A) as unit:
        first = unit.record(rows[0].id, expected_review_revision=1, provider_reference="SAME-FAKE")
        second = unit.record(
            duplicate.id, expected_review_revision=1, provider_reference="SAME-FAKE"
        )
        assert first.event.id != second.event.id


def test_direct_sql_economics_mismatch_and_second_consumption_cannot_bypass_service(
    evidence, database
):
    store, accounts, _ = evidence
    _, source, _, rows = seed(accounts, kind="cash_movement", states=("posted", "posted"))
    with store.transaction(OWNER_A) as unit:
        original = unit.record(rows[0].id, expected_review_revision=1, provider_reference="FAKE")
        unit.record(rows[1].id, expected_review_revision=1, provider_reference="FAKE")
    changed = extra(
        accounts,
        source,
        rows[0].definition,
        values=(rows[0].definition.values[0].model_copy(update={"source": "-13.00"}),),
    )
    url, _ = database
    runtime = engine_for(url("runtime"))
    try:
        with pytest.raises(DBAPIError):
            with runtime.begin() as connection:
                set_owner(connection, OWNER_A)
                connection.execute(
                    text(
                        "INSERT INTO app.event_evidence_links "
                        "(owner_id,source_row_id,review_revision,identity_id,"
                        "event_id,event_revision) "
                        "VALUES (:owner,:row,1,:identity,:event,1)"
                    ),
                    dict(
                        owner=OWNER_A,
                        row=changed.id,
                        identity=original.identity_id,
                        event=original.event.id,
                    ),
                )
        with pytest.raises(DBAPIError):
            with runtime.begin() as connection:
                set_owner(connection, OWNER_A)
                new_id = uuid4()
                for table, id_column in (
                    ("financial_events", "id"),
                    ("event_components", "event_id"),
                    ("cash_movements", "event_id"),
                ):
                    columns = [key for key in recovery.COLUMNS[table] if key != "created_at"]
                    select = [
                        ":new" if key == id_column else ":row" if key == "source_row_id" else key
                        for key in columns
                    ]
                    connection.execute(
                        text(
                            f"INSERT INTO app.{table} ({','.join(columns)}) "
                            f"SELECT {','.join(select)} FROM app.{table} WHERE owner_id=:owner "
                            f"AND {id_column}=:event AND revision=1"
                        ),
                        dict(owner=OWNER_A, event=original.event.id, new=new_id, row=rows[1].id),
                    )
    finally:
        runtime.dispose()


def test_corrupted_match_index_fails_before_creating_another_event(evidence, database):
    store, accounts, admin = evidence
    _, _, _, rows = seed(accounts, kind="cash_movement", states=("posted", "posted"))
    with store.transaction(OWNER_A) as unit:
        first = unit.record(rows[0].id, expected_review_revision=1, provider_reference="FAKE")
    keys = ReferenceKeys({1: b"a" * 32, 2: b"b" * 32}, 2)
    with admin.begin() as connection:
        row = (
            connection.execute(
                text("SELECT * FROM app.event_provider_identities WHERE id=:id"),
                dict(id=first.identity_id),
            )
            .mappings()
            .one()
        )
        sealed = ProviderKeys(keys).seal(
            OWNER_A, first.identity_id, row["source_id"], row["kind"], "FAKE"
        )
        sealed["fingerprint"] = "0" * 64
        connection.execute(
            text(
                "UPDATE app.event_provider_identities SET key_version=:key_version, "
                "key_check=:key_check,fingerprint=:fingerprint,"
                "encrypted_reference=:encrypted_reference "
                "WHERE id=:id"
            ),
            dict(id=first.identity_id, **sealed),
        )
    url, project = database
    rotated = EventEvidenceDatabase(url("runtime"), project, keys)
    try:
        with pytest.raises(EventEvidenceUnavailable):
            with rotated.transaction(OWNER_A) as unit:
                unit.record(rows[1].id, expected_review_revision=1, provider_reference="FAKE")
    finally:
        rotated.close()
    with store.transaction(OWNER_A) as unit:
        assert unit.get(rows[1].id) is None


def test_upgrade_failure_empty_roundtrip_and_existing_event_preservation(
    evidence, database, monkeypatch
):
    store, accounts, admin = evidence
    _, _, _, rows = seed(accounts, kind="cash_movement")
    with store.transaction(OWNER_A) as unit:
        saved = unit.record(rows[0].id, expected_review_revision=1)
    url, project = database
    migrate.apply(url(), project, direction="downgrade", target="0012_market_evidence")
    from alembic.operations import Operations

    execute = Operations.execute

    def fail(self, statement, *args, **kwargs):
        result = execute(self, statement, *args, **kwargs)
        if "CREATE TABLE app.event_evidence_links" in str(statement):
            raise RuntimeError("Synthetic interruption")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Operations, "execute", fail)
        with pytest.raises(RuntimeError):
            migrate.apply(url(), project)
    assert migrate.revision(url(), project) == "0012_market_evidence"
    with admin.connect() as connection:
        assert (
            connection.execute(
                text("SELECT to_regclass('app.event_provider_identities')")
            ).scalar_one()
            is None
        )
    migrate.apply(url(), project)
    migrate.apply(url(), project)
    with store.transaction(OWNER_A) as unit:
        assert unit.record(rows[0].id, expected_review_revision=1) == saved


def test_late_link_failure_rolls_back_new_event_identity_and_movements(evidence, monkeypatch):
    store, accounts, _ = evidence
    _, _, _, rows = seed(accounts, kind="cash_movement")
    with store.transaction(OWNER_A) as unit:
        budget = unit._budget

        def fail(table):
            if table == "event_evidence_links":
                raise EventEvidenceUnavailable()
            budget(table)

        with monkeypatch.context() as patch:
            patch.setattr(unit, "_budget", fail)
            with pytest.raises(EventEvidenceUnavailable):
                unit.record(rows[0].id, expected_review_revision=1, provider_reference="FAKE")
        for table in (*TABLES, "financial_events", "event_components", "cash_movements"):
            assert (
                unit._execute(
                    f"SELECT count(*) FROM app.{table} WHERE owner_id=:owner"
                ).scalar_one()
                == 0
            )
        assert not unit.record(
            rows[0].id, expected_review_revision=1, provider_reference="FAKE"
        ).reused
