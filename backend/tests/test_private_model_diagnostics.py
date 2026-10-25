"""Malformed internal models fail without serializing private input to diagnostics."""

import warnings
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError

from trading_api import application
from trading_api.config import Settings
from trading_auth import supabase
from trading_auth.config import AuthSettings
from trading_connectors.indmoney_models import (
    AttemptSecrets,
    ConnectorUnavailable,
    TokenSecrets,
    private_document,
)
from trading_db.accounts import AccountDefinition, AccountTransaction
from trading_db.indmoney import IndmoneyDatabase
from trading_db.instruments import (
    IdentifierDefinition,
    InstrumentDefinition,
    InstrumentTransaction,
    ListingDefinition,
    SchemeDefinition,
)
from trading_db.market_contracts import MarketDefinition, MarketTarget
from trading_db.markets import MarketTransaction
from trading_db.workspace import Preferences, PreferenceUpdate, WorkspaceTransaction

MARKER = "fabricated-private-diagnostic-marker"
IDENTITY = UUID("10000000-0000-4000-8000-000000000001")


def malformed(definition, field, construction):
    if construction == "copy":
        return definition.model_copy(update={field: [MARKER]})
    return type(definition).model_construct(**(definition.model_dump() | {field: [MARKER]}))


def assert_private_rejection(action, error_type, caplog, capsys):
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        with pytest.raises(error_type) as error:
            action()
    output = capsys.readouterr()
    assert MARKER not in output.out + output.err + caplog.text + str(error.value) + repr(
        error.value
    )
    assert captured == []


class NoDatabase:
    def __init__(self):
        self.calls = []

    def in_transaction(self):
        return True

    def execute(self, *args, **kwargs):
        self.calls.append("execute")
        raise AssertionError("Malformed input reached SQL.")

    def begin_nested(self):
        self.calls.append("begin_nested")
        raise AssertionError("Malformed input began a write.")


@pytest.mark.parametrize("construction", ["copy", "construct"])
@pytest.mark.parametrize(
    "operation,definition,field",
    [
        (
            "account",
            AccountDefinition(
                kind="bank",
                institution="hdfc",
                market="IN",
                label="Synthetic bank",
                currencies=("INR",),
            ),
            "label",
        ),
        ("scheme", SchemeDefinition(name="Synthetic fund"), "name"),
        (
            "instrument",
            InstrumentDefinition(
                name="Synthetic equity", asset_class="equity", isin="US0378331005"
            ),
            "name",
        ),
        (
            "listing",
            ListingDefinition(venue="XNAS", symbol="SYNTHETIC", quote_currency="USD"),
            "symbol",
        ),
        ("identifier", IdentifierDefinition(namespace="ubs", value="SYNTHETIC"), "value"),
        (
            "market_list",
            MarketTarget(kind="nav", instrument_id=IDENTITY, currency="INR", basis="nav"),
            "instrument_id",
        ),
        (
            "market_record",
            MarketDefinition(
                kind="fx",
                base_currency="USD",
                quote_currency="INR",
                basis="reference",
                namespace="manual_evidence",
                digest="a" * 64,
                occurrence=1,
                normalizer="synthetic",
                normalizer_version=1,
                observed_on="2026-10-24",
                source="83.123456789012",
            ),
            "source",
        ),
        ("preferences_save", Preferences(), "amount_masked"),
        (
            "preferences_compare",
            PreferenceUpdate(theme="light", display_currency="INR", amount_masked=True, revision=0),
            "revision",
        ),
    ],
    ids=[
        "account",
        "scheme",
        "instrument",
        "listing",
        "identifier",
        "market-list",
        "market-record",
        "preferences-save",
        "preferences-compare",
    ],
)
def test_internal_service_revalidation_is_private_and_precedes_sql(
    operation, definition, field, construction, caplog, capsys
):
    connection = NoDatabase()
    unit = WorkspaceTransaction(connection, IDENTITY)
    instruments = InstrumentTransaction(unit)
    markets = MarketTransaction(unit)
    actions = {
        "account": AccountTransaction(unit, None).create,
        "scheme": instruments.scheme,
        "instrument": instruments.create,
        "listing": lambda value: instruments.listing(IDENTITY, value),
        "identifier": instruments.identifier,
        "market_list": markets.list,
        "market_record": markets.record,
        "preferences_save": unit.save_preferences,
        "preferences_compare": unit.compare_preferences,
    }
    value = malformed(definition, field, construction)
    assert_private_rejection(lambda: actions[operation](value), ValidationError, caplog, capsys)
    assert connection.calls == []


@pytest.mark.parametrize("construction", ["copy", "construct"])
@pytest.mark.parametrize("boundary", ["api", "supabase"])
def test_injected_configuration_rejects_privately_before_client_or_app_creation(
    boundary, construction, monkeypatch, caplog, capsys
):
    created = []

    def forbidden(*args, **kwargs):
        created.append("created")
        raise AssertionError("Malformed configuration reached application/client creation.")

    if boundary == "api":
        monkeypatch.setattr(application, "FastAPI", forbidden)
        value = malformed(Settings(), "port", construction)

        def action():
            return application.create_app(value)
    else:
        monkeypatch.setattr(supabase.httpx, "Client", forbidden)
        settings = AuthSettings(
            project_url="https://abcdefghijklmnopqrst.supabase.co",
            publishable_key=SecretStr("sb_publishable_synthetic_test_key_only"),
        )
        value = malformed(settings, "project_url", construction)

        def action():
            return supabase.SupabaseProvider(value)

    assert_private_rejection(action, ValidationError, caplog, capsys)
    assert created == []


@pytest.mark.parametrize("construction", ["copy", "construct"])
@pytest.mark.parametrize("boundary", ["token_custody", "attempt_document"])
def test_private_connector_documents_reject_without_diagnostic_leakage(
    boundary, construction, caplog, capsys
):
    if boundary == "token_custody":
        definition = TokenSecrets(
            access_token=SecretStr("synthetic-access-credential-only"),
            token_type="Bearer",
            expires_in=3600,
            scope="portfolio:read",
        )
        value = malformed(definition, "expires_in", construction)

        def action():
            return IndmoneyDatabase._token_bytes(SimpleNamespace(binding="a" * 64), value)
    else:
        definition = AttemptSecrets(
            pkce=SecretStr("s" * 43),
            issuer_required=True,
            refresh_supported=True,
            client_binding="a" * 64,
        )
        value = malformed(definition, "client_binding", construction)

        def action():
            return private_document(value.private_bytes())

    assert_private_rejection(action, ConnectorUnavailable, caplog, capsys)
