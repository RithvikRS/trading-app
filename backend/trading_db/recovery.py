"""Bounded foundation recovery rehearsal; accepts only disposable local databases."""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import URL, Connection, text

from trading_db import migrate
from trading_db.account_keys import ReferenceKeys, ReferenceUnavailable
from trading_db.connections import DatabaseFailure, engine_for, require_disposable, verify_server
from trading_db.provider_keys import ProviderKeys

HEAD = "0017_reconciled_completion"
FORMAT = 13
LIMIT = 4_000_000
MAX_ROWS = 1000
COLUMNS = {
    "owners": ("id", "is_active", "created_at"),
    "owner_identities": ("issuer", "subject", "owner_id", "created_at", "mfa_enrolled"),
    "workspace_preferences": (
        "owner_id",
        "theme",
        "display_currency",
        "amount_masked",
        "created_at",
        "updated_at",
        "revision",
    ),
    "auth_revocations": ("owner_id", "revoked_before"),
    "security_events": (
        "id",
        "occurred_at",
        "event",
        "outcome",
        "request_id",
        "actor",
        "session_reference",
    ),
    "financial_accounts": (
        "owner_id",
        "id",
        "kind",
        "institution",
        "market",
        "label",
        "archived_at",
        "revision",
        "created_at",
        "updated_at",
    ),
    "account_currencies": ("owner_id", "account_id", "currency"),
    "source_accounts": (
        "owner_id",
        "id",
        "namespace",
        "key_version",
        "key_check",
        "fingerprint",
        "encrypted_reference",
        "revision",
        "created_at",
        "updated_at",
    ),
    "source_account_mappings": (
        "owner_id",
        "source_id",
        "revision",
        "previous_revision",
        "account_id",
        "reason",
        "created_at",
    ),
    "fund_schemes": ("owner_id", "id", "name", "created_at"),
    "instruments": (
        "owner_id",
        "id",
        "asset_class",
        "name",
        "isin",
        "fund_scheme_id",
        "fund_plan",
        "fund_option",
        "fund_currency",
        "created_at",
    ),
    "instrument_listings": (
        "owner_id",
        "id",
        "instrument_id",
        "venue",
        "symbol",
        "series",
        "quote_currency",
        "created_at",
    ),
    "instrument_identifiers": ("owner_id", "id", "namespace", "value", "qualifier", "created_at"),
    "instrument_mappings": (
        "owner_id",
        "identifier_id",
        "revision",
        "previous_revision",
        "instrument_id",
        "listing_id",
        "reason",
        "created_at",
    ),
    "account_positions": (
        "owner_id",
        "id",
        "account_id",
        "instrument_id",
        "holding_form",
        "created_at",
    ),
}
COLUMNS.update(
    {
        "source_observations": (
            "owner_id",
            "id",
            "source_id",
            "previous_id",
            "digest",
            "digest_algorithm",
            "period_start",
            "period_end",
            "coverage",
            "created_at",
        ),
        "import_batches": (
            "owner_id",
            "id",
            "observation_id",
            "revision",
            "previous_revision",
            "normalizer",
            "normalizer_version",
            "normalized_digest",
            "row_count",
            "contract_version",
            "cash_date_basis",
            "created_at",
        ),
        "staged_rows": (
            "owner_id",
            "id",
            "batch_id",
            "occurrence",
            "kind",
            "instrument_identifier_id",
            "trade_date",
            "settlement_date",
            "booking_date",
            "value_date",
            "as_of_date",
            "acquisition_date",
            "blocked_reason",
            "as_of_instant",
            "snapshot_scope",
            "reconciliation_boundary",
            "posting_state",
            "value_count",
            "created_at",
        ),
        "staged_values": (
            "owner_id",
            "row_id",
            "role",
            "source",
            "amount",
            "currency",
            "missing_reason",
        ),
        "review_decisions": (
            "owner_id",
            "row_id",
            "revision",
            "previous_revision",
            "action",
            "reason",
            "source_id",
            "account_mapping_revision",
            "instrument_identifier_id",
            "instrument_mapping_revision",
            "created_at",
        ),
    }
)
COLUMNS.update(
    {
        "financial_events": (
            "owner_id",
            "id",
            "revision",
            "previous_revision",
            "source_row_id",
            "source_review_revision",
            "account_id",
            "position_id",
            "instrument_id",
            "kind",
            "posting_state",
            "status",
            "correction_reason",
            "trade_date",
            "settlement_date",
            "booking_date",
            "value_date",
            "value_count",
            "created_at",
        ),
        "event_components": (
            "owner_id",
            "event_id",
            "revision",
            "role",
            "source",
            "amount",
            "currency",
            "missing_reason",
        ),
        "quantity_movements": ("owner_id", "event_id", "revision", "position_id", "amount"),
        "cash_movements": ("owner_id", "event_id", "revision", "account_id", "currency", "amount"),
    }
)
COLUMNS.update(
    {
        "lots": ("owner_id", "id", "position_id", "created_at"),
        "lot_observations": (
            "owner_id",
            "id",
            "revision",
            "previous_revision",
            "lot_id",
            "scope",
            "source_row_id",
            "source_review_revision",
            "status",
            "correction_reason",
            "as_of_date",
            "acquisition_date",
            "booking_date",
            "value_count",
            "created_at",
        ),
        "lot_components": (
            "owner_id",
            "observation_id",
            "revision",
            "role",
            "source",
            "amount",
            "currency",
            "missing_reason",
        ),
    }
)
COLUMNS.update(
    {
        "snapshot_records": (
            "owner_id",
            "id",
            "revision",
            "previous_revision",
            "source_row_id",
            "source_review_revision",
            "account_id",
            "position_id",
            "instrument_id",
            "currency",
            "kind",
            "status",
            "correction_reason",
            "as_of_date",
            "as_of_instant",
            "snapshot_scope",
            "booking_date",
            "value_count",
            "created_at",
        ),
        "snapshot_components": (
            "owner_id",
            "snapshot_id",
            "revision",
            "role",
            "source",
            "amount",
            "currency",
            "missing_reason",
        ),
        "snapshot_selections": (
            "owner_id",
            "id",
            "revision",
            "previous_revision",
            "account_id",
            "position_id",
            "currency",
            "snapshot_id",
            "snapshot_revision",
            "reason",
            "created_at",
        ),
    }
)
COLUMNS.update(
    {
        "market_observations": (
            "owner_id",
            "id",
            "previous_id",
            "kind",
            "instrument_id",
            "listing_id",
            "currency",
            "base_currency",
            "quote_currency",
            "basis",
            "adjustment",
            "namespace",
            "digest_algorithm",
            "digest",
            "occurrence",
            "normalizer",
            "normalizer_version",
            "contract_version",
            "observed_on",
            "observed_at",
            "source",
            "amount",
            "missing_reason",
            "created_at",
        ),
        "market_selections": (
            "owner_id",
            "id",
            "revision",
            "previous_revision",
            "kind",
            "instrument_id",
            "listing_id",
            "currency",
            "base_currency",
            "quote_currency",
            "basis",
            "observation_id",
            "reason",
            "created_at",
        ),
    }
)
COLUMNS.update(
    {
        "event_provider_identities": (
            "owner_id",
            "id",
            "source_id",
            "kind",
            "event_id",
            "event_revision",
            "key_version",
            "key_check",
            "fingerprint",
            "encrypted_reference",
            "key_revision",
            "created_at",
            "updated_at",
        ),
        "event_evidence_links": (
            "owner_id",
            "source_row_id",
            "review_revision",
            "identity_id",
            "event_id",
            "event_revision",
            "created_at",
        ),
    }
)
COLUMNS.update(
    {
        "completion_receipts": (
            "owner_id",
            "id",
            "idempotency_key",
            "batch_id",
            "batch_revision",
            "baseline_digest",
            "request_canonical",
            "request_digest",
            "mode",
            "coverage",
            "row_count",
            "selection_count",
            "created_at",
        ),
        "completion_rows": (
            "owner_id",
            "receipt_id",
            "source_row_id",
            "review_revision",
            "operation",
            "outcome",
            "event_id",
            "lot_observation_id",
            "snapshot_id",
            "record_revision",
            "provider_identity_id",
            "selection_id",
            "selection_revision",
        ),
    }
)
COLUMNS.update(
    {
        "completion_scopes": (
            "owner_id",
            "id",
            "receipt_id",
            "kind",
            "account_id",
            "position_id",
            "currency",
            "period_start",
            "period_end",
            "date_basis",
            "rule_version",
            "opening_amount",
            "closing_amount",
            "source_total",
            "combined_total",
            "source_posted_count",
            "source_pending_count",
            "combined_posted_count",
            "combined_pending_count",
            "input_count",
        ),
        "completion_inputs": (
            "owner_id",
            "scope_id",
            "side",
            "part",
            "reference_id",
            "reference_revision",
            "source_row_id",
            "event_id",
            "snapshot_id",
            "source",
            "amount",
            "evidence_date",
            "posting_state",
        ),
    }
)
OMITTED = ("auth_sessions", "auth_admissions")


