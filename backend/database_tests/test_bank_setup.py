"""Real owned setup receipts: atomicity, replay, concurrency and database isolation."""

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_ownership import DISABLED, OWNER_A, OWNER_B, UNKNOWN, set_owner
from database_tests.test_preferences import environment as environment
from database_tests.test_preferences import login, sql
from tests.test_bank_setup import command
from trading_api.bank_setup_contracts import BankSetupCommand
from trading_db.accounts import AccountUnavailable
from trading_db.bank_setup import BankSetupTransaction, BankSetupUnavailable
from trading_db.workspace import OwnerAccessDenied

PATH = "/api/v1/finance/bank-account-setup"


def save(store, body, owner=OWNER_A):
    with store.transaction(owner) as unit:
        return BankSetupTransaction(unit._unit).create(BankSetupCommand.model_validate(body))


def test_durable_replay_is_original_declaration_not_current_lifecycle(accounts):
    store, admin = accounts
    body = command()
    first = save(store, body)
    second = save(store, command() | {"expected_revision": 1})
    assert first.account_id != second.account_id  # Identical nicknames are not identities.
    with store.transaction(OWNER_A) as unit:
        unit.archive(UUID(first.account_id), expected_revision=1)
        unit._execute(
            "INSERT INTO app.account_currencies (owner_id,account_id,currency) "
            "VALUES (:owner,:id,'USD')",
            id=UUID(first.account_id),
        )
    assert save(store, body) == first
    store.close()
    assert save(store, body) == first
    with store.transaction(OWNER_A) as unit:
        head = BankSetupTransaction(unit._unit).query()
        assert head.revision == 2 and head.last_saved == second
    assert sql(admin, "SELECT count(*) FROM app.financial_accounts")[0][0] == 2
    assert sql(admin, "SELECT count(*) FROM app.source_accounts")[0][0] == 0
    for changes in [
        {"expected_revision": 1},
        {"label": "Different"},
        {"institution": "sbi"},
        {"currencies": ["INR", "USD"]},
    ]:
        with pytest.raises(BankSetupUnavailable):
            save(store, body | changes)


def test_stale_intent_is_unconsumed_and_ownership_is_independent(accounts):
    store, admin = accounts
    body = command()
    first = save(store, body)
    stale = command()
    with pytest.raises(BankSetupUnavailable):
        save(store, stale)
    assert sql(admin, "SELECT count(*) FROM app.financial_accounts")[0][0] == 1
    assert save(store, stale | {"expected_revision": 1}).revision == 2
    other = save(store, body, OWNER_B)
    assert other.revision == 1 and other.account_id != first.account_id
    for owner in [DISABLED, UNKNOWN]:
        with pytest.raises(OwnerAccessDenied):
            save(store, body, owner)


@pytest.mark.parametrize("same_intent", [False, True])
def test_concurrent_creates_serialize_head_or_replay_without_duplicate_accounts(
    accounts, same_intent
):
    store, admin = accounts
    first = command()
    bodies = [first, first if same_intent else command()]
    ready = Barrier(2)

    def attempt(body):
        ready.wait(timeout=10)
        try:
            return save(store, body)
        except BankSetupUnavailable:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, bodies))
    assert len([value for value in results if value is not None]) == (2 if same_intent else 1)
    if same_intent:
        assert results[0] == results[1]
    assert sql(admin, "SELECT count(*) FROM app.financial_accounts")[0][0] == 1
    assert sql(admin, "SELECT count(*) FROM app.bank_account_setups")[0][0] == 1


def test_receipt_failure_rolls_back_account_and_does_not_bind_intent(accounts, monkeypatch):
    store, admin = accounts
    original = BankSetupTransaction._receipt
    body = command()

    def fail(self, row):
        raise BankSetupUnavailable()

    with monkeypatch.context() as patch:
        patch.setattr(BankSetupTransaction, "_receipt", fail)
        with pytest.raises(BankSetupUnavailable):
            save(store, body)
    for table in ["financial_accounts", "account_currencies", "bank_account_setups"]:
        assert sql(admin, f"SELECT count(*) FROM app.{table}")[0][0] == 0
    assert BankSetupTransaction._receipt == original
    assert save(store, body).revision == 1


