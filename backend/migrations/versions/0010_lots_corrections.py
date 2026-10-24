"""Sourced lot observations and immutable financial correction versions."""

from alembic import op

revision = "0010_lots_corrections"
down_revision = "0009_financial_events"
branch_labels = None
depends_on = None

TABLES = ("lots", "lot_observations", "lot_components")

# Exact prior definitions are retained here for a self-contained disposable downgrade.

PREVIOUS_VALUE = """
        CREATE OR REPLACE FUNCTION app.valid_staged_value(role text, source text, amount numeric,
            currency text, missing text) RETURNS boolean
        LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE digits integer;
        BEGIN
            IF role NOT IN ('quantity','net_cash','gross_cash','unit_price','fee','withholding',
                'acquisition_cost','reported_tax_basis') OR role IS NULL THEN RETURN false;
                END IF;
            IF (role='quantity' AND currency IS NOT NULL) OR (role<>'quantity' AND
                (currency IS NULL OR currency NOT IN ('INR','USD'))) THEN RETURN false; END IF;
            IF source IS NULL THEN
                RETURN amount IS NULL AND missing IS NOT NULL AND missing IN
                    ('not_supplied','incomplete_history','unsupported','conflicting_evidence');
            END IF;
            IF amount IS NULL OR missing IS NOT NULL OR length(source)>32 OR source !~
                '^-?(0|[1-9][0-9]{0,17})([.][0-9]{1,12})?$' THEN RETURN false; END IF;
            digits := CASE WHEN role IN ('net_cash','gross_cash') THEN 2
                WHEN role IN ('quantity','unit_price') THEN 12 ELSE 8 END;
            RETURN amount<>'NaN'::numeric AND abs(amount)<1000000000000000000::numeric
                AND scale(amount)<=digits AND scale(source::numeric)<=digits
                AND source::numeric=amount AND (role<>'unit_price' OR amount>0);
        END $f$
    """

PREVIOUS_ISSUE = """
        CREATE OR REPLACE FUNCTION app.import_row_issue(own uuid, row_key uuid) RETURNS text
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE r record; quantity numeric; cash numeric;
        BEGIN
            SELECT * INTO r FROM app.staged_rows WHERE owner_id=own AND id=row_key;
            IF NOT FOUND THEN RETURN 'unavailable'; END IF;
            IF r.blocked_reason IS NOT NULL THEN RETURN r.blocked_reason; END IF;
            IF r.kind='unsupported' THEN RETURN 'unsupported'; END IF;
            IF EXISTS (SELECT 1 FROM app.staged_values WHERE owner_id=own AND row_id=row_key
                AND NOT CASE
                    WHEN r.kind IN ('cash_snapshot','fee','withholding') THEN role='net_cash'
                    WHEN r.kind='cash_movement' THEN role IN ('net_cash','fee','withholding')
                    WHEN r.kind='dividend' THEN role IN
                        ('net_cash','gross_cash','fee','withholding')
                    WHEN r.kind IN ('buy','sell','subscription','redemption') THEN role IN
                        ('quantity','net_cash','gross_cash','unit_price','fee','withholding')
                    ELSE role IN ('quantity','unit_price','acquisition_cost',
                        'reported_tax_basis','fee','withholding') END) THEN
                RETURN 'unsupported_component';
            END IF;
            SELECT amount INTO quantity FROM app.staged_values WHERE owner_id=own AND
                row_id=row_key AND role='quantity';
            SELECT amount INTO cash FROM app.staged_values WHERE owner_id=own AND
                row_id=row_key AND role='net_cash';
            IF r.kind IN ('buy','sell','subscription','redemption') THEN
                IF r.trade_date IS NULL OR quantity IS NULL OR cash IS NULL THEN RETURN
                'not_supplied'; END IF;
            ELSIF r.kind IN ('position_snapshot','lot_acquisition','lot_remaining',
                'cash_snapshot') THEN
                IF r.as_of_date IS NULL OR (r.kind='cash_snapshot' AND cash IS NULL)
                    OR (r.kind<>'cash_snapshot' AND quantity IS NULL) THEN RETURN
                'not_supplied'; END IF;
            ELSIF r.booking_date IS NULL OR cash IS NULL THEN RETURN 'not_supplied'; END IF;
            IF r.kind IN ('buy','sell','subscription','redemption','dividend',
                'position_snapshot','lot_acquisition','lot_remaining')
                AND r.instrument_identifier_id IS NULL THEN RETURN 'unresolved_instrument';
                END IF;
            IF (r.kind IN ('buy','subscription') AND (quantity<=0 OR cash>=0))
                OR (r.kind IN ('sell','redemption') AND (quantity>=0 OR cash<=0))
                OR (r.kind IN ('position_snapshot','lot_acquisition','lot_remaining',
                'cash_snapshot') AND quantity<0)
                OR (r.kind='dividend' AND cash<0) OR (r.kind IN ('fee','withholding') AND cash>0)
                THEN RETURN 'conflicting_evidence'; END IF;
            RETURN NULL;
        END $f$
    """

