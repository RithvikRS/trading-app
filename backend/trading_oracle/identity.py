"""Exact identity lookup under its own restricted database credential."""

from uuid import UUID

import oracledb

from trading_oracle.connections import ClientPool
from trading_oracle.contracts import IdentityKey, exact_uuid
from trading_oracle.metadata import require


class IdentityDirectory:
    """Accepts an independently verified issuer/subject; this is not token authentication."""

    def __init__(self, pool: ClientPool) -> None:
        require(pool.role == "TRADING_AUTH")
        self._pool = pool

    def resolve(self, identity: IdentityKey) -> UUID | None:
        identity = IdentityKey.model_validate(identity.model_dump(warnings=False))
        with self._pool.checkout() as connection:
            with connection.cursor() as cursor:
                result = cursor.var(oracledb.DB_TYPE_RAW, size=16)
                cursor.callproc(
                    "TRADING_MIGRATOR.IDENTITY_LOOKUP.RESOLVE_OWNER",
                    [
                        identity.issuer.encode("utf-8"),
                        identity.subject.encode("utf-8"),
                        result,
                    ],
                )
                value = result.getvalue()
            return None if value is None else exact_uuid(value)

    def close(self) -> None:
        self._pool.close()