def test_receipts_and_accounts_are_bounded_but_committed_replay_survives_caps(accounts):
    store, admin = accounts
    body = command()
    saved = save(store, body)
    # The 999 further historical declarations are synthetic bootstrap fixtures.
    with admin.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO app.financial_accounts (owner_id,id,kind,institution,market,label)
            SELECT :owner, ('20000000-0000-4000-8000-'||lpad(i::text,12,'0'))::uuid,
                'bank','hdfc','IN','Everyday account' FROM generate_series(2,1000) i
        """),
            {"owner": OWNER_A},
        )
        connection.execute(
            text("""
            INSERT INTO app.account_currencies (owner_id,account_id,currency)
            SELECT owner_id,id,'INR' FROM app.financial_accounts
            WHERE owner_id=:owner AND id<>:first
        """),
            {"owner": OWNER_A, "first": UUID(saved.account_id)},
        )
        connection.execute(
            text("""
            INSERT INTO app.bank_account_setups
                (owner_id,id,revision,previous_revision,account_id,institution,label,currency_set)
            SELECT :owner, ('30000000-0000-4000-8000-'||lpad(i::text,12,'0'))::uuid,i,i-1,
                ('20000000-0000-4000-8000-'||lpad(i::text,12,'0'))::uuid,
                'hdfc','Everyday account','INR' FROM generate_series(2,1000) i
        """),
            {"owner": OWNER_A},
        )
    assert save(store, body) == saved
    with pytest.raises(BankSetupUnavailable):
        save(store, command() | {"expected_revision": 1000})
    assert sql(admin, "SELECT count(*) FROM app.financial_accounts")[0][0] == 1000


def test_runtime_receipt_rls_grants_immutability_and_restore_binding(accounts):
    store, admin = accounts
    saved = save(store, command())
    with store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_B)
        assert (
            connection.execute(text("SELECT count(*) FROM app.bank_account_setups")).scalar() == 0
        )
    for engine in [admin, store._workspace._engine]:
        for mutation in [
            "UPDATE app.bank_account_setups SET label='Different'",
            "DELETE FROM app.bank_account_setups",
        ]:
            with pytest.raises(DBAPIError), engine.begin() as connection:
                set_owner(connection, OWNER_A)
                connection.execute(text(mutation))
    assert sql(
        admin,
        "SELECT relforcerowsecurity FROM pg_class WHERE oid='app.bank_account_setups'::regclass",
    )[0][0]
    assert not sql(
        admin, "SELECT has_table_privilege('trading_auth', 'app.bank_account_setups','SELECT')"
    )[0][0]
    # Privileged recovery cannot fabricate a receipt for an incompatible declaration.
    with pytest.raises(DBAPIError), admin.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO app.bank_account_setups
                (owner_id,id,revision,previous_revision,account_id,institution,label,currency_set)
            VALUES (:owner,:id,2,1,:account,'sbi','Different','USD')
        """),
            dict(owner=OWNER_A, id=uuid4(), account=UUID(saved.account_id)),
        )
    assert save(store, command() | {"expected_revision": 1}).revision == 2


def test_http_setup_refreshes_directory_and_uses_the_existing_security_boundary(environment):
    client, _, _, _, admin = environment
    body = command()
    assert client.post(PATH + "/create", json=body).status_code in (401, 403)
    headers = login(client)
    for changes, expected in [
        ({"Origin": "https://other.invalid"}, 403),
        ({"X-CSRFToken": "wrong"}, 403),
        ({"X-Workspace-Context": "wrong"}, 412),
    ]:
        response = client.post(PATH + "/create", headers=headers | changes, json=body)
        assert response.status_code == expected
    assert sql(admin, "SELECT count(*) FROM app.bank_account_setups")[0][0] == 0
    result = client.post(PATH + "/create", headers=headers, json=body)
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    saved = result.json()
    assert client.post(PATH + "/create", headers=headers, json=body).json() == saved
    head = client.post(PATH + "/query", headers=headers, json={})
    assert head.json() == {"revision": 1, "last_saved": saved}
    directory = client.post("/api/v1/finance/accounts/query", headers=headers, json={}).json()
    assert [item["id"] for item in directory["items"]] == [saved["account_id"]]
    for extra in [{"owner_id": str(uuid4())}, {"account_number": "1234"}, {"balance": "0"}]:
        assert client.post(PATH + "/create", headers=headers, json=body | extra).status_code == 422
    assert (
        client.post(PATH + "/query", headers=headers, json={"owner_id": str(uuid4())}).status_code
        == 422
    )


@pytest.mark.parametrize("failure", ["expired", "disabled"])
def test_final_session_or_owner_failure_rolls_back_all_creation_effects(
    environment, monkeypatch, failure
):
    client, _, _, _, admin = environment
    headers = login(client)
    original = BankSetupTransaction.create

    def interrupted(self, body):
        result = original(self, body)
        sql(
            admin,
            "UPDATE app.owners SET is_active=false"
            if failure == "disabled"
            else "UPDATE app.auth_sessions SET idle_until=clock_timestamp()-interval '1 second'",
        )
        return result

    monkeypatch.setattr(BankSetupTransaction, "create", interrupted)
    assert client.post(PATH + "/create", headers=headers, json=command()).status_code == 401
    for table in ["financial_accounts", "account_currencies", "bank_account_setups"]:
        assert sql(admin, f"SELECT count(*) FROM app.{table}")[0][0] == 0


