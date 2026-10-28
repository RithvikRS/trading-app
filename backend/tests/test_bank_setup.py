"""Finite setup inputs and pre-commit authorization ordering without a database."""

import json
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from starlette.testclient import TestClient

from trading_api.authentication import CookiePolicy
from trading_api.bank_setup import routes
from trading_api.bank_setup_contracts import BankSetupCommand, BankSetupHead, BankSetupReceipt
from trading_auth.models import AuthenticationDenied, AuthenticationLimited, WorkspaceContextChanged
from trading_db.bank_setup import BankSetupTransaction, BankSetupUnavailable
from trading_db.workspace import OwnerAccessDenied


def command(**changes):
    return dict(
        intent_id=str(uuid4()),
        expected_revision=0,
        institution="hdfc",
        label="Everyday account",
        currencies=["INR"],
        **changes,
    )


def receipt(body):
    return BankSetupReceipt.model_validate(
        {key: value for key, value in body.items() if key != "expected_revision"}
        | {"revision": body["expected_revision"] + 1, "account_id": str(uuid4())}
    )


@pytest.mark.parametrize("currencies", [["INR"], ["USD"], ["INR", "USD"]])
def test_json_arrays_have_one_canonical_immutable_representation(currencies):
    body = command()
    body["currencies"] = currencies
    parsed = BankSetupCommand.model_validate(body)
    assert parsed.currencies == tuple(currencies)
    assert BankSetupCommand.model_validate_json(json.dumps(body)) == parsed
    assert body["label"] not in repr(parsed)
    assert BankSetupCommand.model_validate(parsed.model_dump()) == parsed


@pytest.mark.parametrize(
    "changes",
    [
        {"currencies": ["USD", "INR"]},
        {"currencies": []},
        {"currencies": ["INR", "INR"]},
        {"currencies": "INR"},
        {"currencies": [1]},
        {"currencies": ["EUR"]},
        {"institution": "ubs"},
        {"institution": "HDFC"},
        {"label": "Account 1234"},
        {"label": " account"},
        {"label": "name\n"},
        {"label": "a" * 65},
        {"label": ""},
        {"expected_revision": True},
        {"expected_revision": -1},
        {"expected_revision": 1001},
        {"expected_revision": "0"},
        {"intent_id": "00000000-0000-0000-0000-000000000000"},
        {"intent_id": "ABCDEFAB-1234-1234-1234-ABCDEFABCDEF"},
        {"owner_id": str(uuid4())},
        {"provider_reference": "private"},
        {"balance": "0"},
    ],
)
def test_setup_rejects_noncanonical_or_excess_information(changes):
    body = command() | changes
    with pytest.raises(ValidationError) as error:
        BankSetupCommand.model_validate(body)
    assert "input_value" not in str(error.value)


def test_heads_bind_last_receipt_and_revalidate_constructed_models():
    saved = receipt(command())
    assert BankSetupHead(revision=0, last_saved=None).last_saved is None
    assert BankSetupHead(revision=1, last_saved=saved).last_saved == saved
    for revision, last in [(0, saved), (1, None), (2, saved), (True, saved)]:
        with pytest.raises(ValidationError):
            BankSetupHead(revision=revision, last_saved=last)
    unsafe = BankSetupCommand.model_construct(**(command() | {"currencies": ("EUR",)}))
    with pytest.raises(ValidationError):
        BankSetupCommand.model_validate(unsafe)


@pytest.fixture
def harness(monkeypatch):
    trace = []
    state = SimpleNamespace(failure=None, data_failure=None)

    @contextmanager
    def access(*args, **kwargs):
        trace.append("session guard")

        def validate():
            trace.append("final authorization")
            if state.failure:
                raise state.failure()

        try:
            yield uuid4(), validate
        finally:
            trace.append("session released")

    @contextmanager
    def transaction(owner, *, read_only=False):
        trace.append("transaction")
        try:
            yield object()
        except BaseException:
            trace.append("rollback")
            raise
        else:
            trace.append("commit")

    def create(self, body):
        trace.append("creation")
        if state.data_failure:
            raise state.data_failure()
        return receipt(body.model_dump())

    monkeypatch.setattr(BankSetupTransaction, "create", create)
    original = BankSetupReceipt.model_dump_json

    def serialize(self, *args, **kwargs):
        trace.append("serialize")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(BankSetupReceipt, "model_dump_json", serialize)
    app = FastAPI()

    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = "synthetic-request"
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


def test_wire_json_serialization_and_final_authorization_precede_commit(harness):
    client, _, trace = harness
    response = client.post("/api/v1/finance/bank-account-setup/create", json=command())
    assert response.status_code == 200 and response.json()["revision"] == 1
    assert trace == [
        "session guard",
        "transaction",
        "creation",
        "serialize",
        "final authorization",
        "commit",
        "session released",
    ]


@pytest.mark.parametrize(
    "failure", [AuthenticationDenied, AuthenticationLimited, WorkspaceContextChanged]
)
def test_final_authorization_exceptions_are_never_normal_creation_conflicts(harness, failure):
    client, state, trace = harness
    state.failure = failure
    with pytest.raises(failure):
        client.post("/api/v1/finance/bank-account-setup/create", json=command())
    assert trace[-3:] == ["final authorization", "rollback", "session released"]
    assert "commit" not in trace


def test_failed_data_operation_rolls_back_and_is_private(harness):
    client, state, trace = harness
    state.data_failure = BankSetupUnavailable
    response = client.post("/api/v1/finance/bank-account-setup/create", json=command())
    assert response.status_code == 409
    assert response.json() == {"error": "bank_setup_conflict", "request_id": "synthetic-request"}
    assert "commit" not in trace and "rollback" in trace


def test_post_wait_owner_denial_keeps_authentication_semantics(harness):
    client, state, trace = harness
    state.data_failure = OwnerAccessDenied
    with pytest.raises(AuthenticationDenied):
        client.post("/api/v1/finance/bank-account-setup/create", json=command())
    assert "commit" not in trace and "rollback" in trace


@pytest.mark.parametrize("kind", ["wrong-model", "counterfeit", "cycle", "extra", "bad-field"])
def test_invalid_result_never_serializes_untrusted_model_or_commits(harness, monkeypatch, kind):
    from pydantic import model_serializer

    from trading_api.read_contracts import WireModel

    client, _, trace = harness

    class Counterfeit(WireModel):
        @model_serializer
        def leak(self):
            trace.append("untrusted serializer")
            return {"secret": "must not escape"}

    result = receipt(command())
    if kind == "wrong-model":
        result = BankSetupHead(revision=0, last_saved=None)
    elif kind == "counterfeit":
        result = Counterfeit()
    elif kind == "cycle":
        result.__dict__["currencies"] = (result,)
    elif kind == "extra":
        result.__dict__["private"] = "must not escape"
    else:
        result.__dict__["label"] = "Invalid 1234"
    monkeypatch.setattr(BankSetupTransaction, "create", lambda self, body: result)
    response = client.post("/api/v1/finance/bank-account-setup/create", json=command())
    assert response.status_code == 409
    assert "must not escape" not in response.text
    assert "untrusted serializer" not in trace and "commit" not in trace
    assert "rollback" in trace and "final authorization" not in trace


def test_missing_database_projection_is_a_local_data_error():
    service = BankSetupTransaction(object())
    with pytest.raises(BankSetupUnavailable):
        service._receipt({"intent_id": str(uuid4())})