def source_digest() -> str:
    digest = hashlib.sha256()
    paths = sorted(migrate.MIGRATIONS.rglob("*.py"))
    if not paths:
        raise DatabaseFailure("Recovery requires the committed migration sources.")
    for path in paths:
        digest.update(path.relative_to(migrate.MIGRATIONS).as_posix().encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def target(url: URL, project: str) -> None:
    if url.username != "trading_bootstrap":
        raise DatabaseFailure("Recovery rehearsal requires disposable administrative credentials.")
    require_disposable(url, project)


def schema(connection: Connection) -> None:
    tables = set(
        connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='app'")).scalars()
    )
    if tables != set(COLUMNS) | set(OMITTED):
        raise DatabaseFailure("Recovery format does not cover this schema.")
    if (
        connection.execute(text("SELECT version_num FROM app_meta.alembic_version")).scalar_one()
        != HEAD
    ):
        raise DatabaseFailure("Recovery requires the supported migration revision.")
    for table, columns in COLUMNS.items():
        actual = set(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='app' AND table_name=:table"
                ),
                {"table": table},
            ).scalars()
        )
        if actual != set(columns):
            raise DatabaseFailure("Recovery format does not cover these columns.")
    if connection.execute(
        text(
            "SELECT count(*) FROM pg_class WHERE relnamespace='app'::regnamespace "
            "AND relkind='r' AND (NOT relrowsecurity OR NOT relforcerowsecurity "
            "OR pg_get_userbyid(relowner)<>'trading_migrator')"
        )
    ).scalar_one():
        raise DatabaseFailure("Recovery schema ownership or policies are unsafe.")


