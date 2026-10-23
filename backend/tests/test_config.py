import pytest
from pydantic import ValidationError

from trading_api.config import ConfigurationError, Settings, load_settings


def test_defaults_require_no_credentials_or_external_services():
    assert load_settings({}) == Settings(environment="development", port=8000)
    assert (
        load_settings({"TRADING_API_ENVIRONMENT": "test", "TRADING_API_PORT": "9123"}).port == 9123
    )


@pytest.mark.parametrize(
    "environ",
    [
        {"TRADING_API_ENVIRONMENT": "production"},
        {"TRADING_API_ENVIRONMENT": "staging"},
        {"TRADING_API_ENVIRONMENT": ""},
        {"TRADING_API_ENVIRONMENT": "Development"},
        {"TRADING_API_HOST": "0.0.0.0"},
        {"TRADING_API_DEBUG": "true"},
        {"TRADING_API_AUTH_BYPASS": "true"},
        {"TRADING_API_OWNER_ID": "10000000-0000-4000-8000-000000000001"},
        {"TRADING_API_TEST_IDENTITY": "enabled"},
        {"TRADING_API_CORS_ORIGINS": "*"},
        {"TRADING_API_POTR": "8000"},
        {"trading_api_port": "8000"},
    ],
)
def test_unsupported_or_unsafe_settings_fail_closed(environ):
    with pytest.raises(ConfigurationError):
        load_settings(environ)


@pytest.mark.parametrize(
    "port", ["", "0", "80", "1023", "65536", "08000", " 8000", "8e3", "８０００", "true"]
)
def test_port_is_an_explicit_unprivileged_integer(port):
    with pytest.raises(ConfigurationError):
        load_settings({"TRADING_API_PORT": port})


@pytest.mark.parametrize("port", ["1024", "65535"])
def test_port_boundaries_are_valid(port):
    assert load_settings({"TRADING_API_PORT": port}).port == int(port)


def test_configuration_failure_does_not_include_input():
    for key in ("TRADING_API_PORT", "TRADING_API_ENVIRONMENT", "TRADING_API_UNKNOWN"):
        with pytest.raises(ConfigurationError) as failure:
            load_settings({key: "synthetic-secret-do-not-echo"})
        assert "synthetic-secret" not in str(failure.value)


def test_environment_is_read_explicitly_without_loading_dotenv(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("TRADING_API_ENVIRONMENT=production\n")
    assert load_settings({}).environment == "development"
    monkeypatch.setenv("TRADING_API_ENVIRONMENT", "production")
    with pytest.raises(ConfigurationError):
        load_settings()


def test_settings_are_immutable_strict_and_reject_extra_controls():
    settings = Settings()
    with pytest.raises(ValidationError):
        settings.port = 9000
    with pytest.raises(ValidationError):
        Settings.model_validate({"port": "8000"})
    with pytest.raises(ValidationError):
        Settings.model_validate({"debug": True})
