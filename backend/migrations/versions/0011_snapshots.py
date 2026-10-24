"""Exact sourced checkpoints, timestamp precision and explicit selection history."""

from alembic import op

revision = "0011_snapshots"
down_revision = "0010_lots_corrections"
branch_labels = None
depends_on = None

TABLES = ("snapshot_records", "snapshot_components", "snapshot_selections")


# Exact prior function body for a legacy-only disposable downgrade.
PREVIOUS_CONTRACT = """
        CREATE OR REPLACE FUNCTION app.guard_staging_contract() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE version smallint;
        BEGIN
            IF TG_TABLE_NAME='import_batches' THEN
                IF current_user='trading_runtime' AND NEW.contract_version<>3 THEN
                    RAISE EXCEPTION 'New evidence requires the current contract'; END IF;
            ELSIF TG_TABLE_NAME='staged_rows' THEN
                SELECT contract_version INTO version FROM app.import_batches
                    WHERE owner_id=NEW.owner_id AND id=NEW.batch_id;
                IF (version=1 AND NEW.posting_state IS NOT NULL) OR
                    (version<3 AND (NEW.acquisition_date IS NOT NULL OR NEW.kind='cancellation'))
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


def upgrade() -> None:
    _staging()
    op.execute("""
        CREATE TABLE app.snapshot_records (
            owner_id uuid NOT NULL, id uuid NOT NULL CHECK
                (id<>'00000000-0000-0000-0000-000000000000'),
            revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
            previous_revision bigint, source_row_id uuid NOT NULL,
            source_review_revision bigint NOT NULL, account_id uuid NOT NULL,
            position_id uuid, instrument_id uuid, currency text,
            kind text NOT NULL CHECK (kind IN ('position_snapshot','cash_snapshot')),
            status text NOT NULL CHECK (status IN ('active','cancelled')),
            correction_reason text CHECK (correction_reason IN
                ('source_correction','cancellation','reinstatement')),
            as_of_date date, as_of_instant text, snapshot_scope text, booking_date date,
            value_count integer NOT NULL,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,id,revision), UNIQUE (owner_id,source_row_id),
            FOREIGN KEY (owner_id,id,previous_revision)
                REFERENCES app.snapshot_records(owner_id,id,revision) DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY (owner_id,source_row_id,source_review_revision)
                REFERENCES app.review_decisions(owner_id,row_id,revision),
            FOREIGN KEY (owner_id,account_id) REFERENCES app.financial_accounts(owner_id,id),
            FOREIGN KEY (owner_id,position_id) REFERENCES app.account_positions(owner_id,id),
            FOREIGN KEY (owner_id,instrument_id) REFERENCES app.instruments(owner_id,id),
            FOREIGN KEY (owner_id,account_id,currency)
                REFERENCES app.account_currencies(owner_id,account_id,currency),
            CHECK ((revision=1 AND previous_revision IS NULL) OR (revision>1 AND
                previous_revision IS NOT NULL AND previous_revision=revision-1)),
            CHECK ((kind='position_snapshot' AND position_id IS NOT NULL AND
                instrument_id IS NOT NULL AND currency IS NULL) OR (kind='cash_snapshot'
                AND position_id IS NULL AND instrument_id IS NULL AND currency IN ('INR','USD')
                AND currency IS NOT NULL)),
            CHECK ((status='active' AND value_count BETWEEN 1 AND 8 AND as_of_date IS NOT NULL)
                OR (status='cancelled' AND value_count=0))
        )
    """)
    op.execute("""
        CREATE TABLE app.snapshot_components (
            owner_id uuid NOT NULL, snapshot_id uuid NOT NULL, revision bigint NOT NULL,
            role text NOT NULL, source text, amount numeric, currency text, missing_reason text,
            PRIMARY KEY (owner_id,snapshot_id,revision,role),
            FOREIGN KEY (owner_id,snapshot_id,revision)
                REFERENCES app.snapshot_records(owner_id,id,revision),
            CHECK (app.valid_staged_value(role,source,amount,currency,missing_reason))
        )
    """)
    op.execute("""
        CREATE TABLE app.snapshot_selections (
            owner_id uuid NOT NULL, id uuid NOT NULL CHECK
                (id<>'00000000-0000-0000-0000-000000000000'),
            revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
            previous_revision bigint, account_id uuid NOT NULL, position_id uuid, currency text,
            snapshot_id uuid, snapshot_revision bigint,
            reason text NOT NULL CHECK (reason IN
                ('reviewed','newer_evidence','correction','clear')),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,id,revision),
            UNIQUE NULLS NOT DISTINCT (owner_id,account_id,position_id,currency,revision),
            FOREIGN KEY (owner_id,id,previous_revision)
                REFERENCES app.snapshot_selections(owner_id,id,revision) DEFERRABLE INITIALLY
                    DEFERRED,
            FOREIGN KEY (owner_id,snapshot_id,snapshot_revision)
                REFERENCES app.snapshot_records(owner_id,id,revision) DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY (owner_id,account_id) REFERENCES app.financial_accounts(owner_id,id),
            FOREIGN KEY (owner_id,position_id) REFERENCES app.account_positions(owner_id,id),
            FOREIGN KEY (owner_id,account_id,currency)
                REFERENCES app.account_currencies(owner_id,account_id,currency),
            CHECK ((revision=1 AND previous_revision IS NULL AND snapshot_id IS NOT NULL) OR
                (revision>1 AND previous_revision IS NOT NULL AND previous_revision=revision-1)),
            CHECK ((position_id IS NOT NULL AND currency IS NULL) OR
                (position_id IS NULL AND currency IS NOT NULL AND currency IN ('INR','USD'))),
            CHECK ((snapshot_id IS NULL AND snapshot_revision IS NULL AND reason='clear') OR
                (snapshot_id IS NOT NULL AND snapshot_revision IS NOT NULL AND reason<>'clear'))
        )
    """)
    op.execute(
        "CREATE INDEX snapshot_records_account ON app.snapshot_records(owner_id,account_id,"
        "id,revision)"
    )
    op.execute(
        "CREATE INDEX snapshot_records_point ON app.snapshot_records(owner_id,position_id,"
        "currency,as_of_date)"
    )
    op.execute(
        "CREATE INDEX snapshot_selections_account ON app.snapshot_selections(owner_id,"
        "account_id,id,revision)"
    )
    _records()
    _selections()
    _consumption()
    _privileges()


def _staging() -> None:
    op.execute("""
        CREATE FUNCTION app.valid_snapshot_instant(source text,day date) RETURNS boolean
        LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE ending text; point timestamptz;
        BEGIN
            IF source IS NULL THEN RETURN true; END IF;
            IF day IS NULL OR length(source) NOT BETWEEN 20 AND 32 OR source !~
                '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})$'
                THEN RETURN false; END IF;
            IF substring(source,12,2)::int>23 OR substring(source,15,2)::int>59 OR
                substring(source,18,2)::int>59 OR left(source,10)::date<>day THEN
                RETURN false; END IF;
            IF right(source,1)<>'Z' THEN
                ending:=right(source,6);
                IF ending='-00:00' OR substring(ending,2,2)::int>14 OR
                    substring(ending,5,2)::int>59 OR
                    (substring(ending,2,2)::int=14 AND substring(ending,5,2)::int<>0)
                    THEN RETURN false; END IF;
            END IF;
            point:=source::timestamptz;
            RETURN (point AT TIME ZONE 'UTC')::date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31';
        EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow THEN RETURN false;
        END $f$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.valid_snapshot_instant(text,date) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.valid_snapshot_instant(text,date) TO trading_runtime")
    op.execute("""
        ALTER TABLE app.staged_rows ADD COLUMN as_of_instant text,
            ADD COLUMN snapshot_scope text,
            ADD CONSTRAINT staged_snapshot_instant CHECK
                (app.valid_snapshot_instant(as_of_instant,as_of_date)
                AND (as_of_instant IS NULL OR kind IN ('position_snapshot','cash_snapshot'))),
            ADD CONSTRAINT staged_snapshot_scope CHECK (snapshot_scope IS NULL OR
                (kind='position_snapshot' AND snapshot_scope IN
                    ('selected_position','full_account')) OR
                (kind='cash_snapshot' AND snapshot_scope IN ('native_cash','full_account')))
    """)
    op.execute("GRANT INSERT (as_of_instant,snapshot_scope) ON app.staged_rows TO trading_runtime")
    op.execute(
        "ALTER TABLE app.import_batches DROP CONSTRAINT import_batches_contract_version_check"
    )
    op.execute("ALTER TABLE app.import_batches ADD CHECK (contract_version IN (1,2,3,4))")
    op.execute("ALTER TABLE app.import_batches ALTER COLUMN contract_version SET DEFAULT 4")
    op.execute("""
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
    """)