PREVIOUS_CONTRACT = """
        CREATE OR REPLACE FUNCTION app.guard_staging_contract() RETURNS trigger
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
    """

PREVIOUS_REVIEW = """
        CREATE OR REPLACE FUNCTION app.guard_event_review() RETURNS trigger
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
    """

PREVIOUS_EVENT = """
        CREATE OR REPLACE FUNCTION app.check_financial_event() RETURNS trigger
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
    """


def upgrade() -> None:
    op.execute(
        "ALTER TABLE app.import_batches DROP CONSTRAINT import_batches_contract_version_check"
    )
    op.execute("ALTER TABLE app.import_batches ADD CHECK (contract_version IN (1,2,3))")
    op.execute("ALTER TABLE app.import_batches ALTER COLUMN contract_version SET DEFAULT 3")
    op.execute("ALTER TABLE app.staged_rows DROP CONSTRAINT staged_rows_kind_check")
    op.execute("""
        ALTER TABLE app.staged_rows ADD CHECK (kind IN ('cash_movement','buy','sell',
            'subscription','redemption','dividend','fee','withholding','position_snapshot',
            'cash_snapshot','lot_acquisition','lot_remaining','cancellation','unsupported')),
        ADD COLUMN acquisition_date date CHECK (acquisition_date BETWEEN
            DATE '0001-01-01' AND DATE '9999-12-31'),
        ADD CONSTRAINT staged_acquisition_kind CHECK (acquisition_date IS NULL OR
            kind IN ('lot_acquisition','lot_remaining')),
        ADD CONSTRAINT staged_cancellation_state CHECK
            (kind<>'cancellation' OR posting_state IS NULL)
    """)
    op.execute("GRANT INSERT (acquisition_date) ON app.staged_rows TO trading_runtime")
    op.execute(
        PREVIOUS_VALUE.replace(
            "'acquisition_cost','reported_tax_basis')",
            "'acquisition_cost','reported_tax_basis','discount_amount')",
        )
    )
    issue = PREVIOUS_ISSUE.replace(
        "IF r.kind='unsupported' THEN RETURN 'unsupported'; END IF;",
        """IF r.kind='unsupported' THEN RETURN 'unsupported'; END IF;
            IF r.kind='cancellation' THEN
                IF r.value_count<>0 OR r.posting_state IS NOT NULL THEN
                    RETURN 'unsupported_component'; END IF;
                IF r.booking_date IS NULL THEN RETURN 'not_supplied'; END IF;
                RETURN NULL;
            END IF;
            IF r.kind IN ('lot_acquisition','lot_remaining') AND
                (current_user='trading_runtime' OR EXISTS (SELECT 1 FROM app.import_batches
                    WHERE owner_id=own AND id=r.batch_id AND contract_version>=3)) AND (
                r.acquisition_date>r.as_of_date OR EXISTS (SELECT 1 FROM app.staged_values
                    WHERE owner_id=own AND row_id=row_key AND ((role IN
                        ('acquisition_cost','reported_tax_basis','discount_amount') AND amount<0)
                        OR (r.kind='lot_acquisition' AND role='quantity' AND amount=0)))) THEN
                RETURN 'conflicting_evidence';
            END IF;""",
    ).replace(
        "ELSE role IN ('quantity','unit_price','acquisition_cost',",
        """WHEN r.kind IN ('lot_acquisition','lot_remaining') THEN role IN
                        ('quantity','unit_price','acquisition_cost','reported_tax_basis',
                         'fee','withholding','discount_amount')
                    ELSE role IN ('quantity','unit_price','acquisition_cost',""",
    )
    op.execute(issue)
    op.execute("""
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
    """)
    op.execute(
        "CREATE TRIGGER guard_staging_contract BEFORE INSERT ON app.staged_values FOR EACH "
        "ROW EXECUTE FUNCTION app.guard_staging_contract()"
    )
    op.execute("""
        ALTER TABLE app.financial_events ADD COLUMN status text NOT NULL DEFAULT 'active'
            CHECK (status IN ('active','cancelled')),
        ADD COLUMN correction_reason text CHECK (correction_reason IN
            ('source_correction','posting_update','cancellation','reinstatement')),
        DROP CONSTRAINT financial_events_value_count_check,
        ADD CHECK ((status='active' AND value_count BETWEEN 1 AND 8) OR
                   (status='cancelled' AND value_count=0))
    """)
    op.execute("GRANT INSERT (status,correction_reason) ON app.financial_events TO trading_runtime")
    op.execute("""
        CREATE TABLE app.lots (
            owner_id uuid NOT NULL, id uuid NOT NULL CHECK
                (id<>'00000000-0000-0000-0000-000000000000'),
            position_id uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,id),
            FOREIGN KEY (owner_id,position_id) REFERENCES app.account_positions(owner_id,id)
        )
    """)
    op.execute("CREATE INDEX lots_position ON app.lots(owner_id,position_id,id)")
    op.execute("""
        CREATE TABLE app.lot_observations (
            owner_id uuid NOT NULL, id uuid NOT NULL CHECK
                (id<>'00000000-0000-0000-0000-000000000000'),
            revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
            previous_revision bigint, lot_id uuid NOT NULL,
            scope text NOT NULL CHECK (scope IN ('lot_acquisition','lot_remaining')),
            source_row_id uuid NOT NULL, source_review_revision bigint NOT NULL,
            status text NOT NULL CHECK (status IN ('active','cancelled')),
            correction_reason text CHECK (correction_reason IN
                ('source_correction','cancellation','reinstatement')),
            as_of_date date, acquisition_date date, booking_date date,
            value_count integer NOT NULL,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,id,revision), UNIQUE (owner_id,source_row_id),
            FOREIGN KEY (owner_id,lot_id) REFERENCES app.lots(owner_id,id),
            FOREIGN KEY (owner_id,id,previous_revision)
                REFERENCES app.lot_observations(owner_id,id,revision)
                DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY (owner_id,source_row_id,source_review_revision)
                REFERENCES app.review_decisions(owner_id,row_id,revision),
            CHECK ((revision=1 AND previous_revision IS NULL) OR (revision>1 AND
                previous_revision IS NOT NULL AND previous_revision=revision-1)),
            CHECK ((status='active' AND value_count BETWEEN 1 AND 8 AND as_of_date IS NOT NULL)
                OR (status='cancelled' AND value_count=0)),
            CHECK (acquisition_date<=as_of_date)
        )
    """)
    op.execute(
        "CREATE INDEX lot_observations_lot ON app.lot_observations(owner_id,lot_id,id,revision)"
    )
    op.execute("""
        CREATE TABLE app.lot_components (
            owner_id uuid NOT NULL, observation_id uuid NOT NULL, revision bigint NOT NULL,
            role text NOT NULL, source text, amount numeric, currency text, missing_reason text,
            PRIMARY KEY (owner_id,observation_id,revision,role),
            FOREIGN KEY (owner_id,observation_id,revision)
                REFERENCES app.lot_observations(owner_id,id,revision),
            CHECK (app.valid_staged_value(role,source,amount,currency,missing_reason)),
            CHECK (role NOT IN ('acquisition_cost','reported_tax_basis','discount_amount')
                OR amount IS NULL OR amount>=0)
        )
    """)
    _review_context()
    _record_constraints()
    _privileges()