def test_mfa_is_required_before_setup_mutation(environment):
    client, _, _, _, admin = environment
    headers = login(client, mfa=False)
    assert client.post(PATH + "/create", headers=headers, json=command()).status_code in (401, 403)
    assert sql(admin, "SELECT count(*) FROM app.financial_accounts")[0][0] == 0


def test_active_owner_is_rechecked_after_waiting_for_the_account_lock(accounts):
    store, admin = accounts
    lock = int.from_bytes(
        hashlib.sha256(b"accounts/v1" + OWNER_A.bytes).digest()[:8], "big", signed=True
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        with admin.begin() as holding:
            holding.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
            future = executor.submit(save, store, command())
            deadline = time.monotonic() + 10
            while not sql(
                admin, "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted"
            )[0][0]:
                assert time.monotonic() < deadline
                time.sleep(0.02)
            sql(admin, "UPDATE app.owners SET is_active=false WHERE id=:id", id=OWNER_A)
        with pytest.raises(OwnerAccessDenied):
            future.result(timeout=10)
    assert sql(admin, "SELECT count(*) FROM app.bank_account_setups")[0][0] == 0
    assert sql(admin, "SELECT count(*) FROM app.financial_accounts")[0][0] == 0


def test_existing_account_quota_applies_even_when_setup_head_is_below_cap(accounts):
    store, admin = accounts
    body = command()
    first = save(store, body)
    sql(
        admin,
        """
        WITH seeded AS (
            INSERT INTO app.financial_accounts (owner_id,id,kind,institution,market,label)
            SELECT :owner, ('40000000-0000-4000-8000-'||lpad(i::text,12,'0'))::uuid,
                'bank','hdfc','IN','Existing account' FROM generate_series(2,1000) i
            RETURNING owner_id,id
        ) INSERT INTO app.account_currencies (owner_id,account_id,currency)
            SELECT owner_id,id,'INR' FROM seeded
    """,
        owner=OWNER_A,
    )
    assert save(store, body) == first
    with pytest.raises(AccountUnavailable):
        save(store, command() | {"expected_revision": 1})
    assert sql(admin, "SELECT count(*) FROM app.bank_account_setups")[0][0] == 1
    assert sql(admin, "SELECT count(*) FROM app.financial_accounts")[0][0] == 1000


def test_query_uses_read_only_transaction_and_bad_projection_keeps_session(
    environment, monkeypatch
):
    client, _, _, _, admin = environment
    headers = login(client)
    body = command()
    assert client.post(PATH + "/create", headers=headers, json=body).status_code == 200
    modes = []
    original = BankSetupTransaction.query

    def observed(self):
        modes.append(
            self._accounts._execute("SELECT current_setting('transaction_read_only')").scalar_one()
        )
        return original(self)

    monkeypatch.setattr(BankSetupTransaction, "query", observed)
    assert client.post(PATH + "/query", headers=headers, json={}).status_code == 200
    assert modes == ["on"]
    from trading_api.bank_setup_contracts import BankSetupHead

    broken = BankSetupHead.model_construct(revision=1, last_saved=None)
    monkeypatch.setattr(BankSetupTransaction, "query", lambda self: broken)
    failed = client.post(PATH + "/query", headers=headers, json={})
    assert failed.status_code == 409 and "set-cookie" not in failed.headers
    assert client.get("/api/v1/auth/session", headers=headers).status_code == 200
    assert sql(admin, "SELECT count(*) FROM app.bank_account_setups")[0][0] == 1


def test_runtime_cannot_create_a_receipt_for_another_owner(accounts):
    store, admin = accounts
    saved = save(store, command(), OWNER_A)
    for row_owner in [OWNER_A, OWNER_B]:
        with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
            set_owner(connection, OWNER_B)
            connection.execute(
                text("""
                INSERT INTO app.bank_account_setups
                    (owner_id,id,revision,previous_revision,account_id,institution,label,currency_set)
                VALUES (:owner,:id,1,NULL,:account,'hdfc','Everyday account','INR')
            """),
                dict(owner=row_owner, id=uuid4(), account=UUID(saved.account_id)),
            )
    assert sql(admin, "SELECT count(*) FROM app.bank_account_setups")[0][0] == 1