def _records() -> None:
    op.execute("""
        CREATE FUNCTION app.check_snapshot_record() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE record_key uuid; e record; s record; prior record; native text;
        BEGIN
            IF TG_TABLE_NAME='snapshot_records' THEN record_key:=NEW.id;
            ELSE record_key:=NEW.snapshot_id; END IF;
            SELECT * INTO e FROM app.snapshot_records WHERE owner_id=NEW.owner_id AND
                id=record_key AND revision=NEW.revision;
            SELECT * INTO s FROM app.staged_rows WHERE owner_id=e.owner_id AND id=e.source_row_id;
            IF e.id IS NULL THEN RAISE EXCEPTION 'Snapshot is unavailable'; END IF;
            PERFORM app.check_record_review(e.owner_id,e.source_row_id,e.source_review_revision,
                e.account_id,e.instrument_id,e.status='cancelled');
            IF (e.position_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM app.account_positions
                WHERE owner_id=e.owner_id AND id=e.position_id AND account_id=e.account_id AND
                instrument_id=e.instrument_id)) OR
                s.as_of_date IS DISTINCT FROM e.as_of_date OR
                s.as_of_instant IS DISTINCT FROM e.as_of_instant OR
                s.snapshot_scope IS DISTINCT FROM e.snapshot_scope OR
                s.booking_date IS DISTINCT FROM e.booking_date OR s.value_count<>e.value_count OR
                (e.status='cancelled' AND s.kind<>'cancellation') OR
                (e.status='active' AND s.kind<>e.kind) OR
                (SELECT count(*) FROM app.snapshot_components WHERE owner_id=e.owner_id AND
                    snapshot_id=e.id AND revision=e.revision)<>e.value_count OR EXISTS (
                    SELECT role,source,amount,currency,missing_reason FROM app.staged_values
                        WHERE owner_id=e.owner_id AND row_id=e.source_row_id
                    EXCEPT SELECT role,source,amount,currency,missing_reason FROM
                        app.snapshot_components
                        WHERE owner_id=e.owner_id AND snapshot_id=e.id AND revision=e.revision) THEN
                RAISE EXCEPTION 'Snapshot evidence is inconsistent'; END IF;
            IF e.status='active' THEN
                IF (e.kind='cash_snapshot' AND NOT EXISTS (SELECT 1 FROM app.snapshot_components
                    WHERE owner_id=e.owner_id AND snapshot_id=e.id AND revision=e.revision AND
                    role='net_cash' AND amount IS NOT NULL AND currency=e.currency)) OR
                    (e.kind='position_snapshot' AND NOT EXISTS (SELECT 1 FROM
                        app.snapshot_components
                    WHERE owner_id=e.owner_id AND snapshot_id=e.id AND revision=e.revision AND
                    role='quantity' AND amount>=0)) THEN
                    RAISE EXCEPTION 'Snapshot value is unavailable'; END IF;
                SELECT coalesce(l.quote_currency,i.fund_currency) INTO native
                    FROM app.review_decisions d JOIN app.instrument_mappings m ON
                        m.owner_id=d.owner_id
                        AND m.identifier_id=d.instrument_identifier_id AND
                            m.revision=d.instrument_mapping_revision
                    JOIN app.instruments i ON i.owner_id=m.owner_id AND i.id=m.instrument_id
                    LEFT JOIN app.instrument_listings l ON l.owner_id=m.owner_id AND
                        l.id=m.listing_id
                    WHERE d.owner_id=e.owner_id AND d.row_id=e.source_row_id AND
                        d.revision=e.source_review_revision;
                IF native IS NOT NULL AND EXISTS (SELECT 1 FROM app.snapshot_components WHERE
                    owner_id=e.owner_id AND snapshot_id=e.id AND revision=e.revision AND
                    role='unit_price' AND currency<>native) THEN
                    RAISE EXCEPTION 'Snapshot price currency is inconsistent'; END IF;
            END IF;
            IF e.revision=1 THEN
                IF e.status<>'active' OR e.correction_reason IS NOT NULL THEN
                    RAISE EXCEPTION 'Initial snapshot cannot be a correction'; END IF;
            ELSE
                SELECT * INTO prior FROM app.snapshot_records WHERE owner_id=e.owner_id AND
                    id=e.id AND revision=e.previous_revision;
                IF NOT FOUND OR e.account_id<>prior.account_id OR
                    e.position_id IS DISTINCT FROM prior.position_id OR
                    e.instrument_id IS DISTINCT FROM prior.instrument_id OR
                    e.currency IS DISTINCT FROM prior.currency OR e.kind<>prior.kind THEN
                    RAISE EXCEPTION 'Snapshot correction identity is inconsistent'; END IF;
                IF e.correction_reason IS NULL OR NOT (
                    (e.status='cancelled' AND prior.status='active' AND
                        e.correction_reason='cancellation') OR
                    (e.status='active' AND prior.status='cancelled' AND
                        e.correction_reason='reinstatement') OR
                    (e.status='active' AND prior.status='active' AND
                        e.correction_reason='source_correction')) THEN
                    RAISE EXCEPTION 'Snapshot correction transition is inconsistent'; END IF;
            END IF;
            RETURN NULL;
        END $f$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.check_snapshot_record() FROM PUBLIC")
    for table in ("snapshot_records", "snapshot_components"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER check_snapshot_record AFTER INSERT ON app.{table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
            "app.check_snapshot_record()"
        )


def _selections() -> None:
    op.execute("""
        CREATE FUNCTION app.snapshot_conflict(own uuid,record_key uuid,version bigint) RETURNS
            boolean
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
    """)
    op.execute("REVOKE ALL ON FUNCTION app.snapshot_conflict(uuid,uuid,bigint) FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.snapshot_conflict(uuid,uuid,bigint) TO trading_runtime"
    )
    op.execute("""
        CREATE FUNCTION app.check_snapshot_selection() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE prior record; snapshot record;
        BEGIN
            IF NEW.revision>1 THEN
                SELECT * INTO prior FROM app.snapshot_selections WHERE owner_id=NEW.owner_id AND
                    id=NEW.id AND revision=NEW.previous_revision;
                IF NOT FOUND OR prior.account_id<>NEW.account_id OR
                    prior.position_id IS DISTINCT FROM NEW.position_id OR
                    prior.currency IS DISTINCT FROM NEW.currency THEN
                    RAISE EXCEPTION 'Selection identity is inconsistent'; END IF;
            END IF;
            IF NEW.position_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM app.account_positions
                WHERE owner_id=NEW.owner_id AND id=NEW.position_id AND
                    account_id=NEW.account_id) THEN
                RAISE EXCEPTION 'Selection position is unavailable'; END IF;
            IF current_user='trading_runtime' AND NOT EXISTS (SELECT 1 FROM app.financial_accounts
                WHERE owner_id=NEW.owner_id AND id=NEW.account_id AND archived_at IS NULL) THEN
                RAISE EXCEPTION 'Selection account is unavailable'; END IF;
            IF NEW.snapshot_id IS NOT NULL THEN
                SELECT * INTO snapshot FROM app.snapshot_records WHERE owner_id=NEW.owner_id AND
                    id=NEW.snapshot_id AND revision=NEW.snapshot_revision;
                IF NOT FOUND OR snapshot.account_id<>NEW.account_id OR
                    snapshot.position_id IS DISTINCT FROM NEW.position_id OR
                    snapshot.currency IS DISTINCT FROM NEW.currency OR
                        snapshot.status<>'active' THEN
                    RAISE EXCEPTION 'Selected snapshot is inconsistent'; END IF;
                IF current_user='trading_runtime' THEN
                    PERFORM app.check_record_review(snapshot.owner_id,snapshot.source_row_id,
                        snapshot.source_review_revision,snapshot.account_id,
                        snapshot.instrument_id,false);
                    IF EXISTS (SELECT 1 FROM app.snapshot_records WHERE owner_id=NEW.owner_id AND
                        id=NEW.snapshot_id AND revision>NEW.snapshot_revision) OR
                        app.snapshot_conflict(NEW.owner_id,NEW.snapshot_id,
                            NEW.snapshot_revision) THEN
                        RAISE EXCEPTION 'Selected evidence is stale or conflicting'; END IF;
                END IF;
            END IF;
            RETURN NULL;
        END $f$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.check_snapshot_selection() FROM PUBLIC")
    op.execute(
        "CREATE CONSTRAINT TRIGGER check_snapshot_selection AFTER INSERT ON "
        "app.snapshot_selections DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
        "app.check_snapshot_selection()"
    )


