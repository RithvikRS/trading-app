"""Encrypted synthetic export restored into a separately bootstrapped PostgreSQL cluster."""

import json
import time
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from starlette.testclient import TestClient

from database_tests.test_preferences import environment as environment
from database_tests.test_preferences import login, sql
from tests.auth_support import ISSUER, SUBJECT
from tests.browser_support import BrowserProviderStub
from trading_api.application import create_app
from trading_auth.browser import BrowserAuth
from trading_auth.models import AuthenticationDenied
from trading_auth.session_models import verifier
from trading_db import migrate, recovery
from trading_db.account_keys import ReferenceKeys, load_keys
from trading_db.accounts import AccountDatabase, AccountDefinition
from trading_db.connections import DatabaseFailure, engine_for
from trading_db.enrollment import provision_owner
from trading_db.event_evidence import EventEvidenceTransaction
from trading_db.events import EventTransaction
from trading_db.import_contracts import (
    BatchDefinition,
    CandidateDefinition,
    ObservationDefinition,
    StagedValue,
)
from trading_db.imports import ImportTransaction
from trading_db.instruments import (
    IdentifierDefinition,
    InstrumentDefinition,
    InstrumentTransaction,
    ListingDefinition,
    SchemeDefinition,
)
from trading_db.local import ROOT, disposable, private_directory
from trading_db.lots import LotTransaction
from trading_db.market_contracts import MarketDefinition
from trading_db.markets import MarketTransaction
from trading_db.sessions import SessionDatabase
from trading_db.snapshots import SnapshotTransaction
from trading_db.workspace import PreferenceUpdate, WorkspaceDatabase


def signature(engine):
    return {
        "policies": sql(
            engine,
            "SELECT tablename, policyname, roles, cmd, qual, with_check FROM pg_policies "
            "WHERE schemaname='app' ORDER BY tablename,policyname",
        ),
        "roles": sql(
            engine,
            "SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles "
            "WHERE rolname LIKE 'trading_%' ORDER BY rolname",
        ),
        "grants": sql(
            engine,
            "SELECT table_name,grantee,privilege_type FROM information_schema.table_privileges "
            "WHERE table_schema='app' ORDER BY table_name,grantee,privilege_type",
        ),
        "column_grants": sql(
            engine,
            "SELECT table_name,column_name,grantee,privilege_type "
            "FROM information_schema.column_privileges WHERE table_schema='app' "
            "ORDER BY table_name,column_name,grantee,privilege_type",
        ),
        "constraints": sql(
            engine,
            "SELECT c.relname,k.conname,pg_get_constraintdef(k.oid) FROM pg_constraint k "
            "JOIN pg_class c ON c.oid=k.conrelid WHERE c.relnamespace='app'::regnamespace "
            "ORDER BY c.relname,k.conname",
        ),
    }