def _review_context() -> None:
    op.execute("""
        CREATE FUNCTION app.check_record_review(own uuid,row_key uuid,review bigint,
            account uuid,instrument uuid,allow_absent boolean) RETURNS void
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE r record; d record; mapped_account uuid; mapped_instrument uuid;
        BEGIN
            SELECT s.*,b.observation_id,b.revision AS batch_revision INTO r
                FROM app.staged_rows s JOIN app.import_batches b
                    ON b.owner_id=s.owner_id AND b.id=s.batch_id
                WHERE s.owner_id=own AND s.id=row_key;
            SELECT * INTO d FROM app.review_decisions WHERE owner_id=own
                AND row_id=row_key AND revision=review;
            IF d.action IS DISTINCT FROM 'include' OR app.import_row_issue(own,row_key)
                IS NOT NULL THEN RAISE EXCEPTION 'Record evidence is unavailable'; END IF;
            SELECT account_id INTO mapped_account FROM app.source_account_mappings
                WHERE owner_id=own AND source_id=d.source_id
                    AND revision=d.account_mapping_revision;
            SELECT instrument_id INTO mapped_instrument FROM app.instrument_mappings
                WHERE owner_id=own AND identifier_id=d.instrument_identifier_id
                    AND revision=d.instrument_mapping_revision;
            IF mapped_account IS DISTINCT FROM account OR
                ((NOT allow_absent OR d.instrument_identifier_id IS NOT NULL) AND
                    mapped_instrument IS DISTINCT FROM instrument) THEN
                RAISE EXCEPTION 'Record mapping is inconsistent'; END IF;
            IF current_user='trading_runtime' AND (
                EXISTS (SELECT 1 FROM app.review_decisions WHERE owner_id=own AND row_id=row_key
                    AND revision>review)
                OR EXISTS (SELECT 1 FROM app.import_batches WHERE owner_id=own AND
                    observation_id=r.observation_id AND revision>r.batch_revision)
                OR EXISTS (SELECT 1 FROM app.source_observations WHERE owner_id=own AND
                    previous_id=r.observation_id)
                OR EXISTS (SELECT 1 FROM app.source_account_mappings WHERE owner_id=own
                    AND source_id=d.source_id AND revision>d.account_mapping_revision)
                OR EXISTS (SELECT 1 FROM app.instrument_mappings WHERE owner_id=own AND
                    identifier_id=d.instrument_identifier_id
                    AND revision>d.instrument_mapping_revision)
                OR NOT EXISTS (SELECT 1 FROM app.financial_accounts WHERE owner_id=own
                    AND id=account AND archived_at IS NULL)) THEN
                RAISE EXCEPTION 'Record review context is stale'; END IF;
        END $f$
    """)
    op.execute(
        "REVOKE ALL ON FUNCTION app.check_record_review(uuid,uuid,bigint,uuid,uuid,boolean) "
        "FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.check_record_review(uuid,uuid,bigint,uuid,uuid,"
        "boolean) TO trading_runtime"
    )
    op.execute(
        PREVIOUS_REVIEW.replace(
            "WHERE owner_id=NEW.owner_id AND source_row_id=NEW.row_id) THEN",
            "WHERE owner_id=NEW.owner_id AND source_row_id=NEW.row_id) OR EXISTS (SELECT 1 "
            "FROM app.lot_observations WHERE owner_id=NEW.owner_id AND "
            "source_row_id=NEW.row_id) THEN",
        )
    )