def _consumption() -> None:
    op.execute("""
        CREATE FUNCTION app.check_snapshot_consumption() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        BEGIN
            IF (SELECT count(*) FROM (
                SELECT source_row_id FROM app.financial_events WHERE owner_id=NEW.owner_id AND
                    source_row_id=NEW.source_row_id
                UNION ALL SELECT source_row_id FROM app.lot_observations WHERE
                    owner_id=NEW.owner_id AND source_row_id=NEW.source_row_id
                UNION ALL SELECT source_row_id FROM app.snapshot_records WHERE
                    owner_id=NEW.owner_id AND source_row_id=NEW.source_row_id
                ) used)>1 THEN RAISE EXCEPTION 'Source occurrence is already consumed'; END IF;
            RETURN NULL;
        END $f$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.check_snapshot_consumption() FROM PUBLIC")
    for table in ("financial_events", "lot_observations", "snapshot_records"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER check_snapshot_consumption AFTER INSERT ON app.{table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
            "app.check_snapshot_consumption()"
        )
    op.execute("""
        CREATE FUNCTION app.guard_snapshot_review() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        BEGIN
            IF current_user='trading_runtime' AND EXISTS (SELECT 1 FROM app.snapshot_records
                WHERE owner_id=NEW.owner_id AND source_row_id=NEW.row_id) THEN
                RAISE EXCEPTION 'Recorded snapshot review is immutable'; END IF;
            RETURN NEW;
        END $f$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.guard_snapshot_review() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER guard_snapshot_review BEFORE INSERT ON app.review_decisions FOR EACH "
        "ROW EXECUTE FUNCTION app.guard_snapshot_review()"
    )


