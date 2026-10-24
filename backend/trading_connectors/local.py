"""Explicit local connector custody; no dynamic registration or implicit key creation."""

import argparse
import getpass
import os
import ssl
import sys
from pathlib import Path

from trading_auth.browser import BrowserAuth
from trading_connectors.indmoney_keys import ConnectorKeys
from trading_connectors.indmoney_models import ClientRegistration, ConnectorUnavailable
from trading_connectors.indmoney_provider import IndmoneyProvider
from trading_connectors.indmoney_service import IndmoneyService
from trading_db.account_keys import initialize_key
from trading_db.indmoney import IndmoneyDatabase
from trading_db.local import ROOT, development, private_directory

DIRECTORY = ROOT / ".cache/indmoney"


def private_read(path: Path, limit: int) -> bytes:
    try:
        if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)) or (
            os.name != "nt" and path.stat().st_mode & 0o077
        ):
            raise ConnectorUnavailable()
        with path.open("rb") as stream:
            value = stream.read(limit + 1)
        if not 1 <= len(value) <= limit:
            raise ConnectorUnavailable()
        return value
    except OSError:
        raise ConnectorUnavailable() from None


def load_keys() -> ConnectorKeys:
    try:
        if any(
            name.upper().startswith("TRADING_INDMONEY_") and name != "TRADING_INDMONEY_KEY_VERSIONS"
            for name in os.environ
        ):
            raise ValueError()
        versions = os.environ.get("TRADING_INDMONEY_KEY_VERSIONS", "1").split(",")
        if not 1 <= len(versions) <= 8 or any(
            not v.isascii() or not v.isdecimal() or str(int(v)) != v for v in versions
        ):
            raise ValueError()
        numbers = [int(v) for v in versions]
        if len(set(numbers)) != len(numbers):
            raise ValueError()
        return ConnectorKeys(
            {v: private_read(DIRECTORY / "keys" / f"v{v}.key", 32) for v in numbers}, max(numbers)
        )
    except ValueError, OSError:
        raise ConnectorUnavailable() from None


def local_service(browser: BrowserAuth) -> IndmoneyService:
    try:
        keys = load_keys()
        raw = keys.open(None, None, "client", 1, private_read(DIRECTORY / "client.sealed", 32800))
        client = ClientRegistration.model_validate_json(raw)
        provider = IndmoneyProvider(client)
        database = development()
        store = IndmoneyDatabase(
            database.url("auth"), database.project, keys=keys, binding=provider.binding
        )
        return IndmoneyService(browser, store, provider)
    except Exception:
        raise ConnectorUnavailable() from None


def tls_files() -> tuple[str, str]:
    certificate, key = DIRECTORY / "tls/cert.pem", DIRECTORY / "tls/key.pem"
    private_read(certificate, 16384)
    private_read(key, 16384)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate, key)
    return str(certificate), str(key)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init-key", "import-client", "rotate-client"))
    parser.add_argument("--version", type=int, default=1)
    args = parser.parse_args()
    try:
        if args.action == "init-key":
            initialize_key(DIRECTORY / "keys", args.version)
        else:
            keys = load_keys()
            if args.action == "import-client":
                # Hidden interactive input only; never CLI arguments, environment or stdout.
                if not sys.stdin.isatty() or not sys.stderr.isatty():
                    raise ConnectorUnavailable()
                from pydantic import SecretStr

                client = ClientRegistration(
                    client_id=SecretStr(getpass.getpass("Client identifier: ")),
                    client_secret=SecretStr(getpass.getpass("Client secret: ")),
                )
                private_directory(DIRECTORY)
                sealed = keys.seal(None, None, "client", 1, client.private_bytes())
                descriptor = os.open(
                    DIRECTORY / "client.sealed", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(sealed)
            else:
                path = DIRECTORY / "client.sealed"
                raw = keys.open(None, None, "client", 1, private_read(path, 32800))
                ClientRegistration.model_validate_json(raw)
                temporary = DIRECTORY / "client.rotating"
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(keys.seal(None, None, "client", 1, raw))
                os.replace(temporary, path)
    except Exception:
        parser.exit(
            1,
            "Connector custody operation failed; inspect local setup privately.\n",
        )
    print("Connector custody operation completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
