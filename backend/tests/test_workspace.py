from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import URL
from sqlalchemy.exc import DisconnectionError

from trading_db.connections import DatabaseFailure, _reset_owner_context
from trading_db.workspace import OwnerAccessDenied, Preferences, WorkspaceDatabase


@pytest.mark.parametrize("role", ["trading_bootstrap", "trading_migrator", "postgres"])
def test_workspace_rejects_privileged_credentials_before_creating_engine(role):
    with patch("trading_db.workspace.engine_for") as create:
        with pytest.raises(DatabaseFailure):
            WorkspaceDatabase(URL.create("postgresql+psycopg", username=role), "project")
    create.assert_not_called()


@pytest.mark.parametrize(
    "identity", [None, "10000000-0000-4000-8000-000000000001", "", UUID(int=0)]
)
def test_identity_must_be_an_internal_nonzero_uuid_before_connect(identity):
    with patch("trading_db.workspace.engine_for") as create:
        store = WorkspaceDatabase(
            URL.create("postgresql+psycopg", username="trading_runtime"), "project"
        )
        with pytest.raises(OwnerAccessDenied):
            with store.transaction(identity):
                pytest.fail("Invalid identity was accepted")
    create.return_value.begin.assert_not_called()


@pytest.mark.parametrize(
    "values",
    [
        {"owner_id": "synthetic-private-identity"},
        {"theme": "other"},
        {"display_currency": "EUR"},
        {"amount_masked": "false"},
        {"amount_masked": 0},
        {"amount_masked": None},
        {"created_at": "2026-10-23T00:00:00Z"},
    ],
)
def test_preferences_reject_identity_metadata_and_coercion(values):
    with pytest.raises(ValidationError) as error:
        Preferences.model_validate(values)
    assert "synthetic-private-identity" not in str(error.value)


def test_preferences_default_to_masked_and_are_immutable():
    preferences = Preferences()
    assert preferences.amount_masked is True
    with pytest.raises(ValidationError):
        preferences.theme = "dark"


def test_reset_failure_discards_connection_and_does_not_expose_driver_payload():
    connection, record, state = Mock(), Mock(), Mock(terminate_only=False)
    connection.execute.side_effect = RuntimeError("synthetic-sensitive-driver-payload")
    with pytest.raises(DisconnectionError) as error:
        _reset_owner_context(connection, record, state)
    record.invalidate.assert_called_once_with()
    connection.rollback.assert_called_once_with()
    connection.commit.assert_not_called()
    assert str(error.value) == "Runtime connection reset failed."
    assert error.value.__suppress_context__
