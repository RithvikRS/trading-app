"""Versioned private-reference custody, independent of authentication and backup keys."""

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from trading_db.connections import DatabaseFailure

NAMESPACES = frozenset(
    (
        "hdfc_statement",
        "sbi_statement",
        "indmoney_india",
        "indmoney_us",
        "indmoney_funds",
        "cas",
        "advisor",
        "ubs_espp",
    )
)
REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", re.ASCII)


class ReferenceUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__("Source reference or identifier key is unavailable.")


def context(owner: UUID, namespace: str) -> None:
    if not isinstance(owner, UUID) or not owner.int or namespace not in NAMESPACES:
        raise ReferenceUnavailable()


def reference(value: str) -> str:
    # Provider-specific normalization belongs in a future parser, never in matching.
    if type(value) is not str or REFERENCE.fullmatch(value) is None:
        raise ReferenceUnavailable()
    return value


def packed(*parts: str | int) -> bytes:
    return json.dumps(parts, separators=(",", ":"), ensure_ascii=True).encode("ascii")


class ReferenceKeys:
    """Bounded key ring with a redacted repr; no key material enters a database row."""

    def __init__(self, keys: Mapping[int, bytes], active: int) -> None:
        if (
            not 1 <= len(keys) <= 8
            or type(active) is not int
            or active not in keys
            or any(type(v) is not int or not 1 <= v <= 2147483647 for v in keys)
            or any(type(k) is not bytes or len(k) != 32 for k in keys.values())
            or len(set(keys.values())) != len(keys)
        ):
            raise ReferenceUnavailable()
        if active != max(keys):
            raise ReferenceUnavailable()
        self._keys = MappingProxyType(dict(keys))
        self._active = active

    def __repr__(self) -> str:
        return "ReferenceKeys(<redacted>)"

    @property
    def active(self) -> int:
        return self._active

    @property
    def versions(self) -> tuple[int, ...]:
        return tuple(sorted(self._keys))

    def _derive(self, version: int, purpose: str) -> bytes:
        if type(version) is not int or version not in self._keys:
            raise ReferenceUnavailable()
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=packed("trading/account-reference/v1", version, purpose),
        ).derive(self._keys[version])

    def key_check(self, owner: UUID, version: int) -> str:
        return hmac.new(
            self._derive(version, "check"), packed(str(owner)), hashlib.sha256
        ).hexdigest()

    def check(self, owner: UUID, version: int, check: str) -> None:
        if type(check) is not str or not hmac.compare_digest(self.key_check(owner, version), check):
            raise ReferenceUnavailable()

    def fingerprint(self, owner: UUID, namespace: str, value: str, version: int) -> str:
        context(owner, namespace)
        return hmac.new(
            self._derive(version, "match"),
            packed(str(owner), namespace, reference(value)),
            hashlib.sha256,
        ).hexdigest()

    def seal(self, owner: UUID, source_id: UUID, namespace: str, value: str) -> dict[str, Any]:
        if not isinstance(source_id, UUID) or not source_id.int:
            raise ReferenceUnavailable()
        version = self.active
        digest = self.fingerprint(owner, namespace, value, version)
        aad = packed(str(owner), str(source_id), namespace, version, digest)
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._derive(version, "encrypt")).encrypt(nonce, value.encode(), aad)
        return {
            "key_version": version,
            "key_check": self.key_check(owner, version),
            "fingerprint": digest,
            "encrypted_reference": base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii"),
        }

    def open(self, row: Mapping[str, Any]) -> str:
        try:
            owner, source_id = UUID(str(row["owner_id"])), UUID(str(row["id"]))
            namespace, version = row["namespace"], row["key_version"]
            context(owner, namespace)
            if not source_id.int:
                raise ReferenceUnavailable()
            self.check(owner, version, row["key_check"])
            encoded = row["encrypted_reference"]
            if type(encoded) is not str or not 40 <= len(encoded) <= 256:
                raise ReferenceUnavailable()
            data = base64.b64decode(encoded, altchars=b"-_", validate=True)
            aad = packed(str(owner), str(source_id), namespace, version, row["fingerprint"])
            value = AESGCM(self._derive(version, "encrypt")).decrypt(data[:12], data[12:], aad)
            result = reference(value.decode("ascii"))
            if not hmac.compare_digest(
                row["fingerprint"], self.fingerprint(owner, namespace, result, version)
            ):
                raise ReferenceUnavailable()
            return result
        except ValueError, TypeError, KeyError, UnicodeError, InvalidTag:
            raise ReferenceUnavailable() from None


def load_keys(directory: Path, *, active: int, versions: tuple[int, ...]) -> ReferenceKeys:
    """Recover keys separately; refusing missing files never generates replacement keys."""
    try:
        if (
            any(path.is_symlink() or path.is_junction() for path in (directory, *directory.parents))
            or not 1 <= len(versions) <= 8
            or len(set(versions)) != len(versions)
            or (os.name != "nt" and directory.stat().st_mode & 0o077)
        ):
            raise ReferenceUnavailable()
        keys = {}
        for version in versions:
            if type(version) is not int or not 1 <= version <= 2147483647:
                raise ReferenceUnavailable()
            path = directory / f"v{version}.key"
            if (
                path.is_symlink()
                or not path.is_file()
                or (os.name != "nt" and path.stat().st_mode & 0o077)
            ):
                raise ReferenceUnavailable()
            with path.open("rb") as stream:
                keys[version] = stream.read(33)
        return ReferenceKeys(keys, active)
    except OSError, ValueError:
        raise ReferenceUnavailable() from None


def initialize_key(directory: Path, version: int) -> None:
    from trading_db.local import private_directory

    if type(version) is not int or not 1 <= version <= 2147483647:
        raise ReferenceUnavailable()
    try:
        if any(path.is_symlink() or path.is_junction() for path in (directory, *directory.parents)):
            raise ReferenceUnavailable()
        private_directory(directory)
        path = directory / f"v{version}.key"
        if directory.is_symlink() or path.is_symlink():
            raise ReferenceUnavailable()
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(secrets.token_bytes(32))
    except OSError, ValueError:
        raise ReferenceUnavailable() from None


if __name__ == "__main__":
    from trading_db.local import ROOT

    parser = argparse.ArgumentParser(description="Create an independent local identifier key.")
    parser.add_argument("version", type=int)
    args = parser.parse_args()
    try:
        initialize_key(ROOT / ".cache/finance/keys", args.version)
    except DatabaseFailure:
        parser.exit(1, "Identifier key creation failed; no existing key was replaced.\n")
    print("Identifier key created in the private local key directory.")
