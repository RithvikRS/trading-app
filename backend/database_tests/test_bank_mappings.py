"""Existing bank sources: bounded history, transition replay and authorization at commit."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from queue import Queue
from threading import Barrier, Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_accounts import definition
from database_tests.test_events import seed as seed_events
from database_tests.test_ownership import DISABLED, OWNER_A, OWNER_B, UNKNOWN, set_owner
from database_tests.test_preferences import environment as environment
from database_tests.test_preferences import login, sql
from trading_api.bank_mapping_contracts import (
    MAX_MAPPING_REVISION,
    BankMappingChange,
    BankMappingHistoryQuery,
)
from trading_auth.session_models import verifier
from trading_db.account_keys import ReferenceKeys
from trading_db.accounts import AccountDatabase, AccountUnavailable
from trading_db.bank_mappings import BankMappingTransaction, BankMappingUnavailable
from trading_db.events import EventTransaction
from trading_db.workspace import OwnerAccessDenied

PATH = "/api/v1/finance/bank-source-mappings"


def command(source, account, expected=0):
    return BankMappingChange(
        source_id=str(source.id),
        expected_revision=expected,
        account_id=str(account.id) if account is not None else None,
    )


def seed_mapping(store, owner=OWNER_A, institution="hdfc", currencies=("INR",)):
    with store.transaction(owner) as unit:
        first = unit.create(definition(institution=institution, currencies=currencies))
        second = unit.create(definition(institution=institution, currencies=currencies))
        source = unit.source(institution + "_statement", "SYNTHETIC-BANK-MAPPING")
    return first, second, source


def save(store, request, owner=OWNER_A):
    with store.transaction(owner) as unit:
        return BankMappingTransaction(unit._unit).change(request)


def history(store, source, owner=OWNER_A, **parameters):
    with store._workspace.transaction(owner, read_only=True) as unit:
        return BankMappingTransaction(unit).history(
            BankMappingHistoryQuery(source_id=str(source.id), **parameters)
        )


def mapping_count(admin):
    return sql(admin, "SELECT count(*) FROM app.source_account_mappings")[0][0]


def await_lock(admin, future, pid, blocker, kind):
    """Poll an exact blocked backend and blocker, within the production lock timeout."""
    deadline = monotonic() + 3
    while monotonic() < deadline:
        waiting = sql(
            admin,
            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid "
            "AND locktype=:kind AND NOT granted) "
            "AND :blocker=ANY(pg_blocking_pids(:pid))",
            pid=pid,
            kind=kind,
            blocker=blocker,
        )[0][0]
        if waiting:
            return
        assert not future.done(), "Operation ended before the expected observed lock wait"
        sleep(0.01)
    pytest.fail("Operation did not reach the expected observed lock wait")


@pytest.fixture
def http_mapping(environment, database):
    client, browser, workspace, _, admin = environment
    url, project = database
    owner = sql(admin, "SELECT id FROM app.owners")[0][0]
    store = AccountDatabase(url("runtime"), project, ReferenceKeys({1: b"a" * 32}, 1))
    try:
        first, second, source = seed_mapping(store, owner)
        yield client, browser, workspace, admin, store, owner, first, second, source
    finally:
        store.close()


@pytest.mark.parametrize("institution", ["hdfc", "sbi"])
@pytest.mark.parametrize("currencies", [("INR",), ("USD",), ("USD", "INR")])
def test_initial_correction_unlink_relink_preserve_native_declarations(
    accounts, institution, currencies
):
    store, admin = accounts
    first, second, source = seed_mapping(store, institution=institution, currencies=currencies)
    empty = history(store, source)
    assert empty.head_revision == 0 and empty.head is None
    assert empty.items == () and empty.next_before is None
    saved = [
        save(store, command(source, first)),
        save(store, command(source, second, 1)),
        save(store, command(source, None, 2)),
        save(store, command(source, first, 3)),
    ]
    assert [row.reason for row in saved] == ["initial", "correction", "unlinked", "correction"]
    assert [row.previous_revision for row in saved] == [None, 1, 2, 3]
    assert {row.namespace for row in saved} == {institution + "_statement"}
    assert history(store, source).items == tuple(reversed(saved))
    with store.transaction(OWNER_A) as unit:
        assert unit.get(first.id).definition.currencies == tuple(sorted(currencies))
        assert unit.get(second.id).definition.currencies == tuple(sorted(currencies))
    assert sql(admin, "SELECT count(*) FROM app.financial_events")[0][0] == 0


def test_replay_retains_original_predecessor_after_corrections_unlink_and_archive(accounts):
    store, admin = accounts
    first, second, source = seed_mapping(store)
    original = command(source, first)
    initial = save(store, original)
    correction = save(store, command(source, second, 1))
    unlink = save(store, command(source, None, 2))
    with store.transaction(OWNER_A) as unit:
        unit.archive(first.id, expected_revision=1)
        unit.archive(second.id, expected_revision=1)
    store.close()
    assert save(store, original) == initial
    assert save(store, command(source, second, 1)) == correction
    assert save(store, command(source, None, 2)) == unlink
    assert history(store, source).head == unlink
    for request in [
        command(source, second),  # Different target cannot impersonate revision one.
        command(source, first, 1),  # A no-op cannot impersonate the later correction.
        command(source, first, 2),
        command(source, None, 3),
        command(source, first, 3),  # New admission still requires an active target.
    ]:
        with pytest.raises(BankMappingUnavailable):
            save(store, request)
    assert mapping_count(admin) == 3


def test_matching_latest_target_does_not_fast_forward_a_different_original_predecessor(accounts):
    store, admin = accounts
    first, second, source = seed_mapping(store)
    save(store, command(source, first))
    save(store, command(source, second, 1))
    save(store, command(source, first, 2))
    for request in [command(source, first, 1), command(source, first, 3)]:
        with pytest.raises(BankMappingUnavailable):
            save(store, request)
    assert mapping_count(admin) == 3


def test_noop_and_constructed_initial_unlink_never_consume_a_revision(accounts):
    store, admin = accounts
    first, _, source = seed_mapping(store)
    invalid = BankMappingChange.model_construct(
        source_id=str(source.id), expected_revision=0, account_id=None
    )
    with pytest.raises(BankMappingUnavailable):
        save(store, invalid)
    save(store, command(source, first))
    with pytest.raises(BankMappingUnavailable):
        save(store, command(source, first, 1))
    assert save(store, command(source, None, 1)).revision == 2
    with pytest.raises(BankMappingUnavailable):
        save(store, command(source, None, 2))
    assert mapping_count(admin) == 2


def test_history_is_exact_bounded_and_accepts_inclusive_terminal_cursor(accounts):
    store, _ = accounts
    first, second, source = seed_mapping(store)
    saved = [
        save(store, command(source, first)),
        save(store, command(source, second, 1)),
        save(store, command(source, None, 2)),
    ]
    newest = history(store, source, limit=1)
    assert newest.head == saved[2] and newest.items == (saved[2],) and newest.next_before == 3
    middle = history(store, source, limit=1, before=newest.next_before)
    assert middle.head == saved[2] and middle.items == (saved[1],) and middle.next_before == 2
    oldest = history(store, source, limit=1, before=middle.next_before)
    assert oldest.head == saved[2] and oldest.items == (saved[0],) and oldest.next_before is None
    below = history(store, source, before=1)
    assert below.head == saved[2] and below.items == () and below.next_before is None
    assert history(store, source, before=MAX_MAPPING_REVISION).items == tuple(reversed(saved))


def test_scope_denials_are_private_and_never_treat_missing_sources_as_empty(accounts):
    store, admin = accounts
    first, _, source = seed_mapping(store)
    other, _, foreign = seed_mapping(store, OWNER_B)
    with store.transaction(OWNER_A) as unit:
        wrong = unit.source("indmoney_india", "SYNTHETIC-WRONG-FAMILY")
        wrong_bank = unit.create(definition(institution="sbi"))
        wrong_kind = unit.create(definition("brokerage", "indmoney"))
    source_ids = [foreign.id, wrong.id, uuid4()]
    for source_id in source_ids:
        with store.transaction(OWNER_A) as unit:
            service = BankMappingTransaction(unit._unit)
            with pytest.raises(BankMappingUnavailable):
                service.history(BankMappingHistoryQuery(source_id=str(source_id)))
            with pytest.raises(BankMappingUnavailable):
                service.change(
                    command(source, first).model_copy(update={"source_id": str(source_id)})
                )
    for account_id in [other.id, wrong_bank.id, wrong_kind.id, uuid4()]:
        with pytest.raises(BankMappingUnavailable) as failure:
            save(store, command(source, first).model_copy(update={"account_id": str(account_id)}))
        assert str(account_id) not in str(failure.value)
    for owner in [DISABLED, UNKNOWN]:
        with pytest.raises(OwnerAccessDenied):
            save(store, command(source, first), owner)
    assert mapping_count(admin) == 0


@pytest.mark.parametrize("same_target", [True, False])
def test_concurrent_commands_converge_only_for_the_same_state_transition(accounts, same_target):
    store, admin = accounts
    first, second, source = seed_mapping(store)
    ready = Barrier(2)

    def attempt(target):
        ready.wait(timeout=5)
        try:
            return save(store, command(source, target))
        except BankMappingUnavailable:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [first, first if same_target else second]))
    winners = [result for result in results if result is not None]
    assert len(winners) == (2 if same_target else 1)
    if same_target:
        assert results[0] == results[1]
    assert mapping_count(admin) == 1
    assert history(store, source).head == winners[0]


def test_committed_transition_replay_precedes_owner_mapping_quota(accounts):
    store, admin = accounts
    first, second, source = seed_mapping(store)
    original = save(store, command(source, first))
    sql(
        admin,
        "INSERT INTO app.source_account_mappings "
        "(owner_id,source_id,revision,previous_revision,account_id,reason) "
        "SELECT :owner,:source,n,n-1,CASE WHEN n%2=0 THEN CAST(:second AS uuid) "
        "ELSE CAST(:first AS uuid) END,'correction' FROM generate_series(2,1000) n",
        owner=OWNER_A,
        source=source.id,
        first=first.id,
        second=second.id,
    )
    assert mapping_count(admin) == 1000
    with store.transaction(OWNER_A) as unit:
        unit.archive(first.id, expected_revision=1)
    assert save(store, command(source, first)) == original
    # An active third target reaches the quota check rather than failing target admission.
    with store.transaction(OWNER_A) as unit:
        third = unit.create(definition())
    with pytest.raises(AccountUnavailable):
        save(store, command(source, third, 1000))
    assert mapping_count(admin) == 1000
    assert history(store, source, limit=1).head_revision == 1000


def test_runtime_rls_grants_and_correction_do_not_rewrite_saved_financial_attribution(accounts):
    store, admin = accounts
    first, source, _, rows = seed_events(store, kind="cash_movement")
    with store.transaction(OWNER_A) as unit:
        saved = EventTransaction(unit._unit).record(rows[0].id, expected_review_revision=1)
        second = unit.create(definition())
    original_mapping = history(store, source).head
    save(store, command(source, second, 1))
    save(store, command(source, None, 2))
    with store.transaction(OWNER_A) as unit:
        assert EventTransaction(unit._unit).get(saved.id) == saved
        assert EventTransaction(unit._unit).movements(first.id, kind="cash", posting_state="posted")
        assert (
            EventTransaction(unit._unit).movements(second.id, kind="cash", posting_state="posted")
            == ()
        )
    assert history(store, source).items[-1] == original_mapping
    for mutation in [
        "UPDATE app.source_account_mappings SET account_id=NULL",
        "DELETE FROM app.source_account_mappings",
    ]:
        with pytest.raises(DBAPIError), store._workspace._engine.begin() as connection:
            set_owner(connection, OWNER_A)
            connection.execute(text(mutation))
    with store._workspace._engine.begin() as connection:
        set_owner(connection, OWNER_B)
        assert (
            connection.execute(text("SELECT count(*) FROM app.source_account_mappings")).scalar()
            == 0
        )
    assert sql(
        admin,
        "SELECT relforcerowsecurity FROM pg_class "
        "WHERE oid='app.source_account_mappings'::regclass",
    )[0][0]
    assert not sql(
        admin,
        "SELECT has_table_privilege('trading_auth','app.source_account_mappings','SELECT')",
    )[0][0]


@pytest.mark.parametrize("disable", [False, True])
def test_non_key_archive_wait_requires_fresh_target_and_owner_checks(accounts, disable):
    store, admin = accounts
    first, _, source = seed_mapping(store)
    pending = Queue()

    def mapping():
        with store.transaction(OWNER_A) as unit:
            pending.put(unit._execute("SELECT pg_backend_pid()").scalar_one())
            return BankMappingTransaction(unit._unit).change(command(source, first))

    with ThreadPoolExecutor(max_workers=1) as pool:
        with admin.begin() as holder:
            blocker = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()
            holder.execute(
                text(
                    "UPDATE app.financial_accounts SET archived_at=statement_timestamp() "
                    "WHERE owner_id=:owner AND id=:id"
                ),
                dict(owner=OWNER_A, id=first.id),
            )
            future = pool.submit(mapping)
            await_lock(admin, future, pending.get(timeout=5), blocker, "transactionid")
            if disable:
                holder.execute(
                    text("UPDATE app.owners SET is_active=false WHERE id=:id"), dict(id=OWNER_A)
                )
        with pytest.raises(OwnerAccessDenied if disable else BankMappingUnavailable):
            future.result(timeout=10)
    assert mapping_count(admin) == 0


def test_mapping_share_lock_blocks_non_key_archive_until_outer_transaction_commits(accounts):
    store, admin = accounts
    first, _, source = seed_mapping(store)
    pending = Queue()

    def archive():
        # This is exactly the granted non-key lifecycle UPDATE; deliberately bypass the
        # cooperative advisory lock so the row-lock guarantee is independently exercised.
        with store._workspace._engine.begin() as connection:
            set_owner(connection, OWNER_A)
            pending.put(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
            connection.execute(
                text(
                    "UPDATE app.financial_accounts SET archived_at=statement_timestamp() "
                    "WHERE owner_id=:owner AND id=:id AND archived_at IS NULL"
                ),
                dict(owner=OWNER_A, id=first.id),
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.transaction(OWNER_A) as unit:
            blocker = unit._execute("SELECT pg_backend_pid()").scalar_one()
            saved = BankMappingTransaction(unit._unit).change(command(source, first))
            future = pool.submit(archive)
            await_lock(admin, future, pending.get(timeout=5), blocker, "transactionid")
            assert mapping_count(admin) == 0  # The returned transition has not committed yet.
        future.result(timeout=10)
    assert mapping_count(admin) == 1
    assert save(store, command(source, first)) == saved
    with store.transaction(OWNER_A) as unit:
        assert unit.get(first.id).archived_at is not None


def test_owner_is_rechecked_after_waiting_for_owner_advisory_lock(accounts):
    store, admin = accounts
    first, _, source = seed_mapping(store)
    pending = Queue()
    key = int.from_bytes(
        hashlib.sha256(b"accounts/v1" + OWNER_A.bytes).digest()[:8], "big", signed=True
    )

    def mapping():
        with store.transaction(OWNER_A) as unit:
            pending.put(unit._execute("SELECT pg_backend_pid()").scalar_one())
            return BankMappingTransaction(unit._unit).change(command(source, first))

    with ThreadPoolExecutor(max_workers=1) as pool:
        with admin.begin() as holder:
            blocker = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()
            holder.execute(text("SELECT pg_advisory_xact_lock(:key)"), dict(key=key))
            future = pool.submit(mapping)
            await_lock(admin, future, pending.get(timeout=5), blocker, "advisory")
            holder.execute(
                text("UPDATE app.owners SET is_active=false WHERE id=:id"), dict(id=OWNER_A)
            )
        with pytest.raises(OwnerAccessDenied):
            future.result(timeout=10)
    assert mapping_count(admin) == 0


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_new_mapping_service_rejects_stale_snapshot_isolation(accounts, isolation):
    store, admin = accounts
    first, _, source = seed_mapping(store)
    from trading_db.workspace import WorkspaceTransaction

    with store._workspace._engine.connect().execution_options(
        isolation_level=isolation
    ) as connection:
        with connection.begin():
            set_owner(connection, OWNER_A)
            unit = WorkspaceTransaction(connection, OWNER_A)
            with pytest.raises(BankMappingUnavailable):
                BankMappingTransaction(unit).change(command(source, first))
    assert mapping_count(admin) == 0


def test_http_round_trip_keeps_source_identity_private_and_history_read_only(
    http_mapping, monkeypatch
):
    client, _, _, admin, _, _, first, _, source = http_mapping
    headers = login(client)
    body = command(source, first).model_dump(mode="json")
    saved = client.post(PATH + "/change", headers=headers, json=body)
    assert saved.status_code == 200 and saved.headers["cache-control"] == "no-store"
    assert saved.json()["revision"] == 1 and saved.json()["previous_revision"] is None
    assert client.post(PATH + "/change", headers=headers, json=body).json() == saved.json()
    modes = []
    original = BankMappingTransaction.history

    def observed(self, query):
        modes.append(self._accounts._execute("SHOW transaction_read_only").scalar_one())
        return original(self, query)

    monkeypatch.setattr(BankMappingTransaction, "history", observed)
    response = client.post(PATH + "/history", headers=headers, json={"source_id": str(source.id)})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["head"] == saved.json()
    assert response.json()["items"] == [saved.json()] and modes == ["on"]
    for private in ["encrypted_reference", "fingerprint", "SYNTHETIC-BANK-MAPPING", "owner_id"]:
        assert private not in response.text and private not in saved.text
    for extra in [
        {"owner_id": str(uuid4())},
        {"namespace": "sbi_statement"},
        {"reference": "FAKE"},
    ]:
        assert client.post(PATH + "/change", headers=headers, json=body | extra).status_code == 422
    assert mapping_count(admin) == 1


@pytest.mark.parametrize("endpoint", ["history", "change"])
def test_http_uses_mfa_origin_csrf_and_exact_workspace_context(http_mapping, endpoint):
    client, _, _, admin, _, _, first, _, source = http_mapping
    body = (
        command(source, first).model_dump(mode="json")
        if endpoint == "change"
        else {"source_id": str(source.id)}
    )
    assert client.post(PATH + "/" + endpoint, json=body).status_code in (401, 403)
    headers = login(client)
    for change, status in [
        ({"Origin": "https://other.invalid"}, 403),
        ({"X-CSRFToken": "wrong"}, 403),
        ({"X-Workspace-Context": "wrong"}, 412),
        ({"Authorization": "Bearer synthetic"}, 403),
    ]:
        response = client.post(PATH + "/" + endpoint, headers=headers | change, json=body)
        assert response.status_code == status
    assert mapping_count(admin) == 0


@pytest.mark.parametrize("endpoint", ["history", "change"])
def test_http_pending_mfa_cannot_read_or_change_mapping(http_mapping, endpoint):
    client, _, _, admin, _, _, first, _, source = http_mapping
    headers = login(client, mfa=False)
    body = (
        command(source, first).model_dump(mode="json")
        if endpoint == "change"
        else {"source_id": str(source.id)}
    )
    assert client.post(PATH + "/" + endpoint, headers=headers, json=body).status_code in (401, 403)
    assert mapping_count(admin) == 0


def test_http_foreign_missing_and_wrong_family_sources_share_private_conflict(http_mapping):
    client, _, _, admin, store, owner, first, _, source = http_mapping
    with store.transaction(owner) as unit:
        wrong = unit.source("indmoney_india", "SYNTHETIC-OTHER")
    sql(admin, "INSERT INTO app.owners(id,is_active) VALUES (:id,true)", id=OWNER_B)
    _, _, foreign = seed_mapping(store, OWNER_B)
    headers = login(client)
    for source_id in [uuid4(), wrong.id, foreign.id]:
        for endpoint, body in [
            ("history", {"source_id": str(source_id)}),
            (
                "change",
                command(source, first).model_dump(mode="json") | {"source_id": str(source_id)},
            ),
        ]:
            response = client.post(PATH + "/" + endpoint, headers=headers, json=body)
            assert response.status_code == 409
            assert set(response.json()) == {"error", "request_id"}
            assert response.json()["error"] == "bank_mapping_conflict"
            assert str(source_id) not in response.text and "set-cookie" not in response.headers
    assert client.get("/api/v1/auth/session", headers=headers).status_code == 200
    assert mapping_count(admin) == 0


@pytest.mark.parametrize("failure", ["disabled", "expired"])
def test_final_authorization_failure_rolls_back_mapping_and_retains_predecessor(
    http_mapping, monkeypatch, failure
):
    client, _, _, admin, store, owner, first, second, source = http_mapping
    original_saved = save(store, command(source, first), owner)
    headers = login(client)
    original = BankMappingTransaction.change

    def interrupted(self, body):
        saved = original(self, body)
        sql(
            admin,
            "UPDATE app.owners SET is_active=false"
            if failure == "disabled"
            else "UPDATE app.auth_sessions SET idle_until=clock_timestamp()-interval '1 second'",
        )
        return saved

    monkeypatch.setattr(BankMappingTransaction, "change", interrupted)
    response = client.post(
        PATH + "/change", headers=headers, json=command(source, second, 1).model_dump(mode="json")
    )
    assert response.status_code == 401 and mapping_count(admin) == 1
    row = sql(admin, "SELECT revision,account_id FROM app.source_account_mappings")[0]
    assert row[0] == original_saved.revision and str(row[1]) == original_saved.account_id


@pytest.mark.parametrize("malformation", ["invalid_predecessor", "wrong_model", "unexpected_field"])
def test_malformed_response_rolls_back_before_commit_and_does_not_revoke_session(
    http_mapping, monkeypatch, malformation
):
    client, _, _, admin, _, _, first, _, source = http_mapping
    headers = login(client)
    original = BankMappingTransaction.change

    def malformed(self, body):
        saved = original(self, body)
        if malformation == "wrong_model":
            return body
        if malformation == "unexpected_field":
            return saved.model_copy(update={"private_diagnostic": "synthetic-private"})
        return saved.model_copy(update={"previous_revision": 0})

    monkeypatch.setattr(BankMappingTransaction, "change", malformed)
    response = client.post(
        PATH + "/change", headers=headers, json=command(source, first).model_dump(mode="json")
    )
    assert response.status_code == 409 and mapping_count(admin) == 0
    assert response.json()["error"] == "bank_mapping_conflict"
    assert "synthetic-private" not in response.text and "set-cookie" not in response.headers
    assert client.get("/api/v1/auth/session", headers=headers).status_code == 200


@pytest.mark.parametrize("archive", [False, True])
@pytest.mark.parametrize("failure", ["expired", "disabled"])
def test_authorization_changes_during_observed_target_wait_cannot_commit(
    http_mapping, monkeypatch, archive, failure
):
    client, _, _, admin, _, owner, first, _, source = http_mapping
    headers = login(client)
    pending = Queue()
    original = BankMappingTransaction._admit_target

    def observed(self, scope, account_id):
        pending.put(self._accounts._execute("SELECT pg_backend_pid()").scalar_one())
        return original(self, scope, account_id)

    monkeypatch.setattr(BankMappingTransaction, "_admit_target", observed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with admin.begin() as holder:
            blocker = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()
            holder.execute(
                text(
                    "UPDATE app.financial_accounts SET archived_at=statement_timestamp() "
                    "WHERE owner_id=:owner AND id=:id"
                    if archive
                    else "SELECT id FROM app.financial_accounts WHERE owner_id=:owner AND id=:id "
                    "FOR NO KEY UPDATE"
                ),
                dict(owner=owner, id=first.id),
            )
            future = pool.submit(
                client.post,
                PATH + "/change",
                headers=headers,
                json=command(source, first).model_dump(mode="json"),
            )
            await_lock(admin, future, pending.get(timeout=5), blocker, "transactionid")
            holder.execute(
                text(
                    "UPDATE app.owners SET is_active=false WHERE id=:owner"
                    if failure == "disabled"
                    else "UPDATE app.auth_sessions SET idle_until=clock_timestamp() "
                    "-interval '1 second'"
                ),
                dict(owner=owner),
            )
        response = future.result(timeout=10)
    # A target rejected on the no-row path has no commit to authorize; session expiry
    # is then observable on the next session check. Fresh owner denial is checked there.
    assert response.status_code == (409 if archive and failure == "expired" else 401)
    assert mapping_count(admin) == 0
    assert client.get("/api/v1/auth/session", headers=headers).status_code == 401


def test_revocation_before_registry_admission_prevents_mapping(http_mapping, monkeypatch):
    client, browser, _, admin, _, _, first, _, source = http_mapping
    headers = login(client)
    original = browser.store.workspace_guard

    @contextmanager
    def revoked(key, owner):
        browser.store.revoke(key, "a" * 32, all_sessions=True)
        with original(key, owner) as validate:
            yield validate

    monkeypatch.setattr(browser.store, "workspace_guard", revoked)
    response = client.post(
        PATH + "/change", headers=headers, json=command(source, first).model_dump(mode="json")
    )
    assert response.status_code == 401 and mapping_count(admin) == 0


def test_registry_revocation_waits_for_admitted_mapping_commit(http_mapping, monkeypatch):
    client, browser, _, admin, _, _, first, _, source = http_mapping
    headers = login(client)
    key = verifier(client.cookies["trading_dev_session"])
    entered, release = Event(), Event()
    original = BankMappingTransaction.change

    def paused(self, body):
        result = original(self, body)
        entered.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(BankMappingTransaction, "change", paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        saving = pool.submit(
            client.post,
            PATH + "/change",
            headers=headers,
            json=command(source, first).model_dump(mode="json"),
        )
        try:
            assert entered.wait(5)
            revoking = pool.submit(browser.store.revoke, key, "a" * 32)
            deadline = monotonic() + 3
            while monotonic() < deadline:
                rows = sql(
                    admin,
                    "SELECT waiter.pid, holder.pid FROM pg_locks waiter "
                    "JOIN pg_locks holder USING (locktype,database,classid,objid,objsubid) "
                    "WHERE waiter.locktype='advisory' AND NOT waiter.granted "
                    "AND holder.granted AND waiter.objid=714039232 "
                    "AND holder.pid=ANY(pg_blocking_pids(waiter.pid))",
                )
                if rows:
                    break
                assert not revoking.done(), "Revocation escaped the admitted registry guard"
                sleep(0.01)
            else:
                pytest.fail("Revocation did not reach the held registry lock")
            assert mapping_count(admin) == 0
        finally:
            release.set()
        assert saving.result(timeout=10).status_code == 200
        revoking.result(timeout=10)
    assert mapping_count(admin) == 1
    assert client.get("/api/v1/auth/session", headers=headers).status_code == 401