def _privileges() -> None:
    columns = {
        "snapshot_records": (
            "owner_id,id,revision,previous_revision,source_row_id,source_review_revision,"
            "account_id,position_id,instrument_id,currency,kind,status,correction_reason,"
            "as_of_date,as_of_instant,snapshot_scope,booking_date,value_count"
        ),
        "snapshot_components": (
            "owner_id,snapshot_id,revision,role,source,amount,currency,missing_reason"
        ),
        "snapshot_selections": (
            "owner_id,id,revision,previous_revision,account_id,position_id,currency,"
            "snapshot_id,snapshot_revision,reason"
        ),
    }
    for table in TABLES:
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC,trading_runtime,trading_auth")
        op.execute(f"""
            CREATE POLICY snapshot_owner ON app.{table} TO trading_runtime
            USING (owner_id=app.current_owner_id() AND EXISTS (SELECT 1 FROM app.owners
                WHERE id=app.current_owner_id() AND is_active))
            WITH CHECK (owner_id=app.current_owner_id() AND EXISTS (SELECT 1 FROM app.owners
                WHERE id=app.current_owner_id() AND is_active))
        """)
        op.execute(f"GRANT SELECT,INSERT ({columns[table]}) ON app.{table} TO trading_runtime")
        op.execute(
            f"CREATE TRIGGER a_serialize_financial_write BEFORE INSERT ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.serialize_financial_write()"
        )


