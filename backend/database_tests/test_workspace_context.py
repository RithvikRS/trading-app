"""A stale tab cannot follow a replaced cookie into another workspace operation."""

from uuid import uuid4

import httpx2 as httpx
import pytest
from sqlalchemy import event

from database_tests.test_accounts import definition
from database_tests.test_preferences import DEFAULT, UPDATE, login, sql
from database_tests.test_preferences import environment as environment
from tests.auth_support import ISSUER, SUBJECT
from trading_db.account_keys import ReferenceKeys
from trading_db.accounts import AccountTransaction
from trading_db.enrollment import provision_owner

PREFERENCES = "/api/v1/preferences"
ACCOUNTS = "/api/v1/finance/accounts/query"


@pytest.mark.parametrize("context", [None, "", "b" * 64, "A" * 64, "x" * 65])
def test_context_failure_never_enters_financial_sql_or_revokes_valid_session(environment, context):
    client, _, workspace, _, admin = environment
    headers = login(client)
    changed = dict(headers)
    if context is None:
        changed.pop("X-Workspace-Context")
    else:
        changed["X-Workspace-Context"] = context
    statements = []

    def capture(*args):
        statements.append(True)

    event.listen(workspace._engine, "before_cursor_execute", capture)
    try:
        for method, path, body in [
            ("get", PREFERENCES, None),
            ("put", PREFERENCES, UPDATE),
            ("post", ACCOUNTS, {}),
        ]:
            arguments = {"headers": changed}
            if body is not None:
                arguments["json"] = body
            response = getattr(client, method)(path, **arguments)
            assert response.status_code == 412
            assert response.json()["error"] == "workspace_context_changed"
            assert set(response.json()) == {"error", "request_id"}
            assert response.headers["cache-control"] == "no-store"
            assert "set-cookie" not in response.headers
        assert not statements
    finally:
        event.remove(workspace._engine, "before_cursor_execute", capture)
    assert sql(admin, "SELECT count(*) FROM app.auth_sessions")[0][0] == 1
    assert sql(admin, "SELECT count(*) FROM app.workspace_preferences")[0][0] == 0
    assert client.get(PREFERENCES, headers=headers).json() == DEFAULT
    assert client.post(ACCOUNTS, headers=headers, json={}).status_code == 200


def test_duplicate_context_header_is_rejected_without_revoking_or_choosing_one(environment):
    client, _, _, _, _ = environment
    headers = login(client)
    duplicated = [*headers.items(), ("X-Workspace-Context", "b" * 64)]
    assert client.post(ACCOUNTS, headers=duplicated, json={}).status_code == 403
    assert client.get(PREFERENCES, headers=headers).status_code == 200


def test_context_survives_checked_renewal_but_changes_for_a_new_sign_in(environment):
    client, _, _, _, _ = environment
    first = login(client)
    for path in ["/api/v1/auth/session", "/api/v1/auth/session/activity"]:
        result = (
            client.get(path, headers=first)
            if path.endswith("/session")
            else client.post(path, headers=first, json={})
        )
        assert result.json()["workspace_context"] == first["X-Workspace-Context"]
    second = login(client)
    assert second["X-Workspace-Context"] != first["X-Workspace-Context"]
    assert client.get(PREFERENCES, headers=first).status_code == 412
    assert client.get(PREFERENCES, headers=second).status_code == 200


def test_old_tab_context_cannot_read_or_write_the_replacement_owner(environment, database):
    client, _, workspace, stub, admin = environment
    url, project = database
    first = login(client)
    assert client.put(PREFERENCES, headers=first, json=UPDATE).status_code == 200
    old_owner = sql(
        admin,
        "SELECT owner_id FROM app.owner_identities WHERE subject=:subject",
        subject=str(SUBJECT),
    )[0][0]
    new_subject = uuid4()
    provision_owner(url("bootstrap"), project, ISSUER, new_subject)
    # End the previous session with its original provider identity before switching
    # the synthetic provider. The old tab retains only its view marker.
    assert client.post("/api/v1/auth/logout", headers=first, json={}).status_code == 200
    stub.claim_changes["sub"] = str(new_subject)
    stub.claim_changes["session_id"] = str(uuid4())
    stub.overrides["/user"] = httpx.Response(
        200,
        json=dict(
            id=str(new_subject),
            role="authenticated",
            is_anonymous=False,
            email_confirmed_at="2026-01-01T00:00:00Z",
            factors=stub.factors,
        ),
    )
    second = login(client)
    new_owner = sql(
        admin,
        "SELECT owner_id FROM app.owner_identities WHERE subject=:subject",
        subject=str(new_subject),
    )[0][0]
    with workspace.transaction(new_owner) as unit:
        account = AccountTransaction(unit, ReferenceKeys({1: b"f" * 32}, 1)).create(definition())
    stale = {**second, "X-Workspace-Context": first["X-Workspace-Context"]}
    assert client.put(PREFERENCES, headers=stale, json=UPDATE).status_code == 412
    rejected = client.post(ACCOUNTS, headers=stale, json={})
    assert rejected.status_code == 412 and str(account.id) not in rejected.text
    assert client.get(PREFERENCES, headers=second).json() == DEFAULT
    assert client.post(ACCOUNTS, headers=second, json={}).json()["items"][0]["id"] == str(
        account.id
    )
    with workspace.transaction(old_owner) as unit:
        assert unit.preference_snapshot().model_dump() == {**UPDATE, "revision": 1}
    assert sql(admin, "SELECT count(*) FROM app.auth_sessions")[0][0] == 1
