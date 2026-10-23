"""Internal owner-scoped persistence; no authentication adapter or HTTP routes."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import URL, Connection, text

from trading_db.connections import DatabaseFailure, engine_for, verify_server


class OwnerAccessDenied(PermissionError):
    def __init__(self) -> None:
        super().__init__("Workspace access denied.")


class Preferences(BaseModel):
    """Allowlisted values only; ownership never comes from a preferences payload."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)
    theme: Literal["light", "dark"] = "light"
    display_currency: Literal["INR", "USD"] = "INR"
    amount_masked: bool = True


class WorkspaceTransaction:
    """Public operations expose no owner override, raw SQL, or transaction control."""

    def __init__(self, connection: Connection, owner_id: UUID) -> None:
        self._connection = connection
        self._owner_id = owner_id
        self._open = True

    def _require_open(self) -> None:
        if not self._open or not self._connection.in_transaction():
            raise DatabaseFailure("Workspace transaction has ended.")

    def get_preferences(self) -> Preferences | None:
        self._require_open()
        row = (
            self._connection.execute(
                text(
                    "SELECT theme, display_currency, amount_masked "
                    "FROM app.workspace_preferences WHERE owner_id = :owner"
                ),
                {"owner": self._owner_id},
            )
            .mappings()
            .one_or_none()
        )
        return Preferences.model_validate(dict(row)) if row is not None else None

    def save_preferences(self, preferences: Preferences) -> None:
        self._require_open()
        # Revalidate even a model assembled with model_construct/model_copy.
        validated = Preferences.model_validate(preferences.model_dump())
        self._connection.execute(
            text("""
                INSERT INTO app.workspace_preferences
                    (owner_id, theme, display_currency, amount_masked)
                VALUES (:owner, :theme, :display_currency, :amount_masked)
                ON CONFLICT (owner_id) DO UPDATE SET
                    theme = excluded.theme,
                    display_currency = excluded.display_currency,
                    amount_masked = excluded.amount_masked
            """),
            {"owner": self._owner_id, **validated.model_dump()},
        )


class WorkspaceDatabase:
    """Accept an internal UUID only after server-side identity verification in Step 3E.

    A UUID is a scope, not authentication proof. Currently only synthetic tests invoke
    this interface; nothing reads an identity from requests, environment, or the UI.
    """

    def __init__(self, url: URL, project: str) -> None:
        if url.username != "trading_runtime":
            raise DatabaseFailure("Workspace access requires the restricted runtime identity.")
        self._engine = engine_for(url)
        self._project = project

    def close(self) -> None:
        self._engine.dispose()

    @contextmanager
    def transaction(self, owner_id: UUID) -> Iterator[WorkspaceTransaction]:
        if not isinstance(owner_id, UUID) or owner_id.int == 0:
            raise OwnerAccessDenied()
        unit: WorkspaceTransaction | None = None
        try:
            with self._engine.begin() as connection:
                verify_server(connection, str(self._engine.url.database), self._project)
                role = connection.execute(
                    text("""
                    SELECT current_user = 'trading_runtime' AND session_user = 'trading_runtime'
                        AND NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication
                                 OR rolbypassrls)
                        AND NOT EXISTS (SELECT 1 FROM pg_auth_members WHERE member = pg_roles.oid)
                        AND NOT has_database_privilege(current_database(), 'CREATE')
                        AND NOT has_database_privilege(current_database(), 'TEMP')
                        AND NOT has_schema_privilege('app', 'CREATE')
                        AND NOT EXISTS (SELECT 1 FROM pg_namespace
                            WHERE nspname IN ('app', 'app_meta', 'public')
                            AND nspowner=pg_roles.oid)
                        AND NOT EXISTS (SELECT 1 FROM pg_class AS relation
                            JOIN pg_namespace AS namespace ON namespace.oid=relation.relnamespace
                            WHERE namespace.nspname IN ('app', 'app_meta')
                            AND relation.relowner=pg_roles.oid)
                    FROM pg_roles WHERE rolname = current_user
                """)
                ).scalar_one()
                if not role:
                    raise DatabaseFailure("Workspace identity has unexpected elevated privileges.")
                connection.execute(
                    text("SELECT set_config('app.owner_id', :owner, true)"),
                    {"owner": str(owner_id)},
                )
                active = connection.execute(
                    text("SELECT id FROM app.owners WHERE id = :owner AND is_active"),
                    {"owner": owner_id},
                ).scalar_one_or_none()
                if active is None:
                    raise OwnerAccessDenied()
                unit = WorkspaceTransaction(connection, owner_id)
                yield unit
        finally:
            if unit is not None:
                unit._open = False
