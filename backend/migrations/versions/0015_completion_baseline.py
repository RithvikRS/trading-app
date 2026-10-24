"""Bounded owner-state tokens under the common financial transaction lock."""

from alembic import op

revision = "0015_completion_baseline"
down_revision = "0014_statement_boundaries"
branch_labels = None
depends_on = None

# Committed identifiers only. Immutable children are covered by their constrained
# parent revision; source custody revisions and market data do not change ledgers.
BASELINE = {
    "financial_accounts": ("id", "revision"),
    "account_currencies": ("account_id", "currency"),
    "source_accounts": ("id",),
    "source_account_mappings": ("source_id", "revision"),
    "fund_schemes": ("id",),
    "instruments": ("id",),
    "instrument_listings": ("id",),
    "instrument_identifiers": ("id",),
    "instrument_mappings": ("identifier_id", "revision"),
    "account_positions": ("id",),
    "source_observations": ("id",),
    "import_batches": ("id", "revision"),
    "staged_rows": ("id",),
    "review_decisions": ("row_id", "revision"),
    "financial_events": ("id", "revision"),
    "lots": ("id",),
    "lot_observations": ("id", "revision"),
    "snapshot_records": ("id", "revision"),
    "snapshot_selections": ("id", "revision"),
    "event_provider_identities": ("id",),
    "event_evidence_links": ("source_row_id",),
}
ADDITIONAL_LOCKS = (
    "account_currencies",
    "source_accounts",
    "fund_schemes",
    "instruments",
    "instrument_listings",
    "instrument_identifiers",
    "account_positions",
    "staged_rows",
)


def upgrade() -> None:
    queries = []
    for table, columns in BASELINE.items():
        fields = ",".join(columns)
        queries.append(f"""
            SELECT count(*), COALESCE(jsonb_agg(jsonb_build_array({fields}) ORDER BY {fields}),
                '[]'::jsonb) INTO total, entries FROM (
                SELECT {fields} FROM app.{table} WHERE owner_id=own ORDER BY {fields} LIMIT 1001
            ) bounded;
            IF total>1000 THEN RAISE EXCEPTION 'Financial baseline exceeds its bounded scope';
                END IF;
            manifest := manifest || jsonb_build_object('{table}', entries);
        """)
    op.execute(
        """
        CREATE FUNCTION app.financial_baseline() RETURNS text
        LANGUAGE plpgsql VOLATILE SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE own uuid; lock_key bigint; total bigint; entries jsonb; manifest jsonb;
        BEGIN
            IF current_user<>'trading_runtime' OR
                current_setting('transaction_isolation')<>'read committed' THEN
                RAISE EXCEPTION 'Financial baseline context is unavailable'; END IF;
            own := app.current_owner_id();
            IF own IS NULL OR own='00000000-0000-0000-0000-000000000000' THEN
                RAISE EXCEPTION 'Financial baseline context is unavailable'; END IF;
            lock_key := ('x'||substr(encode(sha256(convert_to('accounts/v1','UTF8')||
                uuid_send(own)), 'hex'),1,16))::bit(64)::bigint;
            PERFORM pg_advisory_xact_lock(lock_key);
            -- VOLATILE reads take fresh snapshots after a contended lock; STABLE
            -- would keep the caller statement's snapshot from before the wait.
            IF NOT EXISTS (SELECT 1 FROM app.owners WHERE id=own AND is_active) THEN
                RAISE EXCEPTION 'Financial baseline context is unavailable'; END IF;
            manifest := jsonb_build_object('baseline_contract',1,'owner',own);
        """
        + "".join(queries)
        + """
            RETURN encode(sha256(convert_to(manifest::text,'UTF8')),'hex');
        END $f$
    """
    )
    op.execute("REVOKE ALL ON FUNCTION app.financial_baseline() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.financial_baseline() TO trading_runtime")
    for table in ADDITIONAL_LOCKS:
        op.execute(
            f"CREATE TRIGGER a_serialize_financial_write BEFORE INSERT ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.serialize_financial_write()"
        )


def downgrade() -> None:
    for table in ADDITIONAL_LOCKS:
        op.execute(f"DROP TRIGGER a_serialize_financial_write ON app.{table}")
    op.execute("DROP FUNCTION app.financial_baseline()")
