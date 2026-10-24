"""Independent versioned AES-GCM custody, with explicit purpose and ownership binding."""

import secrets
from collections.abc import Mapping
from types import MappingProxyType
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from trading_connectors.indmoney_discovery import ISSUER, RESOURCE
from trading_connectors.indmoney_models import CALLBACK, ConnectorUnavailable
from trading_db.account_keys import packed


class ConnectorKeys:
    def __init__(self, keys: Mapping[int, bytes], active: int) -> None:
        if (
            not 1 <= len(keys) <= 8
            or type(active) is not int
            or any(type(v) is not int or not 1 <= v <= 2147483647 for v in keys)
            or active != max(keys)
            or any(type(k) is not bytes or len(k) != 32 for k in keys.values())
            or len(set(keys.values())) != len(keys)
        ):
            raise ConnectorUnavailable()
        self._keys = MappingProxyType(dict(keys))
        self.active = active

    def __repr__(self) -> str:
        return "ConnectorKeys(<redacted>)"

    def _cipher(self, version: int) -> AESGCM:
        if version not in self._keys:
            raise ConnectorUnavailable()
        key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=packed("trading/indmoney-custody/v1", version),
        ).derive(self._keys[version])
        return AESGCM(key)

    @staticmethod
    def _context(owner: UUID | None, identity: UUID | None, purpose: str, revision: int) -> bytes:
        if (
            purpose not in {"attempt", "tokens", "client"}
            or type(revision) is not int
            or not 1 <= revision <= 9007199254740991
            or (purpose == "client" and (owner is not None or identity is not None))
            or (
                purpose != "client"
                and (
                    not isinstance(owner, UUID)
                    or not owner.int
                    or not isinstance(identity, UUID)
                    or not identity.int
                )
            )
        ):
            raise ConnectorUnavailable()
        return packed(
            "indmoney/v1", ISSUER, RESOURCE, CALLBACK, str(owner), str(identity), purpose, revision
        )

    def seal(
        self, owner: UUID | None, identity: UUID | None, purpose: str, revision: int, raw: bytes
    ) -> bytes:
        if type(raw) is not bytes or not 1 <= len(raw) <= 32768:
            raise ConnectorUnavailable()
        version = self.active.to_bytes(4, "big")
        aad = self._context(owner, identity, purpose, revision) + version
        nonce = secrets.token_bytes(12)
        return version + nonce + self._cipher(self.active).encrypt(nonce, raw, aad)

    def open(
        self, owner: UUID | None, identity: UUID | None, purpose: str, revision: int, sealed: bytes
    ) -> bytes:
        try:
            if type(sealed) is not bytes or not 33 <= len(sealed) <= 32800:
                raise ConnectorUnavailable()
            aad = self._context(owner, identity, purpose, revision) + sealed[:4]
            return self._cipher(int.from_bytes(sealed[:4], "big")).decrypt(
                sealed[4:16], sealed[16:], aad
            )
        except ValueError, TypeError, InvalidTag:
            raise ConnectorUnavailable() from None
