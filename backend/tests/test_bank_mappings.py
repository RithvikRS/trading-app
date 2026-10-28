"""Protected mapping route transaction and private projection boundaries without SQL."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from pydantic import model_serializer
from starlette.testclient import TestClient

from tests.test_bank_mapping_contracts import command, page, scope, transition
from trading_api.authentication import CookiePolicy
from trading_api.bank_mapping_contracts import BankMappingHistoryPage, BankMappingTransition
from trading_api.bank_mappings import routes
from trading_api.read_contracts import WireModel
from trading_auth.models import AuthenticationDenied, AuthenticationLimited, WorkspaceContextChanged
from trading_db.bank_mappings import BankMappingTransaction, BankMappingUnavailable
from trading_db.connections import DatabaseFailure
from trading_db.workspace import OwnerAccessDenied

PATH = "/api/v1/finance/bank-source-mappings"


@pytest.fixture
def boundary(monkeypatch):
    trace = []
    state = SimpleNamespace(owner=uuid4(), auth_error=None, data_error=None, returned=None)

    @contextmanager
    def access(*args, **kwargs):
        trace.append("session guard")

        def validate():
            trace.append("final authorization")
            if state.auth_error:
                raise state.auth_error()

        try:
            yield state.owner, validate
        finally:
            trace.append("session released")

    @contextmanager
    def transaction(owner, *, read_only=False):
        assert owner == state.owner
        trace.append("read only" if read_only else "read write")
        try:
            yield object()
        except BaseException:
            trace.append("rollback")
            raise
        else:
            trace.append("commit")

    def operation(method):
        def run(self, request):
            trace.append(method)
            if state.data_error:
                raise state.data_error()
            return (
                state.returned
                if state.returned is not None
                else (transition() if method == "change" else page())
            )

        return run

    monkeypatch.setattr(BankMappingTransaction, "change", operation("change"))
    monkeypatch.setattr(BankMappingTransaction, "history", operation("history"))
    for model in (BankMappingTransition, BankMappingHistoryPage):
        original = model.model_dump_json

        def serializer(self, *args, _original=original, **kwargs):
            trace.append("serialize")
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(model, "model_dump_json", serializer)
    app = FastAPI()

    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = "synthetic-mapping-request"
        return await call_next(request)

    app.include_router(
        routes(
            SimpleNamespace(workspace_access=access),
            SimpleNamespace(transaction=transaction),
            CookiePolicy("http://127.0.0.1:8000"),
        )
    )
    with TestClient(app) as client:
        yield client, state, trace


def post(client, method):
    body = command().model_dump() if method == "change" else {"source_id": scope().source_id}
    return client.post(PATH + "/" + method, json=body)


@pytest.mark.parametrize("method", ["change", "history"])
def test_response_is_validated_before_final_authorization_and_commit(boundary, method):
    client, _, trace = boundary
    response = post(client, method)
    assert response.status_code == 200
    assert trace == [
        "session guard",
        "read write" if method == "change" else "read only",
        method,
        "serialize",
        "final authorization",
        "commit",
        "session released",
    ]
    if method == "change":
        assert response.json() == transition().model_dump()
        assert "request_id" not in response.json() and "is_current" not in response.json()
    else:
        assert response.json() == page().model_dump(mode="json")


@pytest.mark.parametrize(
    "failure", [AuthenticationDenied, AuthenticationLimited, WorkspaceContextChanged]
)
@pytest.mark.parametrize("method", ["change", "history"])
def test_final_auth_failures_cannot_become_mapping_conflicts(boundary, failure, method):
    client, state, trace = boundary
    state.auth_error = failure
    with pytest.raises(failure):
        post(client, method)
    assert trace[-3:] == ["final authorization", "rollback", "session released"]
    assert "commit" not in trace


@pytest.mark.parametrize("method", ["change", "history"])
def test_owner_denial_retains_authentication_semantics(boundary, method):
    client, state, trace = boundary
    state.data_error = OwnerAccessDenied
    with pytest.raises(AuthenticationDenied):
        post(client, method)
    assert "commit" not in trace and "rollback" in trace


@pytest.mark.parametrize(
    "failure,code,error",
    [
        (BankMappingUnavailable, 409, "bank_mapping_conflict"),
        (
            lambda: DatabaseFailure("Synthetic private database detail"),
            503,
            "financial_data_unavailable",
        ),
    ],
)
def test_data_failure_is_private_and_rolls_back_without_revoking_session_guard(
    boundary, failure, code, error
):
    client, state, trace = boundary
    state.data_error = failure
    response = post(client, "change")
    assert response.status_code == code
    assert response.json() == {"error": error, "request_id": "synthetic-mapping-request"}
    assert "Synthetic private" not in response.text and "set-cookie" not in response.headers
    assert trace[-2:] == ["rollback", "session released"] and "commit" not in trace


@pytest.mark.parametrize("kind", ["wrong-model", "counterfeit", "extra", "cycle", "bad-revision"])
def test_invalid_response_model_never_serializes_private_content_or_commits(boundary, kind):
    client, state, trace = boundary

    class Counterfeit(WireModel):
        @model_serializer
        def private(self):
            trace.append("counterfeit serializer")
            return {"private": "must not escape"}

    state.returned = transition()
    if kind == "wrong-model":
        state.returned = page()
    elif kind == "counterfeit":
        state.returned = Counterfeit()
    elif kind == "extra":
        state.returned.__dict__["private"] = "must not escape"
    elif kind == "cycle":
        state.returned.__dict__["account_id"] = state.returned
    else:
        state.returned.__dict__["revision"] = True
    response = post(client, "change")
    assert response.status_code == 409 and "must not escape" not in response.text
    assert "counterfeit serializer" not in trace and "commit" not in trace
    assert "final authorization" not in trace and "rollback" in trace


def test_response_byte_limit_is_checked_before_authorization_and_commit(boundary, monkeypatch):
    client, _, trace = boundary
    monkeypatch.setattr(
        BankMappingTransition, "model_dump_json", lambda *args, **kwargs: "x" * 262145
    )
    response = post(client, "change")
    assert response.status_code == 409
    assert "commit" not in trace and "final authorization" not in trace and "rollback" in trace


def test_projection_uses_real_stored_predecessor_and_private_missing_field_errors():
    service = BankMappingTransaction(object())
    with pytest.raises(BankMappingUnavailable):
        service._transition(scope(), {"source_id": scope().source_id})
    stored = transition(2).model_dump()
    assert service._transition(scope(), stored).previous_revision == 1
    stored["previous_revision"] = None
    with pytest.raises(BankMappingUnavailable):
        service._transition(scope(), stored)


def test_no_row_after_target_wait_still_rechecks_owner_and_reads_fresh_target(monkeypatch):
    service, trace = BankMappingTransaction(object()), []

    def execute(query, **parameters):
        assert "FOR SHARE" in query and "FOR KEY SHARE" not in query
        trace.append("target wait ended without row")
        return SimpleNamespace(scalar_one_or_none=lambda: None)

    def active():
        trace.append("fresh owner")

    def get(account):
        trace.append("fresh target")
        return None

    monkeypatch.setattr(service._accounts, "_execute", execute)
    monkeypatch.setattr(service, "_active", active)
    monkeypatch.setattr(service._accounts, "get", get)
    with pytest.raises(BankMappingUnavailable):
        service._admit_target(scope(), command().account_id)
    assert trace == ["target wait ended without row", "fresh owner", "fresh target"]