def add_correction_history(unit, staging, source, reference, position, event_batch, event_records):
    original = event_batch.definition.rows[0]
    revised_values = tuple(
        value.model_copy(update={"source": "-15.00"})
        if value.role == "net_cash"
        else value.model_copy(update={"source": "0.223456789012"})
        if value.role == "quantity"
        else value
        for value in original.values
    )
    cancellation = CandidateDefinition(occurrence=2, kind="cancellation", booking_date="2026-10-24")
    acquisition = CandidateDefinition(
        occurrence=3,
        kind="lot_acquisition",
        instrument_identifier_id=reference.id,
        as_of_date="2026-10-24",
        acquisition_date="2026-09-01",
        values=(
            StagedValue(role="quantity", source="10.000000000001"),
            StagedValue(role="acquisition_cost", source="100.00000000", currency="INR"),
            StagedValue(role="discount_amount", source="10.00000000", currency="INR"),
            StagedValue(
                role="reported_tax_basis",
                source=None,
                currency="INR",
                missing_reason="not_supplied",
            ),
        ),
    )
    remaining = acquisition.model_copy(
        update={
            "occurrence": 4,
            "kind": "lot_remaining",
            "acquisition_date": None,
            "values": (
                StagedValue(role="quantity", source="2.000000000001"),
                StagedValue(role="acquisition_cost", source="20.00", currency="INR"),
                StagedValue(
                    role="discount_amount",
                    source=None,
                    currency="INR",
                    missing_reason="not_supplied",
                ),
                StagedValue(role="reported_tax_basis", source="30.00", currency="INR"),
            ),
        }
    )
    corrected = remaining.model_copy(
        update={
            "occurrence": 5,
            "values": tuple(
                value.model_copy(update={"source": "1.000000000001"})
                if value.role == "quantity"
                else value.model_copy(update={"source": "19.00"})
                if value.role == "acquisition_cost"
                else value.model_copy(
                    update={"source": None, "missing_reason": "incomplete_history"}
                )
                if value.role == "reported_tax_basis"
                else value
                for value in remaining.values
            ),
        }
    )
    observation = staging.observation(
        source.id,
        ObservationDefinition(
            digest="c" * 64,
            coverage="partial_activity",
            period_start="2026-10-24",
            period_end="2026-10-24",
        ),
    )
    batch = staging.stage(
        observation.id,
        BatchDefinition(
            normalizer="synthetic",
            normalizer_version="1",
            rows=(
                original.model_copy(update={"values": revised_values}),
                cancellation,
                acquisition,
                remaining,
                corrected,
                cancellation.model_copy(update={"occurrence": 6}),
                acquisition.model_copy(update={"occurrence": 7}),
                original.model_copy(update={"occurrence": 8}),
            ),
        ),
        expected_revision=0,
    )
    rows = staging.rows(batch.id)
    for row in rows:
        staging.decide(row.id, "include", expected_revision=0)
    events = EventTransaction(unit._unit)
    events.correct(
        event_records[0].id,
        rows[0].id,
        expected_revision=1,
        expected_review_revision=1,
        reason="source_correction",
    )
    events.correct(
        event_records[1].id,
        rows[1].id,
        expected_revision=1,
        expected_review_revision=1,
        reason="cancellation",
    )
    events.correct(
        event_records[1].id,
        rows[7].id,
        expected_revision=2,
        expected_review_revision=1,
        reason="reinstatement",
    )
    lots = LotTransaction(unit._unit)
    bought = lots.record(rows[2].id, position.id, expected_review_revision=1)
    left = lots.record(rows[3].id, position.id, expected_review_revision=1, lot_id=bought.lot_id)
    lots.correct(
        left.id,
        rows[4].id,
        expected_revision=1,
        expected_review_revision=1,
        reason="source_correction",
    )
    lots.correct(
        bought.id,
        rows[5].id,
        expected_revision=1,
        expected_review_revision=1,
        reason="cancellation",
    )
    lots.correct(
        bought.id,
        rows[6].id,
        expected_revision=2,
        expected_review_revision=1,
        reason="reinstatement",
    )


def add_market_history(store, owner):
    with store.transaction(owner) as unit:
        identities = InstrumentTransaction(unit._unit)
        equity = identities.by_isin("ZZ0000000032")
        listing = identities.listings(equity.id)[0]
        direct = identities.by_isin("ZZ0000000016")
        regular = identities.by_isin("ZZ0000000024")
        base = dict(
            namespace="manual_evidence",
            digest="d" * 64,
            normalizer="synthetic",
            normalizer_version=1,
            observed_on="2026-10-24",
            observed_at="2026-10-24T00:30:00.120+05:30",
            source="83.123456789012",
        )
        prices = MarketTransaction(unit._unit)
        quote = MarketDefinition(
            **base,
            occurrence=1,
            kind="quote",
            instrument_id=equity.id,
            listing_id=listing.id,
            currency="USD",
            basis="close",
            adjustment="unadjusted",
        )
        original = prices.record(quote)
        choice = prices.select(original.id, expected_revision=0)
        nav = MarketDefinition(
            **base, occurrence=2, kind="nav", instrument_id=direct.id, currency="INR", basis="nav"
        )
        fund = prices.record(nav)
        nav_choice = prices.select(fund.id, expected_revision=0)
        prices.record(
            nav.model_copy(
                update={
                    "occurrence": 3,
                    "instrument_id": regular.id,
                    "source": None,
                    "missing_reason": "not_supplied",
                }
            )
        )
        fx = prices.record(
            MarketDefinition(
                **base,
                occurrence=4,
                kind="fx",
                base_currency="USD",
                quote_currency="INR",
                basis="reference",
            )
        )
        prices.select(fx.id, expected_revision=0)
        prices.record(
            fx.definition.model_copy(
                update={
                    "occurrence": 5,
                    "base_currency": "INR",
                    "quote_currency": "USD",
                    "source": "0.00",
                }
            )
        )
        prices.record(quote.model_copy(update={"occurrence": 6, "adjustment": "split_adjusted"}))
    with store.transaction(owner) as unit:
        prices = MarketTransaction(unit._unit)
        corrected = prices.record(
            quote.model_copy(
                update={"occurrence": 7, "previous_id": original.id, "source": "84.000000000001"}
            )
        )
        assert prices.resolve(choice.id).state == "stale"
        prices.select(corrected.id, expected_revision=1, reason="correction")
        prices.clear(nav_choice.id, expected_revision=1)


