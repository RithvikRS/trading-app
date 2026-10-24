"""Exact source-linked events and distinct native cash/quantity movements."""

from alembic import op

revision = "0009_financial_events"
down_revision = "0008_import_staging"
branch_labels = None
depends_on = None

TABLES = ("financial_events", "event_components", "quantity_movements", "cash_movements")
SERIALIZED = (
    "financial_accounts",
    "source_account_mappings",
    "instrument_mappings",
    "source_observations",
    "import_batches",
    "review_decisions",
    "financial_events",
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE app.import_batches ADD COLUMN contract_version smallint NOT NULL "
        "DEFAULT 1 CHECK (contract_version IN (1,2))"
    )
    op.execute("ALTER TABLE app.import_batches ALTER COLUMN contract_version SET DEFAULT 2")
    op.execute(
        "ALTER TABLE app.staged_rows ADD COLUMN posting_state text CHECK "
        "(posting_state IS NULL OR (posting_state IN ('posted','pending') AND kind NOT IN "
        "('position_snapshot','cash_snapshot','lot_acquisition','lot_remaining')))"
    )
    op.execute("GRANT INSERT (contract_version) ON app.import_batches TO trading_runtime")
    op.execute("GRANT INSERT (posting_state) ON app.staged_rows TO trading_runtime")
    op.execute("""
        CREATE FUNCTION app.guard_staging_contract() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        BEGIN
            IF TG_TABLE_NAME='import_batches' THEN
                IF current_user='trading_runtime' AND NEW.contract_version<>2 THEN
                    RAISE EXCEPTION 'New evidence requires the current contract';
                END IF;
            ELSIF NEW.posting_state IS NOT NULL AND EXISTS (
                SELECT 1 FROM app.import_batches WHERE owner_id=NEW.owner_id
                    AND id=NEW.batch_id AND contract_version=1) THEN
                RAISE EXCEPTION 'Legacy evidence cannot contain posting state';
            END IF;
            RETURN NEW;
        END $f$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.guard_staging_contract() FROM PUBLIC")
    for table in ("import_batches", "staged_rows"):
        op.execute(
            f"CREATE TRIGGER guard_staging_contract BEFORE INSERT ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.guard_staging_contract()"
        )
    op.execute(
        "ALTER TABLE app.account_positions ADD CONSTRAINT position_event_context "
        "UNIQUE (owner_id,id,account_id,instrument_id)"
    )
    op.execute("""
        CREATE TABLE app.financial_events (
            owner_id uuid NOT NULL, id uuid NOT NULL CHECK
                (id<>'00000000-0000-0000-0000-000000000000'),
            revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
            previous_revision bigint,
            source_row_id uuid NOT NULL, source_review_revision bigint NOT NULL,
            account_id uuid NOT NULL, position_id uuid, instrument_id uuid,
            kind text NOT NULL CHECK (kind IN ('buy','sell','subscription','redemption',
                'dividend','fee','withholding','cash_movement')),
            posting_state text NOT NULL CHECK (posting_state IN ('posted','pending')),
            trade_date date, settlement_date date, booking_date date, value_date date,
            value_count integer NOT NULL CHECK (value_count BETWEEN 1 AND 8),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,id,revision), UNIQUE (owner_id,source_row_id),
            FOREIGN KEY (owner_id,id,previous_revision)
                REFERENCES app.financial_events(owner_id,id,revision)
                DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY (owner_id,source_row_id,source_review_revision)
                REFERENCES app.review_decisions(owner_id,row_id,revision),
            FOREIGN KEY (owner_id,account_id) REFERENCES app.financial_accounts(owner_id,id),
            FOREIGN KEY (owner_id,position_id,account_id,instrument_id)
                REFERENCES app.account_positions(owner_id,id,account_id,instrument_id),
            CHECK ((position_id IS NULL)=(instrument_id IS NULL)),
            CHECK (kind NOT IN ('buy','sell','subscription','redemption','dividend')
                OR position_id IS NOT NULL),
            CHECK ((revision=1 AND previous_revision IS NULL) OR
                (revision>1 AND previous_revision IS NOT NULL AND previous_revision=revision-1))
        )
    """)
    op.execute(
        "CREATE INDEX financial_event_account ON app.financial_events "
        "(owner_id,account_id,id,revision)"
    )
    op.execute(
        "CREATE INDEX financial_event_position ON app.financial_events "
        "(owner_id,position_id,id,revision)"
    )
    op.execute("""
        CREATE TABLE app.event_components (
            owner_id uuid NOT NULL, event_id uuid NOT NULL, revision bigint NOT NULL,
            role text NOT NULL, source text, amount numeric, currency text, missing_reason text,
            PRIMARY KEY (owner_id,event_id,revision,role),
            FOREIGN KEY (owner_id,event_id,revision)
                REFERENCES app.financial_events(owner_id,id,revision),
            CHECK (app.valid_staged_value(role,source,amount,currency,missing_reason))
        )
    """)
    for table, parent, digits in (
        ("quantity_movements", "position", 12),
        ("cash_movements", "account", 2),
    ):
        currency = (
            "currency text NOT NULL CHECK (currency IN ('INR','USD'))," if digits == 2 else ""
        )
        target = "account_positions" if parent == "position" else "financial_accounts"
        op.execute(f"""
            CREATE TABLE app.{table} (
                owner_id uuid NOT NULL, event_id uuid NOT NULL, revision bigint NOT NULL,
                {parent}_id uuid NOT NULL, {currency}
                amount numeric NOT NULL CHECK (amount<>'NaN'::numeric AND
                    abs(amount)<1000000000000000000::numeric AND scale(amount)<={digits}),
                PRIMARY KEY (owner_id,event_id,revision),
                FOREIGN KEY (owner_id,event_id,revision)
                    REFERENCES app.financial_events(owner_id,id,revision),
                FOREIGN KEY (owner_id,{parent}_id) REFERENCES app.{target}(owner_id,id)
            )
        """)
        op.execute(
            f"CREATE INDEX {table}_parent ON app.{table} (owner_id,{parent}_id,event_id,revision)"
        )
    op.execute("""
        CREATE FUNCTION app.guard_event_review() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        BEGIN
            IF current_user='trading_runtime' THEN
                IF EXISTS (SELECT 1 FROM app.financial_events
                    WHERE owner_id=NEW.owner_id AND source_row_id=NEW.row_id) THEN
                    RAISE EXCEPTION 'Financial evidence requires a correction';
                END IF;
                IF NEW.action='include' AND EXISTS (SELECT 1 FROM app.staged_rows
                    WHERE owner_id=NEW.owner_id AND id=NEW.row_id AND kind IN
                        ('buy','sell','subscription','redemption','dividend','fee',
                         'withholding','cash_movement') AND posting_state IS NULL) THEN
                    RAISE EXCEPTION 'Posting evidence is unavailable';
                END IF;
            END IF;
            RETURN NEW;
        END $f$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.guard_event_review() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER guard_event_review BEFORE INSERT ON app.review_decisions "
        "FOR EACH ROW EXECUTE FUNCTION app.guard_event_review()"
    )
    op.execute("""
        CREATE FUNCTION app.check_financial_event() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE e record; s record; d record; cash record; qty record;
                event uuid; account uuid; instrument uuid; native text;
        BEGIN
            IF TG_TABLE_NAME='financial_events' THEN event:=NEW.id;
            ELSE event:=NEW.event_id; END IF;
            SELECT * INTO e FROM app.financial_events WHERE owner_id=NEW.owner_id
                AND id=event AND revision=NEW.revision;
            IF NOT FOUND THEN RAISE EXCEPTION 'Event is unavailable'; END IF;
            SELECT r.*, b.observation_id,b.revision AS batch_revision,o.source_id INTO s
                FROM app.staged_rows r JOIN app.import_batches b ON b.owner_id=r.owner_id
                    AND b.id=r.batch_id JOIN app.source_observations o ON
                    o.owner_id=b.owner_id AND o.id=b.observation_id
                WHERE r.owner_id=e.owner_id AND r.id=e.source_row_id;
            SELECT * INTO d FROM app.review_decisions WHERE owner_id=e.owner_id
                AND row_id=e.source_row_id AND revision=e.source_review_revision;
            IF d.action IS DISTINCT FROM 'include' OR s.kind IS DISTINCT FROM e.kind
                OR s.posting_state IS DISTINCT FROM e.posting_state
                OR s.trade_date IS DISTINCT FROM e.trade_date
                OR s.settlement_date IS DISTINCT FROM e.settlement_date
                OR s.booking_date IS DISTINCT FROM e.booking_date
                OR s.value_date IS DISTINCT FROM e.value_date
                OR s.value_count IS DISTINCT FROM e.value_count
                OR app.import_row_issue(e.owner_id,e.source_row_id) IS NOT NULL THEN
                RAISE EXCEPTION 'Event evidence is inconsistent';
            END IF;
            SELECT account_id INTO account FROM app.source_account_mappings
                WHERE owner_id=e.owner_id AND source_id=d.source_id
                    AND revision=d.account_mapping_revision;
            SELECT m.instrument_id,coalesce(l.quote_currency,i.fund_currency)
                INTO instrument,native FROM app.instrument_mappings m
                JOIN app.instruments i ON i.owner_id=m.owner_id AND i.id=m.instrument_id
                LEFT JOIN app.instrument_listings l ON l.owner_id=m.owner_id AND l.id=m.listing_id
                WHERE m.owner_id=e.owner_id AND m.identifier_id=d.instrument_identifier_id
                    AND m.revision=d.instrument_mapping_revision;
            IF account IS DISTINCT FROM e.account_id OR instrument IS DISTINCT FROM
                e.instrument_id THEN RAISE EXCEPTION 'Event mapping is inconsistent'; END IF;
            IF current_user='trading_runtime' AND (
                e.revision<>1 OR EXISTS (SELECT 1 FROM app.review_decisions
                    WHERE owner_id=e.owner_id AND row_id=e.source_row_id
                        AND revision>e.source_review_revision)
                OR EXISTS (SELECT 1 FROM app.import_batches WHERE owner_id=e.owner_id
                    AND observation_id=s.observation_id AND revision>s.batch_revision)
                OR EXISTS (SELECT 1 FROM app.source_observations WHERE owner_id=e.owner_id
                    AND previous_id=s.observation_id)
                OR EXISTS (SELECT 1 FROM app.source_account_mappings WHERE owner_id=e.owner_id
                    AND source_id=d.source_id AND revision>d.account_mapping_revision)
                OR EXISTS (SELECT 1 FROM app.instrument_mappings WHERE owner_id=e.owner_id
                    AND identifier_id=d.instrument_identifier_id
                    AND revision>d.instrument_mapping_revision)
                OR NOT EXISTS (SELECT 1 FROM app.financial_accounts WHERE owner_id=e.owner_id
                    AND id=e.account_id AND archived_at IS NULL)) THEN
                RAISE EXCEPTION 'Event review context is stale';
            END IF;
            IF (SELECT count(*) FROM app.event_components WHERE owner_id=e.owner_id
                AND event_id=e.id AND revision=e.revision)<>e.value_count OR EXISTS (
                SELECT role,source,amount,currency,missing_reason FROM app.staged_values
                    WHERE owner_id=e.owner_id AND row_id=e.source_row_id
                EXCEPT SELECT role,source,amount,currency,missing_reason FROM app.event_components
                    WHERE owner_id=e.owner_id AND event_id=e.id AND revision=e.revision) THEN
                RAISE EXCEPTION 'Event components are incomplete';
            END IF;
            SELECT * INTO cash FROM app.event_components WHERE owner_id=e.owner_id
                AND event_id=e.id AND revision=e.revision AND role='net_cash';
            IF cash.amount IS NULL OR (native IS NOT NULL AND native<>cash.currency)
                OR EXISTS (SELECT 1 FROM app.event_components WHERE owner_id=e.owner_id
                    AND event_id=e.id AND revision=e.revision AND currency<>cash.currency)
                OR NOT EXISTS (SELECT 1 FROM app.cash_movements WHERE owner_id=e.owner_id
                    AND event_id=e.id AND revision=e.revision AND account_id=e.account_id
                    AND currency=cash.currency AND amount=cash.amount) THEN
                RAISE EXCEPTION 'Native cash movement is inconsistent';
            END IF;
            IF e.kind IN ('buy','sell','subscription','redemption') THEN
                SELECT * INTO qty FROM app.event_components WHERE owner_id=e.owner_id
                    AND event_id=e.id AND revision=e.revision AND role='quantity';
                IF qty.amount IS NULL OR NOT EXISTS (SELECT 1 FROM app.quantity_movements
                    WHERE owner_id=e.owner_id AND event_id=e.id AND revision=e.revision
                        AND position_id=e.position_id AND amount=qty.amount) THEN
                    RAISE EXCEPTION 'Quantity movement is inconsistent';
                END IF;
            ELSIF EXISTS (SELECT 1 FROM app.quantity_movements WHERE owner_id=e.owner_id
                AND event_id=e.id AND revision=e.revision) THEN
                RAISE EXCEPTION 'Unexpected quantity movement';
            END IF;
            RETURN NULL;
        END $f$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.check_financial_event() FROM PUBLIC")
    columns = {
        "financial_events": "owner_id,id,revision,previous_revision,source_row_id,"
        "source_review_revision,account_id,position_id,instrument_id,kind,posting_state,"
        "trade_date,settlement_date,booking_date,value_date,value_count",
        "event_components": "owner_id,event_id,revision,role,source,amount,currency,missing_reason",
        "quantity_movements": "owner_id,event_id,revision,position_id,amount",
        "cash_movements": "owner_id,event_id,revision,account_id,currency,amount",
    }
    for table in TABLES:
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC,trading_runtime,trading_auth")
        op.execute(f"""
            CREATE POLICY event_owner ON app.{table} TO trading_runtime
            USING (owner_id=app.current_owner_id() AND EXISTS (SELECT 1 FROM app.owners
                WHERE id=app.current_owner_id() AND is_active))
            WITH CHECK (owner_id=app.current_owner_id() AND EXISTS (SELECT 1 FROM app.owners
                WHERE id=app.current_owner_id() AND is_active))
        """)
        op.execute(f"GRANT SELECT,INSERT ({columns[table]}) ON app.{table} TO trading_runtime")
        op.execute(f"""
            CREATE CONSTRAINT TRIGGER check_financial_event AFTER INSERT ON app.{table}
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION app.check_financial_event()
        """)
    op.execute("""
        CREATE FUNCTION app.serialize_financial_write() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE lock_key bigint;
        BEGIN
            IF current_user='trading_runtime' THEN
                IF NEW.owner_id IS DISTINCT FROM app.current_owner_id() THEN
                    RAISE EXCEPTION 'Financial owner context is unavailable';
                END IF;
                -- Match AccountTransaction's signed first eight SHA-256 bytes exactly.
                lock_key := ('x'||substr(encode(sha256(convert_to('accounts/v1','UTF8')||
                    uuid_send(NEW.owner_id)), 'hex'),1,16))::bit(64)::bigint;
                PERFORM pg_advisory_xact_lock(lock_key);
            END IF;
            RETURN NEW;
        END $f$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.serialize_financial_write() FROM PUBLIC")
    for table in SERIALIZED:
        operations = "INSERT OR UPDATE" if table == "financial_accounts" else "INSERT"
        op.execute(
            f"CREATE TRIGGER a_serialize_financial_write BEFORE {operations} "
            f"ON app.{table} FOR EACH ROW EXECUTE FUNCTION app.serialize_financial_write()"
        )


def downgrade() -> None:
    for table in SERIALIZED:
        op.execute(f"DROP TRIGGER a_serialize_financial_write ON app.{table}")
    op.execute("DROP FUNCTION app.serialize_financial_write()")
    for table in ("import_batches", "staged_rows"):
        op.execute(f"DROP TRIGGER guard_staging_contract ON app.{table}")
    op.execute("DROP FUNCTION app.guard_staging_contract()")
    op.execute("DROP TRIGGER guard_event_review ON app.review_decisions")
    op.execute("DROP FUNCTION app.guard_event_review()")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE app.{table}")
    op.execute("DROP FUNCTION app.check_financial_event()")
    op.execute("ALTER TABLE app.account_positions DROP CONSTRAINT position_event_context")
    op.execute("ALTER TABLE app.staged_rows DROP COLUMN posting_state")
    op.execute("ALTER TABLE app.import_batches DROP COLUMN contract_version")
