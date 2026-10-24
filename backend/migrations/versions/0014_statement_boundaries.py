"""Explicit source period boundaries and cash date basis; no inferred ledger coverage."""

from alembic import op

revision = "0014_statement_boundaries"
down_revision = "0013_event_evidence"
branch_labels = None
depends_on = None

PREVIOUS_CONTRACT = """
        CREATE OR REPLACE FUNCTION app.guard_staging_contract() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE version smallint;
        BEGIN
            IF TG_TABLE_NAME='import_batches' THEN
                IF current_user='trading_runtime' AND NEW.contract_version<>4 THEN
                    RAISE EXCEPTION 'New evidence requires the current contract'; END IF;
            ELSIF TG_TABLE_NAME='staged_rows' THEN
                SELECT contract_version INTO version FROM app.import_batches
                    WHERE owner_id=NEW.owner_id AND id=NEW.batch_id;
                IF (version=1 AND NEW.posting_state IS NOT NULL) OR
                    (version<3 AND (NEW.acquisition_date IS NOT NULL OR NEW.kind='cancellation')) OR
                    (version<4 AND (NEW.as_of_instant IS NOT NULL OR NEW.snapshot_scope IS NOT
                        NULL))
                    THEN RAISE EXCEPTION 'Evidence exceeds its versioned contract'; END IF;
            ELSIF NEW.role='discount_amount' AND EXISTS (
                SELECT 1 FROM app.staged_rows r JOIN app.import_batches b
                    ON b.owner_id=r.owner_id AND b.id=r.batch_id
                WHERE r.owner_id=NEW.owner_id AND r.id=NEW.row_id AND b.contract_version<3)
                THEN RAISE EXCEPTION 'Evidence exceeds its versioned contract';
            END IF;
            RETURN NEW;
        END $f$
"""

PREVIOUS_CONFLICT = """
        CREATE OR REPLACE FUNCTION app.snapshot_conflict(own uuid,record_key uuid,version bigint)
            RETURNS boolean
        LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $f$
        SELECT EXISTS (
            SELECT 1 FROM app.snapshot_records a JOIN app.snapshot_components av ON
                av.owner_id=a.owner_id AND av.snapshot_id=a.id AND av.revision=a.revision
                AND av.role IN ('quantity','net_cash')
            JOIN app.snapshot_records b ON b.owner_id=a.owner_id AND b.account_id=a.account_id AND
                b.position_id IS NOT DISTINCT FROM a.position_id AND b.currency IS NOT DISTINCT
                    FROM a.currency
                AND b.id<>a.id AND b.status='active'
            JOIN app.snapshot_components bv ON bv.owner_id=b.owner_id AND bv.snapshot_id=b.id AND
                bv.revision=b.revision AND bv.role=av.role
            WHERE a.owner_id=own AND a.id=record_key AND a.revision=version AND a.status='active'
                AND NOT EXISTS (SELECT 1 FROM app.snapshot_records n WHERE n.owner_id=b.owner_id AND
                    n.id=b.id AND n.revision>b.revision)
                AND ((a.as_of_instant IS NULL AND b.as_of_instant IS NULL AND
                    a.as_of_date=b.as_of_date) OR
                    (a.as_of_instant IS NOT NULL AND b.as_of_instant IS NOT NULL AND
                        a.as_of_instant::timestamptz=b.as_of_instant::timestamptz))
                AND av.amount IS DISTINCT FROM bv.amount
        ) $f$
"""

CURRENT_CONTRACT = """
        CREATE OR REPLACE FUNCTION app.guard_staging_contract() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE version smallint;
        BEGIN
            IF TG_TABLE_NAME='import_batches' THEN
                IF current_user='trading_runtime' AND NEW.contract_version<>5 THEN
                    RAISE EXCEPTION 'New evidence requires the current contract'; END IF;
                IF NEW.cash_date_basis IS NOT NULL AND (NEW.contract_version<5 OR NOT EXISTS (
                    SELECT 1 FROM app.source_observations WHERE owner_id=NEW.owner_id
                        AND id=NEW.observation_id AND period_start IS NOT NULL
                        AND period_end IS NOT NULL AND coverage IN
                            ('complete_activity','partial_activity'))) THEN
                    RAISE EXCEPTION 'Cash date basis requires a known activity period'; END IF;
            ELSIF TG_TABLE_NAME='staged_rows' THEN
                SELECT contract_version INTO version FROM app.import_batches
                    WHERE owner_id=NEW.owner_id AND id=NEW.batch_id;
                IF (version=1 AND NEW.posting_state IS NOT NULL) OR
                    (version<3 AND (NEW.acquisition_date IS NOT NULL OR NEW.kind='cancellation')) OR
                    (version<4 AND (NEW.as_of_instant IS NOT NULL OR NEW.snapshot_scope IS NOT
                        NULL)) OR
                    (version<5 AND NEW.reconciliation_boundary IS NOT NULL)
                    THEN RAISE EXCEPTION 'Evidence exceeds its versioned contract'; END IF;
            ELSIF NEW.role='discount_amount' AND EXISTS (
                SELECT 1 FROM app.staged_rows r JOIN app.import_batches b
                    ON b.owner_id=r.owner_id AND b.id=r.batch_id
                WHERE r.owner_id=NEW.owner_id AND r.id=NEW.row_id AND b.contract_version<3)
                THEN RAISE EXCEPTION 'Evidence exceeds its versioned contract';
            END IF;
            RETURN NEW;
        END $f$
"""