def _record_constraints() -> None:
    op.execute("""
        CREATE FUNCTION app.check_cancelled_event(own uuid,event_key uuid,version bigint)
        RETURNS void LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE e record; s record;
        BEGIN
            SELECT * INTO e FROM app.financial_events WHERE owner_id=own AND id=event_key
                AND revision=version;
            SELECT * INTO s FROM app.staged_rows WHERE owner_id=own AND id=e.source_row_id;
            PERFORM app.check_record_review(own,e.source_row_id,e.source_review_revision,
                e.account_id,e.instrument_id,true);
            IF s.kind IS DISTINCT FROM 'cancellation' OR e.value_count<>0 OR
                s.trade_date IS DISTINCT FROM e.trade_date OR
                s.settlement_date IS DISTINCT FROM e.settlement_date OR
                s.booking_date IS DISTINCT FROM e.booking_date OR
                s.value_date IS DISTINCT FROM e.value_date OR EXISTS (
                    SELECT 1 FROM app.event_components WHERE owner_id=own AND event_id=event_key
                        AND revision=version) OR EXISTS (
                    SELECT 1 FROM app.cash_movements WHERE owner_id=own AND event_id=event_key
                        AND revision=version) OR EXISTS (
                    SELECT 1 FROM app.quantity_movements WHERE owner_id=own AND event_id=event_key
                        AND revision=version) THEN
                RAISE EXCEPTION 'Cancellation evidence is inconsistent'; END IF;
        END $f$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.check_cancelled_event(uuid,uuid,bigint) FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.check_cancelled_event(uuid,uuid,bigint) TO trading_runtime"
    )
    op.execute(
        PREVIOUS_EVENT.replace("e.revision<>1 OR EXISTS", "EXISTS").replace(
            "IF NOT FOUND THEN RAISE EXCEPTION 'Event is unavailable'; END IF;",
            """IF NOT FOUND THEN RAISE EXCEPTION 'Event is unavailable'; END IF;
            IF e.status='cancelled' THEN
                PERFORM app.check_cancelled_event(e.owner_id,e.id,e.revision);
                RETURN NULL;
            END IF;""",
        )
    )
    op.execute("""
        CREATE FUNCTION app.check_record_version() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE prior record;
        BEGIN
            IF TG_TABLE_NAME='financial_events' THEN
                IF EXISTS (SELECT 1 FROM app.lot_observations WHERE owner_id=NEW.owner_id
                    AND source_row_id=NEW.source_row_id) THEN
                    RAISE EXCEPTION 'Source occurrence is already consumed'; END IF;
                IF NEW.revision>1 THEN
                    SELECT * INTO prior FROM app.financial_events WHERE owner_id=NEW.owner_id
                        AND id=NEW.id AND revision=NEW.previous_revision;
                    IF NOT FOUND OR NEW.account_id<>prior.account_id OR
                        NEW.position_id IS DISTINCT FROM prior.position_id OR
                        NEW.instrument_id IS DISTINCT FROM prior.instrument_id
                        OR NEW.kind<>prior.kind
                        OR (NEW.status='cancelled' AND NEW.posting_state<>prior.posting_state) THEN
                        RAISE EXCEPTION 'Correction identity is inconsistent'; END IF;
                    IF NEW.correction_reason='posting_update' AND (
                        prior.posting_state<>'pending' OR NEW.posting_state<>'posted' OR
                        NEW.trade_date IS DISTINCT FROM prior.trade_date OR
                        NEW.value_count<>prior.value_count OR EXISTS (
                            SELECT role,amount,currency,missing_reason FROM app.event_components
                                WHERE owner_id=NEW.owner_id AND event_id=NEW.id
                                    AND revision=prior.revision
                            EXCEPT SELECT role,amount,currency,missing_reason
                                FROM app.event_components
                                WHERE owner_id=NEW.owner_id AND event_id=NEW.id
                                    AND revision=NEW.revision)) THEN
                        RAISE EXCEPTION 'Posting update changes economic evidence'; END IF;
                END IF;
            ELSE
                IF EXISTS (SELECT 1 FROM app.financial_events WHERE owner_id=NEW.owner_id
                    AND source_row_id=NEW.source_row_id) THEN
                    RAISE EXCEPTION 'Source occurrence is already consumed'; END IF;
                IF NEW.revision>1 THEN
                    SELECT * INTO prior FROM app.lot_observations WHERE owner_id=NEW.owner_id
                        AND id=NEW.id AND revision=NEW.previous_revision;
                    IF NOT FOUND OR NEW.lot_id<>prior.lot_id OR NEW.scope<>prior.scope THEN
                        RAISE EXCEPTION 'Correction identity is inconsistent'; END IF;
                END IF;
            END IF;
            IF NEW.revision=1 THEN
                IF NEW.status<>'active' OR NEW.correction_reason IS NOT NULL THEN
                    RAISE EXCEPTION 'Initial evidence cannot be a correction'; END IF;
            ELSIF NEW.correction_reason IS NULL OR NOT (
                (NEW.status='cancelled' AND prior.status='active'
                    AND NEW.correction_reason='cancellation')
                OR (NEW.status='active' AND prior.status='cancelled'
                    AND NEW.correction_reason='reinstatement')
                OR (NEW.status='active' AND prior.status='active' AND NEW.correction_reason IN
                    ('source_correction','posting_update'))) THEN
                RAISE EXCEPTION 'Correction transition is inconsistent';
            END IF;
            RETURN NULL;
        END $f$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.check_record_version() FROM PUBLIC")
    for table in ("financial_events", "lot_observations"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER check_record_version AFTER INSERT ON app.{table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
            "app.check_record_version()"
        )
    _lot_constraints()


def _lot_constraints() -> None:
    op.execute("""
        CREATE FUNCTION app.check_lot_observation() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE record_key uuid; e record; s record; position record; native text;
        BEGIN
            IF TG_TABLE_NAME='lot_observations' THEN record_key:=NEW.id;
            ELSE record_key:=NEW.observation_id; END IF;
            SELECT * INTO e FROM app.lot_observations WHERE owner_id=NEW.owner_id
                AND id=record_key AND revision=NEW.revision;
            SELECT * INTO s FROM app.staged_rows WHERE owner_id=e.owner_id AND id=e.source_row_id;
            SELECT p.* INTO position FROM app.lots l JOIN app.account_positions p
                ON p.owner_id=l.owner_id AND p.id=l.position_id
                WHERE l.owner_id=e.owner_id AND l.id=e.lot_id;
            IF e.id IS NULL OR position.id IS NULL THEN
                RAISE EXCEPTION 'Lot is unavailable'; END IF;
            PERFORM app.check_record_review(e.owner_id,e.source_row_id,e.source_review_revision,
                position.account_id,position.instrument_id,e.status='cancelled');
            IF s.as_of_date IS DISTINCT FROM e.as_of_date OR
                s.acquisition_date IS DISTINCT FROM e.acquisition_date OR
                s.booking_date IS DISTINCT FROM e.booking_date OR s.value_count<>e.value_count
                OR (e.status='cancelled' AND s.kind<>'cancellation') OR
                (e.status='active' AND s.kind<>e.scope) OR
                (SELECT count(*) FROM app.lot_components WHERE owner_id=e.owner_id
                    AND observation_id=e.id AND revision=e.revision)<>e.value_count OR EXISTS (
                    SELECT role,source,amount,currency,missing_reason FROM app.staged_values
                        WHERE owner_id=e.owner_id AND row_id=e.source_row_id
                    EXCEPT SELECT role,source,amount,currency,missing_reason FROM app.lot_components
                        WHERE owner_id=e.owner_id AND observation_id=e.id
                            AND revision=e.revision) THEN
                RAISE EXCEPTION 'Lot evidence is inconsistent'; END IF;
            IF e.status='active' THEN
                IF NOT EXISTS (SELECT 1 FROM app.lot_components WHERE owner_id=e.owner_id
                    AND observation_id=e.id AND revision=e.revision AND role='quantity'
                    AND amount>=0 AND (e.scope<>'lot_acquisition' OR amount>0)) THEN
                    RAISE EXCEPTION 'Lot quantity is unavailable'; END IF;
                SELECT coalesce(l.quote_currency,i.fund_currency) INTO native
                    FROM app.review_decisions d JOIN app.instrument_mappings m
                        ON m.owner_id=d.owner_id AND m.identifier_id=d.instrument_identifier_id
                        AND m.revision=d.instrument_mapping_revision
                    JOIN app.instruments i ON i.owner_id=m.owner_id AND i.id=m.instrument_id
                    LEFT JOIN app.instrument_listings l ON l.owner_id=m.owner_id
                        AND l.id=m.listing_id
                    WHERE d.owner_id=e.owner_id AND d.row_id=e.source_row_id
                        AND d.revision=e.source_review_revision;
                IF native IS NOT NULL AND EXISTS (SELECT 1 FROM app.lot_components
                    WHERE owner_id=e.owner_id AND observation_id=e.id AND revision=e.revision
                        AND role='unit_price' AND currency<>native) THEN
                    RAISE EXCEPTION 'Lot price currency is inconsistent'; END IF;
            END IF;
            RETURN NULL;
        END $f$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.check_lot_observation() FROM PUBLIC")
    for table in ("lot_observations", "lot_components"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER check_lot_observation AFTER INSERT ON app.{table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
            "app.check_lot_observation()"
        )


def _privileges() -> None:
    columns = {
        "lots": "owner_id,id,position_id",
        "lot_observations": "owner_id,id,revision,previous_revision,lot_id,scope,source_row_id,"
        "source_review_revision,status,correction_reason,as_of_date,acquisition_date,"
        "booking_date,value_count",
        "lot_components": "owner_id,observation_id,revision,role,source,amount,"
        "currency,missing_reason",
    }
    for table in TABLES:
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC,trading_runtime,trading_auth")
        op.execute(f"""
            CREATE POLICY lot_owner ON app.{table} TO trading_runtime
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
    # Destructive downgrades are allowed only by the guarded disposable test runner.
    op.execute("""
        DO $f$ BEGIN
            IF EXISTS (SELECT 1 FROM app.import_batches WHERE contract_version=3)
                OR EXISTS (SELECT 1 FROM app.lots)
                OR EXISTS (SELECT 1 FROM app.financial_events WHERE revision>1) THEN
                RAISE EXCEPTION 'New financial evidence cannot be downgraded';
            END IF;
        END $f$
    """)
    op.execute("DROP TRIGGER check_record_version ON app.financial_events")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE app.{table}")
    op.execute("DROP FUNCTION app.check_lot_observation()")
    op.execute("DROP FUNCTION app.check_record_version()")
    op.execute(PREVIOUS_EVENT)
    op.execute(PREVIOUS_REVIEW)
    op.execute("DROP FUNCTION app.check_cancelled_event(uuid,uuid,bigint)")
    op.execute("DROP FUNCTION app.check_record_review(uuid,uuid,bigint,uuid,uuid,boolean)")
    op.execute("ALTER TABLE app.financial_events DROP COLUMN status, DROP COLUMN correction_reason")
    op.execute(
        "ALTER TABLE app.financial_events ADD CONSTRAINT financial_events_value_count_check "
        "CHECK (value_count BETWEEN 1 AND 8)"
    )
    op.execute("DROP TRIGGER guard_staging_contract ON app.staged_values")
    op.execute(PREVIOUS_CONTRACT)
    op.execute(PREVIOUS_ISSUE)
    op.execute(PREVIOUS_VALUE)
    op.execute(
        "ALTER TABLE app.staged_rows DROP COLUMN acquisition_date, DROP CONSTRAINT "
        "staged_cancellation_state, DROP CONSTRAINT staged_rows_kind_check"
    )
    op.execute("""
        ALTER TABLE app.staged_rows ADD CHECK (kind IN ('cash_movement','buy','sell','subscription',
            'redemption','dividend','fee','withholding','position_snapshot','cash_snapshot',
            'lot_acquisition','lot_remaining','unsupported'))
    """)
    op.execute(
        "ALTER TABLE app.import_batches DROP CONSTRAINT import_batches_contract_version_check"
    )
    op.execute("ALTER TABLE app.import_batches ADD CHECK (contract_version IN (1,2))")
    op.execute("ALTER TABLE app.import_batches ALTER COLUMN contract_version SET DEFAULT 2")