def downgrade() -> None:
    # The migration runner confines destructive downgrades to disposable clusters.
    op.execute("""
        DO $f$ BEGIN
            IF EXISTS (SELECT 1 FROM app.import_batches WHERE contract_version=4) OR
                EXISTS (SELECT 1 FROM app.snapshot_records) OR
                EXISTS (SELECT 1 FROM app.snapshot_selections) THEN
                RAISE EXCEPTION 'Snapshot evidence cannot be downgraded'; END IF;
        END $f$
    """)
    for table in ("financial_events", "lot_observations"):
        op.execute(f"DROP TRIGGER check_snapshot_consumption ON app.{table}")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE app.{table}")
    op.execute("DROP TRIGGER guard_snapshot_review ON app.review_decisions")
    for function in (
        "guard_snapshot_review()",
        "check_snapshot_consumption()",
        "check_snapshot_selection()",
        "snapshot_conflict(uuid,uuid,bigint)",
        "check_snapshot_record()",
    ):
        op.execute(f"DROP FUNCTION app.{function}")
    op.execute(PREVIOUS_CONTRACT)
    op.execute("ALTER TABLE app.staged_rows DROP COLUMN as_of_instant, DROP COLUMN snapshot_scope")
    op.execute("DROP FUNCTION app.valid_snapshot_instant(text,date)")
    op.execute(
        "ALTER TABLE app.import_batches DROP CONSTRAINT import_batches_contract_version_check"
    )
    op.execute("ALTER TABLE app.import_batches ADD CHECK (contract_version IN (1,2,3))")
    op.execute("ALTER TABLE app.import_batches ALTER COLUMN contract_version SET DEFAULT 3")
