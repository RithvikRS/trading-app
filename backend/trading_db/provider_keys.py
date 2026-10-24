"""Protected provider transaction references, separated from account-reference purposes."""

import base64
import hashlib
import hmac
import secrets
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from trading_db.account_keys import ReferenceKeys, ReferenceUnavailable, packed, reference
from trading_db.import_contracts import EVENT_KINDS


class ProviderKeys:
    def __init__(self, keys: ReferenceKeys) -> None:
        self._keys = keys

    def __repr__(self) -> str:
        return "ProviderKeys(<redacted>)"

    @property
    def active(self) -> int:
        return self._keys.active

    def _derive(self, version: int, purpose: str) -> bytes:
        return self._keys._derive(version, "provider-event/v1/" + purpose)

    @staticmethod
    def _context(owner: UUID, source: UUID, kind: str) -> None:
        if (
            not isinstance(owner, UUID)
            or not owner.int
            or not isinstance(source, UUID)
            or not source.int
            or type(kind) is not str
            or kind not in EVENT_KINDS
        ):
            raise ReferenceUnavailable()

    def key_check(self, owner: UUID, version: int) -> str:
        return hmac.new(
            self._derive(version, "check"), packed(str(owner)), hashlib.sha256
        ).hexdigest()

    def fingerprint(self, owner: UUID, source: UUID, kind: str, value: str, version: int) -> str:
        self._context(owner, source, kind)
        return hmac.new(
            self._derive(version, "match"),
            packed(str(owner), str(source), kind, reference(value)),
            hashlib.sha256,
        ).hexdigest()

    def seal(
        self, owner: UUID, identity: UUID, source: UUID, kind: str, value: str
    ) -> dict[str, Any]:
        if not isinstance(identity, UUID) or not identity.int:
            raise ReferenceUnavailable()
        version = self.active
        digest = self.fingerprint(owner, source, kind, value, version)
        aad = packed(str(owner), str(identity), str(source), kind, version, digest)
        nonce = secrets.token_bytes(12)
        encrypted = AESGCM(self._derive(version, "encrypt")).encrypt(nonce, value.encode(), aad)
        return dict(
            key_version=version,
            key_check=self.key_check(owner, version),
            fingerprint=digest,
            encrypted_reference=base64.urlsafe_b64encode(nonce + encrypted).decode("ascii"),
        )

    def open(self, row: Mapping[str, Any]) -> str:
        try:
            owner, identity, source = (
                UUID(str(row[key])) for key in ("owner_id", "id", "source_id")
            )
            kind, version = row["kind"], row["key_version"]
            self._context(owner, source, kind)
            if not identity.int or not hmac.compare_digest(
                self.key_check(owner, version), row["key_check"]
            ):
                raise ReferenceUnavailable()
            encoded = row["encrypted_reference"]
            if type(encoded) is not str or not 40 <= len(encoded) <= 256:
                raise ReferenceUnavailable()
            data = base64.b64decode(encoded, altchars=b"-_", validate=True)
            aad = packed(str(owner), str(identity), str(source), kind, version, row["fingerprint"])
            value = AESGCM(self._derive(version, "encrypt")).decrypt(data[:12], data[12:], aad)
            result = reference(value.decode("ascii"))
            if not hmac.compare_digest(
                row["fingerprint"], self.fingerprint(owner, source, kind, result, version)
            ):
                raise ReferenceUnavailable()
            return result
        except ValueError, TypeError, KeyError, UnicodeError, InvalidTag:
            raise ReferenceUnavailable() from None