CURRENT_CONFLICT = """
        CREATE OR REPLACE FUNCTION app.snapshot_conflict(own uuid,record_key uuid,version bigint)
            RETURNS boolean
        LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $f$
        SELECT EXISTS (
            SELECT 1 FROM app.snapshot_records a JOIN app.snapshot_components av ON
                av.owner_id=a.owner_id AND av.snapshot_id=a.id AND av.revision=a.revision
                AND av.role IN ('quantity','net_cash')
            JOIN app.snapshot_records b ON b.owner_id=a.owner_id AND b.account_id=a.account_id AND
                b.position_id IS NOT DISTINCT FROM a.position_id AND b.currency IS NOT DISTINCT
                    FROM a.currency
                AND b.id<>a.id AND b.status='active'
            JOIN app.snapshot_components bv ON bv.owner_id=b.owner_id AND bv.snapshot_id=b.id AND
                bv.revision=b.revision AND bv.role=av.role
            JOIN app.staged_rows ar ON ar.owner_id=a.owner_id AND ar.id=a.source_row_id
            JOIN app.staged_rows br ON br.owner_id=b.owner_id AND br.id=b.source_row_id
            WHERE a.owner_id=own AND a.id=record_key AND a.revision=version AND a.status='active'
                AND NOT EXISTS (SELECT 1 FROM app.snapshot_records n WHERE n.owner_id=b.owner_id AND
                    n.id=b.id AND n.revision>b.revision)
                AND ((a.as_of_instant IS NULL AND b.as_of_instant IS NULL AND
                    a.as_of_date=b.as_of_date AND (ar.reconciliation_boundary IS NULL OR
                        br.reconciliation_boundary IS NULL OR
                        ar.reconciliation_boundary=br.reconciliation_boundary)) OR
                    (a.as_of_instant IS NOT NULL AND b.as_of_instant IS NOT NULL AND
                        a.as_of_instant::timestamptz=b.as_of_instant::timestamptz))
                AND av.amount IS DISTINCT FROM bv.amount
        ) $f$
"""


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.import_batches ADD COLUMN cash_date_basis text,
            ADD CONSTRAINT batch_cash_date_basis CHECK (cash_date_basis IS NULL OR
                cash_date_basis IN ('booking','value','settlement'))
    """)
    op.execute("""
        ALTER TABLE app.staged_rows ADD COLUMN reconciliation_boundary text,
            ADD CONSTRAINT staged_reconciliation_boundary CHECK
                (reconciliation_boundary IS NULL OR
                    (reconciliation_boundary IN ('before_period','after_period') AND
                        as_of_date IS NOT NULL AND snapshot_scope IS NOT NULL AND
                        ((kind='cash_snapshot' AND snapshot_scope='native_cash') OR
                         (kind='position_snapshot' AND snapshot_scope='selected_position'))))
    """)
    op.execute("GRANT INSERT (cash_date_basis) ON app.import_batches TO trading_runtime")
    op.execute("GRANT INSERT (reconciliation_boundary) ON app.staged_rows TO trading_runtime")
    op.execute(
        "ALTER TABLE app.import_batches DROP CONSTRAINT import_batches_contract_version_check"
    )
    op.execute("ALTER TABLE app.import_batches ADD CHECK (contract_version IN (1,2,3,4,5))")
    op.execute("ALTER TABLE app.import_batches ALTER COLUMN contract_version SET DEFAULT 5")
    op.execute(CURRENT_CONTRACT)
    op.execute("""
        CREATE FUNCTION app.check_statement_boundary() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE first_day date; last_day date;
        BEGIN
            IF NEW.reconciliation_boundary IS NULL THEN RETURN NEW; END IF;
            SELECT o.period_start,o.period_end INTO first_day,last_day
                FROM app.import_batches b JOIN app.source_observations o
                    ON o.owner_id=b.owner_id AND o.id=b.observation_id
                WHERE b.owner_id=NEW.owner_id AND b.id=NEW.batch_id;
            IF first_day IS NULL OR last_day IS NULL OR
                (NEW.reconciliation_boundary='before_period' AND
                    NEW.as_of_date IS DISTINCT FROM first_day) OR
                (NEW.reconciliation_boundary='after_period' AND
                    NEW.as_of_date IS DISTINCT FROM last_day) THEN
                RAISE EXCEPTION 'Checkpoint boundary does not match its source period';
            END IF;
            RETURN NEW;
        END $f$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.check_statement_boundary() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER check_statement_boundary BEFORE INSERT ON app.staged_rows "
        "FOR EACH ROW EXECUTE FUNCTION app.check_statement_boundary()"
    )
    op.execute(CURRENT_CONFLICT)


def downgrade() -> None:
    op.execute("""
        DO $f$ BEGIN
            IF EXISTS (SELECT 1 FROM app.import_batches WHERE contract_version=5) OR
                EXISTS (SELECT 1 FROM app.import_batches WHERE cash_date_basis IS NOT NULL) OR
                EXISTS (SELECT 1 FROM app.staged_rows WHERE reconciliation_boundary IS NOT NULL)
                THEN RAISE EXCEPTION 'Statement boundary evidence cannot be downgraded'; END IF;
        END $f$
    """)
    op.execute(PREVIOUS_CONFLICT)
    op.execute(PREVIOUS_CONTRACT)
    op.execute("DROP TRIGGER check_statement_boundary ON app.staged_rows")
    op.execute("DROP FUNCTION app.check_statement_boundary()")
    op.execute("ALTER TABLE app.staged_rows DROP COLUMN reconciliation_boundary")
    op.execute("ALTER TABLE app.import_batches DROP COLUMN cash_date_basis")
    op.execute(
        "ALTER TABLE app.import_batches DROP CONSTRAINT import_batches_contract_version_check"
    )
    op.execute("ALTER TABLE app.import_batches ADD CHECK (contract_version IN (1,2,3,4))")
    op.execute("ALTER TABLE app.import_batches ALTER COLUMN contract_version SET DEFAULT 4")