def encode(value: Any) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.isoformat()
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, Decimal) and value.is_finite():
        return format(value, "f")
    raise DatabaseFailure("Unsupported recovery value.")


def verify_references(rows: dict[str, list[dict[str, Any]]], keys: ReferenceKeys | None) -> None:
    identities: set[tuple[str, str, str]] = set()
    for row in rows["source_accounts"]:
        if keys is None:
            raise ReferenceUnavailable()
        value = keys.open(row)
        identity = (str(row["owner_id"]), row["namespace"], value)
        if identity in identities:
            raise ReferenceUnavailable()
        identities.add(identity)
    provider_identities: set[tuple[str, str, str, str]] = set()
    for row in rows["event_provider_identities"]:
        if keys is None:
            raise ReferenceUnavailable()
        value = ProviderKeys(keys).open(row)
        provider_identity = (str(row["owner_id"]), str(row["source_id"]), row["kind"], value)
        if provider_identity in provider_identities:
            raise ReferenceUnavailable()
        provider_identities.add(provider_identity)


def export_snapshot(
    url: URL, project: str, key: bytes, *, identifier_keys: ReferenceKeys | None = None
) -> bytes:
    target(url, project)
    engine = engine_for(url, migration=True)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                verify_server(connection, "trading_test", project)
                schema(connection)
                rows = {}
                for table, columns in COLUMNS.items():
                    rows[table] = [
                        dict(row)
                        for row in connection.execute(
                            text(
                                f"SELECT {','.join(columns)} FROM app.{table} LIMIT {MAX_ROWS + 1}"
                            )
                        ).mappings()
                    ]
                    if len(rows[table]) > MAX_ROWS:
                        raise DatabaseFailure("Recovery rehearsal row budget exceeded.")
                verify_references(rows, identifier_keys)
                payload = json.dumps(
                    {
                        "format": FORMAT,
                        "revision": HEAD,
                        "postgres_major": 17,
                        "migration_digest": source_digest(),
                        "application_version": "0.1.0",
                        "rows": rows,
                    },
                    default=encode,
                    allow_nan=False,
                    sort_keys=True,
                ).encode()
                if len(payload) > LIMIT:
                    raise DatabaseFailure("Recovery rehearsal size budget exceeded.")
                return Fernet(key).encrypt(payload)
    except DatabaseFailure:
        raise
    except Exception:
        raise DatabaseFailure("Recovery export failed.") from None
    finally:
        engine.dispose()


def unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def decode_snapshot(encrypted: bytes, key: bytes) -> dict[str, list[dict[str, Any]]]:
    try:
        if not 1 <= len(encrypted) <= LIMIT * 2:
            raise ValueError()
        payload = Fernet(key).decrypt(encrypted)
        if len(payload) > LIMIT:
            raise ValueError()
        data = json.loads(payload, object_pairs_hook=unique_fields)
        if not isinstance(data, dict):
            raise ValueError()
        if set(data) != {
            "format",
            "revision",
            "postgres_major",
            "migration_digest",
            "application_version",
            "rows",
        }:
            raise ValueError()
        if (
            data["format"],
            data["revision"],
            data["postgres_major"],
            data["migration_digest"],
            data["application_version"],
        ) != (FORMAT, HEAD, 17, source_digest(), "0.1.0"):
            raise ValueError()
        if type(data["format"]) is not int or type(data["postgres_major"]) is not int:
            raise ValueError()
        rows = data["rows"]
        if not isinstance(rows, dict) or set(rows) != set(COLUMNS):
            raise ValueError()
        for table, columns in COLUMNS.items():
            if not isinstance(rows[table], list) or len(rows[table]) > MAX_ROWS:
                raise ValueError()
            for row in rows[table]:
                if not isinstance(row, dict) or set(row) != set(columns):
                    raise ValueError()
                if any(type(value) not in (str, int, bool, type(None)) for value in row.values()):
                    raise ValueError()
        return dict(rows)
    except ValueError, TypeError, KeyError, RecursionError, InvalidToken:
        raise DatabaseFailure("Recovery object is invalid or incompatible.") from None


def restore_snapshot(
    url: URL,
    project: str,
    encrypted: bytes,
    key: bytes,
    *,
    identifier_keys: ReferenceKeys | None = None,
) -> dict[str, int]:
    rows = decode_snapshot(encrypted, key)
    verify_references(rows, identifier_keys)
    target(url, project)
    engine = engine_for(url, migration=True)
    try:
        with engine.begin() as connection:
            verify_server(connection, "trading_test", project)
            connection.execute(text("SELECT pg_advisory_xact_lock(714039231)"))
            schema(connection)
            for table in sorted(set(COLUMNS) | set(OMITTED)):
                connection.execute(text(f"LOCK TABLE app.{table} IN ACCESS EXCLUSIVE MODE"))
                if connection.execute(text(f"SELECT count(*) FROM app.{table}")).scalar_one():
                    raise DatabaseFailure("Recovery destination must be empty.")
            for table, columns in COLUMNS.items():
                if rows[table]:
                    connection.execute(
                        text(
                            f"INSERT INTO app.{table} ({','.join(columns)}) "
                            f"VALUES ({','.join(':' + column for column in columns)})"
                        ),
                        rows[table],
                    )
            # No encrypted provider state is exported. Cut off pre-restore admissions too.
            connection.execute(
                text("""
                INSERT INTO app.auth_revocations (owner_id, revoked_before)
                SELECT id, clock_timestamp() FROM app.owners
                ON CONFLICT (owner_id) DO UPDATE SET revoked_before=
                    GREATEST(app.auth_revocations.revoked_before, excluded.revoked_before)
            """)
            )
            counts = {
                table: connection.execute(text(f"SELECT count(*) FROM app.{table}")).scalar_one()
                for table in (*COLUMNS, *OMITTED)
            }
            for table in set(COLUMNS) - {"auth_revocations"}:
                if counts[table] != len(rows[table]):
                    raise DatabaseFailure("Recovery row verification failed.")
            return counts
    except DatabaseFailure:
        raise
    except Exception:
        raise DatabaseFailure("Recovery transaction failed and was rolled back.") from None
    finally:
        engine.dispose()