def add_snapshot_history(store, owner):
    with store.transaction(owner) as unit:
        source = unit.source("cas", "FAKE-FOLIO")
        account_id = unit.mapping(source.id).account_id
        securities = InstrumentTransaction(unit._unit)
        reference = securities.identifier(
            IdentifierDefinition(namespace="indmoney_funds", value="FAKE-FUND")
        )
        position = securities.positions(account_id)[0]
        staging = ImportTransaction(unit._unit)
        evidence = staging.observation(
            source.id,
            ObservationDefinition(
                digest="d" * 64,
                coverage="snapshot",
                period_start="2026-10-24",
                period_end="2026-10-25",
            ),
        )
        original = CandidateDefinition(
            occurrence=1,
            kind="position_snapshot",
            instrument_identifier_id=reference.id,
            as_of_date="2026-10-24",
            snapshot_scope="full_account",
            values=(
                StagedValue(role="quantity", source="0.123456789012"),
                StagedValue(role="unit_price", source="76.50000", currency="INR"),
                StagedValue(
                    role="reported_tax_basis",
                    source=None,
                    currency="INR",
                    missing_reason="incomplete_history",
                ),
            ),
        )
        cash = CandidateDefinition(
            occurrence=2,
            kind="cash_snapshot",
            as_of_date="2026-10-24",
            snapshot_scope="native_cash",
            values=(StagedValue(role="net_cash", source="100.00", currency="INR"),),
        )
        changed = original.model_copy(
            update={
                "occurrence": 3,
                "as_of_date": "2026-10-25",
                "as_of_instant": "2026-10-25T00:30:00.120+05:30",
                "snapshot_scope": "selected_position",
                "values": (
                    StagedValue(role="quantity", source="0.223456789012"),
                    *original.values[1:],
                ),
            }
        )
        cancel = CandidateDefinition(occurrence=4, kind="cancellation", booking_date="2026-10-25")
        restore = cash.model_copy(
            update={
                "occurrence": 5,
                "as_of_date": "2026-10-25",
                "values": (StagedValue(role="net_cash", source="125.00", currency="INR"),),
            }
        )
        duplicate = changed.model_copy(
            update={
                "occurrence": 6,
                "as_of_date": "2026-10-24",
                "as_of_instant": "2026-10-24T19:00:00.120Z",
            }
        )
        staged = staging.stage(
            evidence.id,
            BatchDefinition(
                normalizer="synthetic",
                normalizer_version="1",
                rows=(original, cash, changed, cancel, restore, duplicate),
            ),
            expected_revision=0,
        )
        rows = staging.rows(staged.id)
        for row in rows:
            staging.decide(row.id, "include", expected_revision=0)
        snapshots = SnapshotTransaction(unit._unit)
        first = snapshots.record(rows[0].id, expected_review_revision=1, position_id=position.id)
        balance = snapshots.record(rows[1].id, expected_review_revision=1)
        chosen = snapshots.select(first.id, expected_snapshot_revision=1, expected_revision=0)
        cash_choice = snapshots.select(
            balance.id, expected_snapshot_revision=1, expected_revision=0
        )
    with store.transaction(owner) as unit:
        snapshots = SnapshotTransaction(unit._unit)
        snapshots.correct(
            first.id,
            rows[2].id,
            expected_revision=1,
            expected_review_revision=1,
            reason="source_correction",
        )
        snapshots.correct(
            balance.id,
            rows[3].id,
            expected_revision=1,
            expected_review_revision=1,
            reason="cancellation",
        )
        snapshots.correct(
            balance.id,
            rows[4].id,
            expected_revision=2,
            expected_review_revision=1,
            reason="reinstatement",
        )
        snapshots.record(rows[5].id, expected_review_revision=1, position_id=position.id)
        assert (
            snapshots.resolve(chosen.id).state == snapshots.resolve(cash_choice.id).state == "stale"
        )
        snapshots.select(
            first.id, expected_snapshot_revision=2, expected_revision=1, reason="correction"
        )
        snapshots.clear(cash_choice.id, expected_revision=1)
        snapshots.select(
            balance.id, expected_snapshot_revision=3, expected_revision=2, reason="correction"
        )


def test_encrypted_restore_preserves_records_and_isolation_but_not_sessions(environment, database):
    client, service, workspace, _, admin = environment
    source_url, source_project = database
    headers = login(client)
    assert (
        client.put(
            "/api/v1/preferences",
            headers=headers,
            json=dict(theme="dark", display_currency="USD", amount_masked=False, revision=0),
        ).status_code
        == 200
    )
    provision_owner(source_url("bootstrap"), source_project, ISSUER, uuid4())
    own = sql(
        admin,
        "SELECT owner_id FROM app.owner_identities WHERE subject=:subject",
        subject=str(SUBJECT),
    )[0][0]
    other = sql(admin, "SELECT id FROM app.owners WHERE id<>:own", own=own)[0][0]
    with workspace.transaction(other) as unit:
        unit.compare_preferences(
            PreferenceUpdate(theme="light", display_currency="INR", amount_masked=True, revision=0)
        )
    identifier_material = {1: b"a" * 32, 2: b"b" * 32}
    identifier_keys = ReferenceKeys({1: identifier_material[1]}, 1)
    account_store = AccountDatabase(source_url("runtime"), source_project, identifier_keys)
    try:
        for owner in (own, other):
            with account_store.transaction(owner) as unit:
                definition = AccountDefinition(
                    kind="mutual_fund",
                    institution="fund_registrar",
                    market="IN",
                    label="Synthetic folio",
                    currencies=("INR",),
                )
                first, second = unit.create(definition), unit.create(definition)
                source = unit.source("cas", "FAKE-FOLIO")
                unit.map(source.id, first.id, expected_revision=0)
                unit.map(source.id, second.id, expected_revision=1)
                securities = InstrumentTransaction(unit._unit)
                scheme = securities.scheme(SchemeDefinition(name="Synthetic scheme"))
                direct = securities.create(
                    InstrumentDefinition(
                        name="Synthetic Direct",
                        asset_class="mutual_fund",
                        isin="ZZ0000000016",
                        fund_scheme_id=scheme.id,
                        fund_plan="direct",
                        fund_option="growth",
                        fund_currency="INR",
                    )
                )
                regular = securities.create(
                    direct.definition.model_copy(
                        update={
                            "name": "Synthetic Regular",
                            "isin": "ZZ0000000024",
                            "fund_plan": "regular",
                        }
                    )
                )
                reference = securities.identifier(
                    IdentifierDefinition(namespace="indmoney_funds", value="FAKE-FUND")
                )
                securities.map(reference.id, direct.id, expected_revision=0)
                securities.map(reference.id, regular.id, expected_revision=1)
                staging = ImportTransaction(unit._unit)
                evidence = staging.observation(
                    source.id,
                    ObservationDefinition(
                        digest="a" * 64,
                        coverage="snapshot",
                        period_start="2026-10-24",
                        period_end="2026-10-24",
                    ),
                )
                candidate = CandidateDefinition(
                    occurrence=1,
                    kind="position_snapshot",
                    instrument_identifier_id=reference.id,
                    as_of_date="2026-10-24",
                    values=(
                        StagedValue(role="quantity", source="0.123456789012"),
                        StagedValue(role="unit_price", source="76.50000", currency="INR"),
                        StagedValue(
                            role="reported_tax_basis",
                            source=None,
                            currency="INR",
                            missing_reason="incomplete_history",
                        ),
                    ),
                )
                normalized = BatchDefinition(
                    normalizer="synthetic", normalizer_version="1", rows=(candidate,)
                )
                first_batch = staging.stage(evidence.id, normalized, expected_revision=0)
                first_row = staging.rows(first_batch.id)[0]
                staging.decide(first_row.id, "include", expected_revision=0)
                staging.decide(first_row.id, "exclude", expected_revision=1)
                staging.decide(first_row.id, "include", expected_revision=2)
                second_batch = staging.stage(
                    evidence.id,
                    normalized.model_copy(update={"normalizer_version": "2"}),
                    expected_revision=1,
                )
                staging.decide(staging.rows(second_batch.id)[0].id, "include", expected_revision=0)
                revised_evidence = staging.observation(
                    source.id,
                    evidence.definition.model_copy(update={"digest": "b" * 64}),
                    previous_id=evidence.id,
                )
                securities.position(first.id, direct.id, "folio")
                position = securities.position(second.id, regular.id, "folio")
                event_batch = staging.stage(
                    revised_evidence.id,
                    BatchDefinition(
                        normalizer="synthetic",
                        normalizer_version="1",
                        rows=tuple(
                            CandidateDefinition(
                                occurrence=index,
                                kind="subscription",
                                posting_state=state,
                                instrument_identifier_id=reference.id,
                                trade_date="2026-10-24",
                                values=(
                                    StagedValue(role="quantity", source="0.123456789012"),
                                    StagedValue(role="net_cash", source="-12.30", currency="INR"),
                                    StagedValue(
                                        role="fee",
                                        source=None,
                                        currency="INR",
                                        missing_reason="not_supplied",
                                    ),
                                ),
                            )
                            for index, state in enumerate(("posted", "pending", "posted"), 1)
                        ),
                    ),
                    expected_revision=0,
                )
                event_records = []
                for event_row in staging.rows(event_batch.id):
                    staging.decide(event_row.id, "include", expected_revision=0)
                    event_records.append(
                        EventEvidenceTransaction(unit._unit, identifier_keys)
                        .record(
                            event_row.id,
                            expected_review_revision=1,
                            position_id=position.id,
                            provider_reference="FAKE-EVENT-"
                            + ("2" if event_row.definition.occurrence == 2 else "1"),
                        )
                        .event
                    )
                add_correction_history(
                    unit, staging, source, reference, position, event_batch, event_records
                )
                brokerage = unit.create(
                    AccountDefinition(
                        kind="brokerage",
                        institution="indmoney",
                        market="US",
                        label="Synthetic brokerage",
                        currencies=("USD",),
                    )
                )
                equity = securities.create(
                    InstrumentDefinition(
                        name="Synthetic Equity", asset_class="equity", isin="ZZ0000000032"
                    )
                )
                listing = securities.listing(
                    equity.id, ListingDefinition(venue="XNYS", symbol="FAKE", quote_currency="USD")
                )
                reference = securities.identifier(
                    IdentifierDefinition(namespace="indmoney_us", value="FAKE-EQUITY")
                )
                securities.map(reference.id, equity.id, expected_revision=0, listing_id=listing.id)
                securities.position(brokerage.id, equity.id, "custody")
                unit.archive(first.id, expected_revision=1)
            add_snapshot_history(account_store, owner)
            add_market_history(account_store, owner)
    finally:
        account_store.close()
    identifier_keys = ReferenceKeys(identifier_material, 2)
    account_store = AccountDatabase(source_url("runtime"), source_project, identifier_keys)
    try:
        for owner in (own, other):
            with account_store.transaction(owner) as unit:
                assert unit.rotate_references() == 1
                assert (
                    EventEvidenceTransaction(unit._unit, identifier_keys).rotate_references() == 2
                )
    finally:
        account_store.close()
    key = Fernet.generate_key()
    started = time.monotonic()
    with pytest.raises(DatabaseFailure):
        recovery.export_snapshot(source_url("bootstrap"), source_project, key)
    encrypted = recovery.export_snapshot(
        source_url("bootstrap"), source_project, key, identifier_keys=identifier_keys
    )
    data = recovery.decode_snapshot(encrypted, key)
    assert "auth_sessions" not in data and "auth_admissions" not in data
    assert str(own).encode() not in encrypted
    old_started = datetime.now(UTC)
    baseline = signature(admin)
    with disposable() as target:
        migrate.apply(target.url("migrator"), target.project)
        restored_admin = engine_for(target.url("bootstrap"), migration=True)
        target_url = target.url("bootstrap")
        try:
            objects, keys = target.directory / "objects", target.directory / "keys"
            private_directory(objects)
            private_directory(keys)
            (objects / "foundation.fernet").write_bytes(encrypted)
            (keys / "recovery.key").write_bytes(key)
            identifier_directory = target.directory / "identifier-keys"
            private_directory(identifier_directory)
            (identifier_directory / "v2.key").write_bytes(identifier_material[2])
            (identifier_directory / "v2.key").chmod(0o600)
            recovered_identifiers = load_keys(identifier_directory, active=2, versions=(2,))
            del key
            recovered_key = (keys / "recovery.key").read_bytes()
            recovered_object = (objects / "foundation.fernet").read_bytes()
            for missing in (None, ReferenceKeys({2: b"x" * 32}, 2)):
                with pytest.raises(DatabaseFailure):
                    recovery.restore_snapshot(
                        target_url,
                        target.project,
                        recovered_object,
                        recovered_key,
                        identifier_keys=missing,
                    )
                assert sql(restored_admin, "SELECT count(*) FROM app.owners")[0][0] == 0
            for invalid, supplied_key in [
                (recovered_object, Fernet.generate_key()),
                (recovered_object[:-8] + b"tampered", recovered_key),
            ]:
                with pytest.raises(DatabaseFailure):
                    recovery.restore_snapshot(target_url, target.project, invalid, supplied_key)
                assert sql(restored_admin, "SELECT count(*) FROM app.owners")[0][0] == 0
            # Valid encryption, but a late database constraint failure must roll back earlier rows.
            broken = json.loads(Fernet(recovered_key).decrypt(recovered_object))
            broken["rows"]["workspace_preferences"][0]["theme"] = "invalid"
            with pytest.raises(DatabaseFailure, match="rolled back"):
                recovery.restore_snapshot(
                    target_url,
                    target.project,
                    Fernet(recovered_key).encrypt(json.dumps(broken).encode()),
                    recovered_key,
                    identifier_keys=recovered_identifiers,
                )
            assert sql(restored_admin, "SELECT count(*) FROM app.owners")[0][0] == 0
            counts = recovery.restore_snapshot(
                target_url,
                target.project,
                recovered_object,
                recovered_key,
                identifier_keys=recovered_identifiers,
            )
            assert (
                counts["owners"]
                == counts["workspace_preferences"]
                == counts["auth_revocations"]
                == 2
            )
            assert counts["auth_sessions"] == counts["auth_admissions"] == 0
            assert counts["financial_accounts"] == counts["account_currencies"] == 6
            assert counts["source_accounts"] == 2 and counts["source_account_mappings"] == 4
            assert (
                counts["instruments"]
                == counts["account_positions"]
                == counts["instrument_mappings"]
                == 6
            )
            assert counts["fund_schemes"] == counts["instrument_listings"] == 2
            assert counts["instrument_identifiers"] == 4
            assert counts["source_observations"] == 8
            assert counts["import_batches"] == 10 and counts["staged_rows"] == 38
            assert counts["staged_values"] == 96 and counts["review_decisions"] == 42
            assert counts["financial_events"] == 10
            assert counts["cash_movements"] == counts["quantity_movements"] == 8
            assert counts["event_components"] == 24
            assert counts["lots"] == 2 and counts["lot_observations"] == 10
            assert counts["lot_components"] == 32
            assert counts["snapshot_records"] == 12
            assert counts["snapshot_components"] == 22
            assert counts["snapshot_selections"] == 10
            assert counts["market_observations"] == 14
            assert counts["market_selections"] == 10
            assert counts["event_provider_identities"] == 4
            assert counts["event_evidence_links"] == 6
            assert signature(restored_admin) == baseline
            restored_data = recovery.decode_snapshot(
                recovery.export_snapshot(
                    target_url, target.project, recovered_key, identifier_keys=recovered_identifiers
                ),
                recovered_key,
            )
            for table in set(data) - {"auth_revocations"}:
                assert sorted(restored_data[table], key=str) == sorted(data[table], key=str)
            assert all(
                row[0] >= old_started
                for row in sql(restored_admin, "SELECT revoked_before FROM app.auth_revocations")
            )
            with pytest.raises(DatabaseFailure, match="must be empty"):
                recovery.restore_snapshot(
                    target_url,
                    target.project,
                    recovered_object,
                    recovered_key,
                    identifier_keys=recovered_identifiers,
                )
            restored_accounts = AccountDatabase(
                target.url("runtime"), target.project, recovered_identifiers
            )
            try:
                for owner in (own, other):
                    with restored_accounts.transaction(owner) as unit:
                        assert len(unit.list()) == 3
                        source = unit.source("cas", "FAKE-FOLIO")
                        assert source.revision == 2
                        assert [row.revision for row in unit.history(source.id)] == [2, 1]
                        assert unit.get(unit.mapping(source.id).account_id).archived_at is None
                        securities = InstrumentTransaction(unit._unit)
                        assert len(securities.list()) == 3
                        for account in unit.list():
                            assert len(securities.positions(account.id)) == 1
                        record = securities.by_isin("ZZ0000000024")
                        assert record.definition.fund_plan == "regular"
                        reference = securities.identifier(
                            IdentifierDefinition(namespace="indmoney_funds", value="FAKE-FUND")
                        )
                        assert securities.mapping(reference.id).instrument_id == record.id
                        assert [r.revision for r in securities.history(reference.id)] == [2, 1]
                        staging = ImportTransaction(unit._unit)
                        observations = staging.observations(source.id)
                        assert len(observations) == 4
                        original = next(
                            item for item in observations if item.definition.digest == "a" * 64
                        )
                        latest = staging.latest_batch(original.id)
                        assert latest.revision == 2
                        row = staging.rows(latest.id)[0]
                        assert row.status == "superseded"
                        assert {value.role: value.source for value in row.definition.values} == {
                            "quantity": "0.123456789012",
                            "unit_price": "76.50000",
                            "reported_tax_basis": None,
                        }
                        assert staging.history(row.id)[0].action == "include"
                        account_id = unit.mapping(source.id).account_id
                        snapshots = SnapshotTransaction(unit._unit)
                        selections = snapshots.selections(account_id)
                        assert len(selections) == 2 and len(snapshots.list(account_id)) == 3
                        for selection in selections:
                            selected = snapshots.resolve(selection.id)
                            assert selected.state == "selected"
                            record = selected.snapshot
                            assert record.coverage == "snapshot"
                            if selection.position_id is None:
                                assert record.components[0].source == "125.00"
                                assert len(snapshots.history(record.id)) == 3
                                history = snapshots.selection_history(selection.id)
                                assert len(history) == 3 and history[1].reason == "clear"
                            else:
                                assert record.as_of_instant == "2026-10-25T00:30:00.120+05:30"
                                assert record.snapshot_scope == "selected_position"
                                assert len(snapshots.history(record.id)) == 2
                                assert len(snapshots.selection_history(selection.id)) == 2
                                assert (
                                    next(
                                        v.source for v in record.components if v.role == "quantity"
                                    )
                                    == "0.223456789012"
                                )
                        events = EventTransaction(unit._unit)
                        market = MarketTransaction(unit._unit)
                        choices = market.selections()
                        assert len(choices) == 3
                        for choice in choices:
                            result = market.resolve(choice.id)
                            if choice.target.kind == "nav":
                                assert result.state == "unselected" and result.observation is None
                                assert len(market.selection_history(choice.id)) == 2
                            else:
                                assert result.state == "selected"
                                evidence = result.observation.definition
                                assert evidence.observed_at == "2026-10-24T00:30:00.120+05:30"
                                assert evidence.reported().usable
                                if evidence.kind == "quote":
                                    assert evidence.source == "84.000000000001"
                                    assert len(market.selection_history(choice.id)) == 2
                                    assert len(market.list(evidence.target())) == 3
                                else:
                                    assert evidence.base_currency == "USD"
                                    assert evidence.quote_currency == "INR"
                                    assert evidence.source == "83.123456789012"
                        assert sorted(item.revision for item in events.list(account_id)) == [2, 3]
                        links = EventEvidenceTransaction(unit._unit, recovered_identifiers)
                        all_links = [
                            link
                            for event in events.list(account_id)
                            for link in links.list(event.id)
                        ]
                        assert len(all_links) == 3 and sum(link.reused for link in all_links) == 1
                        for link in all_links:
                            assert link.event.revision == 1
                            assert (
                                links.record(
                                    link.source_row_id,
                                    expected_review_revision=1,
                                    position_id=link.event.position_id,
                                    provider_reference="FAKE-EVENT-"
                                    + ("2" if link.event.posting_state == "pending" else "1"),
                                )
                                == link
                            )
                        assert (
                            events.movements(account_id, kind="cash", posting_state="pending") == ()
                        )
                        assert sorted(
                            str(item.amount)
                            for item in events.movements(
                                account_id, kind="cash", posting_state="posted"
                            )
                        ) == ["-12.30", "-15.00"]
                        position = securities.positions(account_id)[0]
                        lots = LotTransaction(unit._unit)
                        lot = lots.list(position.id)[0]
                        current = {item.scope: item for item in lots.observations(lot.id)}
                        assert len(current) == 2
                        assert current["lot_acquisition"].revision == 3
                        assert len(lots.history(current["lot_acquisition"].id)) == 3
                        assert current["lot_remaining"].revision == 2
                        basis = next(
                            v
                            for v in current["lot_remaining"].components
                            if v.role == "reported_tax_basis"
                        )
                        assert basis.source is None and basis.missing_reason == "incomplete_history"
                        previous = lots.history(current["lot_remaining"].id)[1]
                        assert (
                            next(
                                v.source
                                for v in previous.components
                                if v.role == "reported_tax_basis"
                            )
                            == "30.00"
                        )

            finally:
                restored_accounts.close()
            restored_workspace = WorkspaceDatabase(target.url("runtime"), target.project)
            restored_sessions = SessionDatabase(target.url("auth"), target.project)
            try:
                for owner, theme in [(own, "dark"), (other, "light")]:
                    with restored_workspace.transaction(owner) as unit:
                        assert unit.preference_snapshot().theme == theme
                        assert (
                            unit._connection.execute(
                                text(
                                    "SELECT count(*) FROM app.workspace_preferences "
                                    "WHERE owner_id<>:owner"
                                ),
                                {"owner": owner},
                            ).scalar_one()
                            == 0
                        )
                        assert (
                            unit._connection.execute(
                                text(
                                    "UPDATE app.workspace_preferences SET theme='dark' "
                                    "WHERE owner_id<>:owner"
                                ),
                                {"owner": owner},
                            ).rowcount
                            == 0
                        )
                with restored_workspace._engine.begin() as connection:
                    assert (
                        connection.execute(
                            text("SELECT count(*) FROM app.workspace_preferences")
                        ).scalar_one()
                        == 0
                    )
                with restored_workspace._engine.begin() as connection, pytest.raises(DBAPIError):
                    connection.execute(text("SELECT * FROM app.auth_sessions"))
                with restored_sessions._engine.begin() as connection, pytest.raises(DBAPIError):
                    connection.execute(text("SELECT * FROM app.workspace_preferences"))
                with pytest.raises(AuthenticationDenied):
                    restored_sessions.create(
                        verifier(client.cookies["trading_dev_session"]),
                        own,
                        ISSUER,
                        SUBJECT,
                        "login",
                        b"synthetic-encrypted-state",
                        old_started,
                        "a" * 32,
                        "login",
                    )
                restored_auth = BrowserAuth(
                    BrowserProviderStub().provider(), restored_sessions, service.vault
                )
                with TestClient(
                    create_app(browser=restored_auth, workspace=restored_workspace),
                    base_url="http://127.0.0.1:8000",
                ) as recovered_client:
                    recovered_client.cookies.update(client.cookies)
                    assert (
                        recovered_client.get("/api/v1/preferences", headers=headers).status_code
                        == 401
                    )
            finally:
                restored_workspace.close()
                restored_sessions.close()
            report = {
                "scope": "synthetic foundation and account records; separate PostgreSQL clusters",
                "encrypted_bytes": len(encrypted),
                "rows": counts,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "measured_at": datetime.now(UTC).isoformat(),
            }
            destination = ROOT / ".cache/operations"
            private_directory(destination)
            (destination / "recovery-report.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
        finally:
            restored_admin.dispose()
